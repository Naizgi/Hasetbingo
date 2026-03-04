# utils/game_manager.py - Game logic manager with server-side coordination
# FIXED VERSION: Single source of truth for game state management
# FIX: Removed duplicate payment in process_winner method
# FIXED: Commission calculation based on actual player count, not prize pool
# FIXED: 4 corners pattern verification now checked first
# ADDED: Detailed logging for bingo verification debugging
# CRITICAL FIX: Prevent multiple concurrent card_purchase games and ensure refunds
# ULTRA-FAST BINGO VERIFICATION: Optimized for lightning-fast claims
# FIXED: Added stuck game recovery for active phase
# FIXED: Handle AttributeError from number_caller.is_calling_numbers_for_game
# ADDED: record_game_commission method for commission tracking
# CRITICAL FIX: 10-second winner display with proper announcement and countdown
# FIXED: Winner display countdown stuck at 5 seconds issue
# INTEGRATION: Added FakeUserManager integration for simulated players
# NUMBER CALLING: Reduced from 5 seconds to 4 seconds
# TWO WINNER SUPPORT: Added support for 2 winners with 50-50 prize split
# ==================== NEW FAKE PLAYER LOGIC ====================
# RANDOM FAKE PLAYERS: Random number between 25-35 per game (decided at game creation)
# FAKE PLAYERS FROZEN: No dynamic adjustments during countdown
# EARLY BROADCAST: Fake players visible at 6-7 seconds
# REAL PLAYERS ADD: Real players join without affecting fake count
# ==================== CRITICAL FIX: MULTIPLE WINNERS SENT AT ONCE ====================
# When game ends (max winners reached), send ALL winners' complete data in a single message
# Each winner includes full card numbers and winning pattern
# ==================== FIXED: ALL winners receive complete winner data (not just final winner) ====================
# ==================== INSTANT FAKE PLAYER CARD UPDATES ====================
# Added fake_card_indices to fake_users_added and early_state_update broadcasts
# Allows frontend to mark cards as sold instantly without grid reload
# ==================== CRITICAL FIX: IMMEDIATE FAKE PLAYER BROADCAST ====================
# Fake players now broadcast IMMEDIATELY at game creation, not at 6-7 seconds
# Removed early broadcast delay to show cards from the very beginning of countdown
# ==================== CRITICAL FIX: ENSURE CARD NUMBERS ALWAYS IN WINNER DATA ====================
# Added _ensure_winner_card_numbers method to guarantee card numbers in all winner broadcasts
# Modified get_winners to validate and fix card numbers when retrieving winners
# Updated process_winner and process_fake_winner to use these fixes
# ==================== ADDED: Force game reset endpoint support ====================
# Added force_game_completion method to properly reset game state
# Added clear_all_game_data method for complete cleanup
# ==================== CRITICAL FIX: DUPLICATE GAME PREVENTION ====================
# Added strict active game checking before creating any new game
# Added database-level checks for existing non-completed games
# Fixed start_new_round_game to reuse existing games instead of creating duplicates
# Fixed _schedule_next_round_after_winner_display to check for existing games first
# ==================== DATABASE-LEVEL LOCKING ====================
# Added system_state table as single source of truth
# Added atomic game creation with BEGIN IMMEDIATE
# Added get_current_game method to fetch authoritative game
# ============================================================

import asyncio
import logging
import random
import json
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Any
import time

# ==================== IMPORT WEBSOCKET SERVER ====================
try:
    from web_server import websocket_server
except ImportError:
    logger = logging.getLogger(__name__)
    logger.warning("WebSocket server not available - broadcasts will fail")
    websocket_server = None

# ==================== INTEGRATION: Import FakeUserManager ====================
from utils.fake_users import fake_user_manager, FakeUserManager

logger = logging.getLogger(__name__)

class GameManager:
    """Manages game logic and coordination - SIMPLIFIED with random fake players (25-35)"""
    
    def __init__(self):
        self.active_game = None
        self.is_initialized = False
        self._countdown_monitor_task = None
        # FIX: Add proper locks to prevent race conditions
        self._lock = asyncio.Lock()  # General lock for game operations
        self._creation_lock = asyncio.Lock()  # Lock for game creation
        self._state_lock = asyncio.Lock()  # Lock for state transitions
        self._verification_lock = asyncio.Lock()  # Lock for bingo verification
        self._initialization_complete = False
        # NEW: Track games that need refunds
        self._games_needing_refunds = set()
        # NEW: Cache for called numbers to avoid DB hits
        self._called_numbers_cache = {}
        # NEW: Cache for user cards to avoid DB hits
        self._user_cards_cache = {}
        # NEW: Fast pattern verification cache
        self._pattern_cache = {}
        # NEW: Track last activity time for active games
        self._last_activity_times = {}
        # NEW: Track if recovery is in progress
        self._recovery_in_progress = False
        # NEW: Track winner display monitoring tasks
        self._winner_display_tasks = {}
        # NEW: Track if we're transitioning between games
        self._transition_in_progress = False
        # NEW: Track stuck at 5 seconds
        self._stuck_5s_tracking = {}
        # NEW: Track completed games to prevent reprocessing
        self._completed_games = set()
        # NEW: Track game state version to prevent duplicate updates
        self._game_state_versions = {}  # game_id -> version number
        # NEW: Track last broadcast time for each game to prevent spam
        self._last_broadcast_times = {}  # game_id -> timestamp
        # NEW: Track last 5s log times to prevent stuck detection issues
        self._last_5s_log_times = {}
        # NEW: Track countdown check times for fake player early broadcast
        self._last_countdown_check = {}  # game_id -> last countdown value
        # NEW: Track if fake players have been finalized for a game
        self._fake_players_finalized = {}  # game_id -> boolean
        # ==================== NEW: Track if final winner broadcast has been sent ====================
        self._final_winner_broadcast_sent = {}  # game_id -> boolean
        
        # ==================== INTEGRATION: Fake user manager instance ====================
        self.fake_user_manager = fake_user_manager
        # NEW: Flag to enable/disable fake users (default: enabled)
        self.fake_users_enabled = True
        # NEW: Minimum number of players to start (including fake users)
        self.min_players_to_start = 2
        
        # ==================== NEW: RANDOM FAKE PLAYER RANGE (25-35) ====================
        # Random fake players between 25-35 per game - decided at game creation
        self.min_fake_players = 25  # Minimum fake players per game
        self.max_fake_players = 35  # Maximum fake players per game
        # No dynamic adjustments - once set, fake count is frozen
        
        # ==================== TWO WINNER SUPPORT: Track winners in current game ====================
        self.game_winners = {}  # game_id -> list of winner dicts
        self.max_winners = 2  # Maximum number of winners allowed per game
        self.winner_lock = asyncio.Lock()  # Lock for winner operations
        
        # ==================== GAME CONTINUITY: Auto-start games with fake players ====================
        self.auto_start_games = True  # Automatically start games with fake players
        self.game_continuity_task = None  # Background task for game continuity
        
        logger.info(f"GameManager initialized with RANDOM FAKE PLAYERS ({self.min_fake_players}-{self.max_fake_players}) per game")
    
    # ==================== SAFE BROADCAST HELPER ====================
    async def _safe_broadcast(self, message: dict, game_id: str = None):
        """Safely broadcast WebSocket message with duplicate prevention"""
        if not websocket_server:
            logger.debug("WebSocket server not available, broadcast skipped")
            return
        
        # Add timestamp if not present
        if 'timestamp' not in message:
            message['timestamp'] = datetime.now().isoformat()
        
        # Check for duplicate broadcasts to prevent spam
        if game_id and message.get('type') in ['game_state_update', 'full_state_update']:
            current_time = time.time()
            last_time = self._last_broadcast_times.get(f"{game_id}_{message.get('type')}", 0)
            
            # Only allow one state update per second to prevent spam
            if current_time - last_time < 1.0:
                logger.debug(f"Throttling duplicate broadcast for game {game_id}")
                return
            
            self._last_broadcast_times[f"{game_id}_{message.get('type')}"] = current_time
        
        try:
            await websocket_server.broadcast_with_retry(message)
        except Exception as e:
            logger.error(f"Failed to broadcast: {e}")
    
    # ==================== NEW: Get random fake player count for a game ====================
    def _get_random_fake_count(self) -> int:
        """Generate random number of fake players between min_fake_players and max_fake_players"""
        return random.randint(self.min_fake_players, self.max_fake_players)
    
    # ==================== NEW: Get current game from system_state ====================
    async def get_current_game(self):
        """
        Get the current authoritative game from system_state
        """
        try:
            from database.db import Database
            
            with Database.get_cursor() as cursor:
                cursor.execute("""
                    SELECT current_game_id 
                    FROM system_state 
                    WHERE id = 1
                """)
                row = cursor.fetchone()
                
                if not row or not row[0]:
                    return None
                
                game_id = row[0]
                
                # Get the game data
                game = await Database.get_game(game_id)
                
                # Update local cache if needed
                async with self._lock:
                    if self.active_game and self.active_game.get('game_id') != game_id:
                        self.active_game = game
                        
                        # Reinitialize tracking for this game
                        if game_id not in self.game_winners:
                            self.game_winners[game_id] = []
                        if game_id not in self._game_state_versions:
                            self._game_state_versions[game_id] = 1
                        if game_id not in self._fake_players_finalized:
                            self._fake_players_finalized[game_id] = False
                        if game_id not in self._final_winner_broadcast_sent:
                            self._final_winner_broadcast_sent[game_id] = False
                
                return game
                
        except Exception as e:
            logger.error(f"Error getting current game: {e}")
            return None
    
    async def initialize(self):
        """Initialize the game manager - FIXED: No race conditions"""
        if self._initialization_complete:
            logger.info("GameManager already initialized")
            return True
            
        async with self._creation_lock:
            if self._initialization_complete:  # Double-check pattern
                return True
                
            try:
                from database.db import Database
                
                # Initialize database
                await Database.init_db()
                await Database.migrate_db()
                
                # Initialize system_state table
                with Database.get_cursor() as cursor:
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS system_state (
                            id INTEGER PRIMARY KEY CHECK (id = 1),
                            current_game_id TEXT
                        )
                    """)
                    cursor.execute("""
                        INSERT OR IGNORE INTO system_state (id, current_game_id)
                        VALUES (1, NULL)
                    """)
                
                # FIX: Get active game from system_state
                async with self._lock:
                    self.active_game = await self.get_current_game()
                
                # CRITICAL FIX: Check for any stuck games in card_purchase phase
                await self._recover_abandoned_games()
                
                if not self.active_game:
                    # Create a new game with 30-second countdown
                    result = await self.start_new_round_game()
                    if not result.get('success'):
                        logger.error("Failed to create new game")
                        return False
                else:
                    # FIX: Handle potentially stuck games
                    game_id = self.active_game.get('game_id')
                    if game_id:
                        current_status = self.active_game.get('status', 'card_purchase')
                        current_phase = self.active_game.get('current_phase', 'card_purchase')
                        
                        # Initialize winner tracking for this game if not exists
                        if game_id not in self.game_winners:
                            self.game_winners[game_id] = []
                        
                        # Initialize state version
                        if game_id not in self._game_state_versions:
                            self._game_state_versions[game_id] = 1
                        
                        # Initialize fake players finalized flag
                        if game_id not in self._fake_players_finalized:
                            self._fake_players_finalized[game_id] = False
                        
                        # ==================== NEW: Initialize final winner broadcast flag ====================
                        if game_id not in self._final_winner_broadcast_sent:
                            self._final_winner_broadcast_sent[game_id] = False
                        
                        # ==================== NEW: Ensure fake users exist but don't change count ====================
                        if self.fake_users_enabled and current_phase == 'card_purchase':
                            # Check if we already have fake players
                            with Database.get_cursor() as cursor:
                                cursor.execute("""
                                    SELECT COUNT(*) as count FROM player_cards 
                                    WHERE game_id = ? AND is_fake = 1 AND is_active = 1
                                """, (game_id,))
                                result = cursor.fetchone()
                                current_fake_count = result['count'] if result else 0
                            
                            # If no fake players, add random count
                            if current_fake_count == 0:
                                random_fake_count = self._get_random_fake_count()
                                logger.info(f"🎲 Adding {random_fake_count} fake players to existing game {game_id}")
                                await self._add_initial_fake_users(game_id, random_fake_count)
                        
                        # NEW: Check for stuck active games
                        if current_phase == 'active' and current_status == 'active':
                            logger.info(f"Found active game {game_id}. Checking if it's stuck...")
                            # Check if number caller is running
                            try:
                                from utils.number_caller import number_caller
                                # FIX: Use safer method check
                                if hasattr(number_caller, 'is_calling_numbers_for_game'):
                                    if not number_caller.is_calling_numbers_for_game(game_id):
                                        logger.warning(f"Game {game_id} is active but number caller not running. Starting it...")
                                        await number_caller.start_number_calling_for_game(game_id)
                                else:
                                    logger.warning(f"NumberCaller missing is_calling_numbers_for_game method. Starting number calling...")
                                    await number_caller.start_number_calling_for_game(game_id)
                            except Exception as e:
                                logger.error(f"Error checking number caller: {e}")
                        
                        # Check if game is stuck in card_purchase phase
                        if current_phase == 'card_purchase' and current_status == 'card_purchase':
                            # Calculate remaining time
                            countdown = await Database.calculate_purchase_countdown(game_id)
                            
                            # If countdown is negative (stuck), reset it
                            if countdown < 0:
                                logger.warning(f"Game {game_id} appears stuck with negative countdown ({countdown}). Resetting...")
                                
                                # Check if there are any real players
                                real_players = await Database.count_game_players(game_id)
                                if real_players > 0:
                                    # Refund real players first
                                    await self._refund_all_players(game_id)
                                
                                # Clean up fake users
                                self.fake_user_manager.cleanup_game(game_id)
                                
                                # Clear winners for this game
                                if game_id in self.game_winners:
                                    del self.game_winners[game_id]
                                
                                # Clear fake finalized flag
                                if game_id in self._fake_players_finalized:
                                    del self._fake_players_finalized[game_id]
                                
                                # ==================== NEW: Clear final winner broadcast flag ====================
                                if game_id in self._final_winner_broadcast_sent:
                                    del self._final_winner_broadcast_sent[game_id]
                                
                                # Reset purchase end time
                                new_end_time = datetime.now() + timedelta(seconds=30)
                                await Database.set_purchase_end_time(game_id, new_end_time)
                                await Database.update_game_countdown(game_id, 30)
                                
                                # Refresh game data
                                async with self._lock:
                                    self.active_game = await Database.get_game(game_id)
                                
                                # Initialize winner tracking
                                self.game_winners[game_id] = []
                                
                                # Initialize fake finalized flag
                                self._fake_players_finalized[game_id] = False
                                
                                # ==================== NEW: Initialize final winner broadcast flag ====================
                                self._final_winner_broadcast_sent[game_id] = False
                                
                                # Increment state version
                                self._game_state_versions[game_id] = self._game_state_versions.get(game_id, 0) + 1
                                
                                # ==================== NEW: Add random fake users ====================
                                if self.fake_users_enabled:
                                    random_fake_count = self._get_random_fake_count()
                                    await self._add_initial_fake_users(game_id, random_fake_count)
                                
                                logger.info(f"Reset stuck game {game_id} countdown to 30 seconds")
                        
                        # If game is active but has no real players, continue with fake players
                        elif current_phase == 'active':
                            real_players = await Database.count_game_players(game_id)
                            fake_count = len(self.fake_user_manager.game_fake_cards.get(game_id, {}))
                            total_with_fake = real_players + fake_count
                            
                            # Check if we have at least 2 total players (real + fake)
                            if total_with_fake < 2:
                                logger.warning(f"Game {game_id} is active but has only {total_with_fake} total player(s) (real: {real_players}, fake: {fake_count}).")
                                # This shouldn't happen with our random initial fake players
                
                # Start countdown monitor
                self._countdown_monitor_task = asyncio.create_task(self.start_countdown_monitor())
                
                # ==================== GAME CONTINUITY: Start game continuity task ====================
                self.game_continuity_task = asyncio.create_task(self._game_continuity_monitor())
                
                self.is_initialized = True
                self._initialization_complete = True
                logger.info(f"GameManager initialized with game: {self.active_game.get('game_id') if self.active_game else 'None'}")
                return True
                
            except Exception as e:
                logger.error(f"Error initializing GameManager: {e}", exc_info=True)
                return False
    
    # ==================== NEW: Add initial fake users with random count and send card indices ====================
    
    async def _add_initial_fake_users(self, game_id: str, count: int):
        """Add initial fake users to a game - NO adjustments later"""
        try:
            if not self.fake_users_enabled:
                return
            
            logger.info(f"🎭 Adding {count} initial fake users to game {game_id}")
            
            # Select cards for fake users
            selected_fake_cards = await self.fake_user_manager.select_fake_user_cards_async(
                game_id=game_id,
                count=count
            )
            
            if selected_fake_cards:
                # Extract card indices for instant frontend updates
                fake_card_indices = [card.get('card_index') for card in selected_fake_cards if card.get('card_index')]
                
                logger.info(f"🎭 Added {len(selected_fake_cards)} fake users to game {game_id} with cards: {fake_card_indices}")
                
                # Get updated counts
                from database.db import Database
                with Database.get_cursor() as cursor:
                    cursor.execute("""
                        SELECT 
                            COUNT(CASE WHEN is_fake = 0 AND is_active = 1 THEN 1 END) as real_players,
                            COUNT(CASE WHEN is_fake = 1 AND is_active = 1 THEN 1 END) as fake_players
                        FROM player_cards 
                        WHERE game_id = ?
                    """, (game_id,))
                    row = cursor.fetchone()
                    real_players = row['real_players'] if row else 0
                    fake_players = row['fake_players'] if row else 0
                    total_players = real_players + fake_players
                    
                    # Calculate correct prize pool based on total players
                    correct_prize_pool = total_players * 8.00
                    await Database.update_prize_pool(game_id, correct_prize_pool)
                
                # Increment state version
                self._game_state_versions[game_id] = self._game_state_versions.get(game_id, 0) + 1
                
                # Broadcast full state update
                await self._broadcast_full_game_state(game_id)
                
                # ==================== CRITICAL FIX: Broadcast IMMEDIATELY, not at 6-7 seconds ====================
                # Broadcast fake users added with card indices for instant frontend update
                await self._safe_broadcast({
                    'type': 'fake_users_added',
                    'game_id': game_id,
                    'fake_users_count': len(selected_fake_cards),
                    'fake_card_indices': fake_card_indices,  # ← for instant card updates
                    'total_fake_players': fake_players,
                    'real_players': real_players,
                    'total_players': total_players,
                    'prize_pool': correct_prize_pool,
                    'max_players': 400,
                    'timestamp': datetime.now().isoformat()
                }, game_id)
                
                logger.info(f"🎭 IMMEDIATE BROADCAST: Sent {len(selected_fake_cards)} fake cards at game creation")
            
        except Exception as e:
            logger.error(f"Error adding initial fake users: {e}")
    
    # ==================== SIMPLIFIED: No dynamic fake player maintenance ====================
    # These methods are kept but simplified - they don't change fake player counts anymore
    
    async def _maintain_fake_user_levels(self, game_id: str):
        """NO-OP: Fake players are fixed and not maintained dynamically"""
        # This method intentionally does nothing - fake player counts are fixed
        pass
    
    # ==================== SIMPLIFIED: Real user join/refund handlers ====================
    
    async def handle_real_user_join(self, game_id: str):
        """Handle when a real user joins - NO fake player removal"""
        try:
            if not self.fake_users_enabled:
                return
            
            # Get updated counts for broadcast only
            from database.db import Database
            with Database.get_cursor() as cursor:
                cursor.execute("""
                    SELECT 
                        COUNT(CASE WHEN is_fake = 0 AND is_active = 1 THEN 1 END) as real_players,
                        COUNT(CASE WHEN is_fake = 1 AND is_active = 1 THEN 1 END) as fake_players
                    FROM player_cards 
                    WHERE game_id = ?
                """, (game_id,))
                row = cursor.fetchone()
                real_players = row['real_players'] if row else 0
                fake_players = row['fake_players'] if row else 0
                total_players = real_players + fake_players
                
                # Calculate correct prize pool based on total players
                correct_prize_pool = total_players * 8.00
                await Database.update_prize_pool(game_id, correct_prize_pool)
            
            # Increment state version
            self._game_state_versions[game_id] = self._game_state_versions.get(game_id, 0) + 1
            
            # Broadcast full state update
            await self._broadcast_full_game_state(game_id)
            
            logger.info(f"📊 Game {game_id} after real user join: Real={real_players}, Fake={fake_players}, Total={total_players}, Prize Pool={correct_prize_pool}")
            
            # Broadcast update
            await self._safe_broadcast({
                'type': 'player_count_update',
                'game_id': game_id,
                'real_players': real_players,
                'fake_players': fake_players,
                'total_players': total_players,
                'max_players': 400,
                'fake_players_remaining': fake_players,
                'timestamp': datetime.now().isoformat()
            }, game_id)
            
        except Exception as e:
            logger.error(f"Error handling real user join: {e}")
    
    async def handle_real_user_refund(self, game_id: str):
        """Handle when a real user refunds - NO fake player addition"""
        try:
            if not self.fake_users_enabled:
                return
            
            # Get updated counts for broadcast only
            from database.db import Database
            with Database.get_cursor() as cursor:
                cursor.execute("""
                    SELECT 
                        COUNT(CASE WHEN is_fake = 0 AND is_active = 1 THEN 1 END) as real_players,
                        COUNT(CASE WHEN is_fake = 1 AND is_active = 1 THEN 1 END) as fake_players
                    FROM player_cards 
                    WHERE game_id = ?
                """, (game_id,))
                row = cursor.fetchone()
                real_players = row['real_players'] if row else 0
                fake_players = row['fake_players'] if row else 0
                total_players = real_players + fake_players
                
                # Calculate correct prize pool based on total players
                correct_prize_pool = total_players * 8.00
                await Database.update_prize_pool(game_id, correct_prize_pool)
            
            # Increment state version
            self._game_state_versions[game_id] = self._game_state_versions.get(game_id, 0) + 1
            
            # Broadcast full state update
            await self._broadcast_full_game_state(game_id)
            
            logger.info(f"📊 Game {game_id} after refund: Real={real_players}, Fake={fake_players}, Total={total_players}, Prize Pool={correct_prize_pool}")
            
            # Broadcast update
            await self._safe_broadcast({
                'type': 'player_count_update',
                'game_id': game_id,
                'real_players': real_players,
                'fake_players': fake_players,
                'total_players': total_players,
                'max_players': 400,
                'timestamp': datetime.now().isoformat()
            }, game_id)
            
        except Exception as e:
            logger.error(f"Error handling real user refund: {e}")
    
    # ==================== GAME CONTINUITY: Ensure games continue with fake players ====================
    
    async def _game_continuity_monitor(self):
        """Background task to ensure game continuity with fake players"""
        try:
            logger.info("Starting game continuity monitor with fake players...")
            
            while True:
                try:
                    # Check if we have an active game
                    async with self._lock:
                        active_game = self.active_game
                    
                    if not active_game:
                        # No active game, create one
                        logger.info("No active game found, creating new game with fake players...")
                        await self.start_new_round_game()
                    else:
                        game_id = active_game.get('game_id')
                        if game_id:
                            # Get game status
                            from database.db import Database
                            game = await Database.get_game(game_id)
                            
                            if game:
                                status = game.get('status', 'card_purchase')
                                phase = game.get('current_phase', 'card_purchase')
                                
                                # CRITICAL FIX: Auto-start games even with only fake players
                                if self.auto_start_games and status == 'card_purchase' and phase == 'card_purchase':
                                    # Get total players
                                    real_players = await Database.count_game_players(game_id)
                                    fake_count = len(self.fake_user_manager.game_fake_cards.get(game_id, {}))
                                    total_players = real_players + fake_count
                                    
                                    # Check countdown
                                    countdown = await Database.calculate_purchase_countdown(game_id)
                                    
                                    # FIXED: Start game if countdown <= 0 AND we have at least 2 fake players
                                    if countdown <= 0:
                                        if fake_count >= 2:
                                            logger.info(f"Auto-starting game {game_id} with {fake_count} fake players and {real_players} real players")
                                            await self.start_game_play(game_id)
                                
                                # Handle completed games
                                if status == 'completed':
                                    logger.info(f"Game {game_id} completed, starting new round with fake players")
                                    await self._schedule_next_round_after_winner_display(game_id)
                    
                    # Wait before next check
                    await asyncio.sleep(5)
                    
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error(f"Error in game continuity monitor: {e}")
                    await asyncio.sleep(10)
        
        except asyncio.CancelledError:
            logger.info("Game continuity monitor cancelled")
        except Exception as e:
            logger.error(f"Game continuity monitor stopped: {e}")
    
    # ==================== FIXED: Get total players with fake (ensures correct count) ====================
    async def get_total_players_with_fake(self, game_id: str) -> int:
        """Get total players including fake users - FIXED: Uses database as source of truth"""
        try:
            from database.db import Database
            
            with Database.get_cursor() as cursor:
                cursor.execute("""
                    SELECT COUNT(*) as count 
                    FROM player_cards 
                    WHERE game_id = ? AND is_active = 1
                """, (game_id,))
                result = cursor.fetchone()
                total = result['count'] if result else 0
            
            # Double-check with memory for consistency
            memory_fake = len(self.fake_user_manager.game_fake_cards.get(game_id, {}))
            
            if memory_fake != (total - await Database.count_game_players(game_id)):
                logger.warning(f"🎭 Fake count mismatch: DB says {total - await Database.count_game_players(game_id)}, memory says {memory_fake}")
            
            return total
        except Exception as e:
            logger.error(f"Error getting total players with fake: {e}")
            return 0
    
    # ==================== NEW: Broadcast full game state ====================
    async def _broadcast_full_game_state(self, game_id: str):
        """Broadcast complete game state to all clients - FIXED: Ensures correct counts"""
        try:
            from database.db import Database
            
            # Get complete game state
            game = await Database.get_game(game_id)
            if not game:
                return
            
            # Get player counts with a single query for efficiency
            with Database.get_cursor() as cursor:
                cursor.execute("""
                    SELECT 
                        COUNT(CASE WHEN is_fake = 0 AND is_active = 1 THEN 1 END) as real_players,
                        COUNT(CASE WHEN is_fake = 1 AND is_active = 1 THEN 1 END) as fake_players
                    FROM player_cards 
                    WHERE game_id = ?
                """, (game_id,))
                row = cursor.fetchone()
                real_players = row['real_players'] if row else 0
                fake_players = row['fake_players'] if row else 0
                total_players = real_players + fake_players
            
            # Get prize pool - should already be correct but double-check
            prize_pool = float(game.get('prize_pool', 0))
            expected_prize_pool = total_players * 8.00
            
            # Fix if there's a mismatch (shouldn't happen with our fixes)
            if abs(prize_pool - expected_prize_pool) > 0.01:
                logger.warning(f"⚠️ Prize pool mismatch in broadcast: DB={prize_pool}, Expected={expected_prize_pool}")
                prize_pool = expected_prize_pool
            
            # Broadcast full state
            await self._safe_broadcast({
                'type': 'full_state_update',
                'game_id': game_id,
                'game_state': {
                    'real_players': real_players,
                    'fake_players': fake_players,
                    'total_players': total_players,
                    'prize_pool': prize_pool,
                    'game_phase': game.get('current_phase'),
                    'game_status': game.get('status'),
                    'round_number': game.get('round_number', 1),
                    'countdown_remaining': game.get('countdown_remaining', 0)
                },
                'timestamp': datetime.now().isoformat()
            }, game_id)
            
            logger.info(f"📢 Broadcast full game state for {game_id}: Total={total_players}, Prize={prize_pool}")
            
        except Exception as e:
            logger.error(f"Error broadcasting full game state: {e}")
    
    async def mark_number_on_all_cards(self, game_id: str, number: int):
        """Mark a number on both real and fake user cards - FIXED: With error handling"""
        try:
            from database.db import Database
            
            # Mark on real user cards (done in database)
            real_updated = await Database.mark_number_on_real_cards(game_id, number)
            logger.info(f"✅ Marked number {number} on {real_updated} real cards in game {game_id}")
            
            # Mark on fake user cards
            fake_updated, fake_winners = self.fake_user_manager.mark_number_on_fake_cards(game_id, number)
            logger.info(f"✅ Marked number {number} on {fake_updated} fake cards in game {game_id}")
            
            # Process any fake winners with error handling
            for fake_card, pattern_type in fake_winners:
                user_id = fake_card['user_id']
                logger.info(f"🎭 FAKE WINNER: User {user_id} got BINGO with pattern: {pattern_type}")
                
                # Process fake winner with error handling - NOW WITH TRUE CLAIM
                try:
                    asyncio.create_task(self.process_fake_winner(game_id, user_id, fake_card, pattern_type))
                except Exception as e:
                    logger.error(f"Failed to create fake winner task: {e}")
            
            return len(fake_winners)
            
        except Exception as e:
            logger.error(f"Error marking number on all cards: {e}")
            return 0
    
    # ==================== FIXED: Fake winner processing with money going to house ====================
    async def process_fake_winner(self, game_id: str, user_id: int, fake_card: Dict, pattern_type: str):
        """
        Process a fake winner with TRUE claim data
        - Uses actual card numbers from fake_card
        - Determines winning pattern based on actual numbers
        - Creates realistic winner announcement with proper grid
        - WINNINGS GO TO HOUSE BALANCE (not fake user)
        - Uses special ×10 commission rate via record_fake_winner_commission()
        - FIXED: ALWAYS sends complete winner data for EVERY winner
        """
        try:
            from database.db import Database
            # Import websocket_server at function level to avoid circular imports
            from web_server import websocket_server
            
            logger.info(f"🎭 Processing fake winner with TRUE claim: User {user_id} in game {game_id} with pattern {pattern_type}")
            
            # Get game details
            game = await Database.get_game(game_id)
            if not game:
                logger.error(f"Game {game_id} not found for fake winner")
                return None
            
            # Check if we can add another winner
            if not await self.can_add_winner(game_id):
                logger.info(f"Game {game_id} already has maximum winners, cannot add fake winner")
                return None
            
            # Check if game already has winner(s) and number calling should be stopped
            game_status = game.get('status', 'card_purchase')
            winners_count = await self.get_winners_count(game_id)
            
            # Stop number calling on first winner only
            if winners_count == 0 and game_status != 'winner_display':
                from utils.number_caller import number_caller
                await number_caller.stop_number_calling_for_game(game_id)
            
            # Get prize pool
            prize_pool = float(game.get('prize_pool', 0.00))
            if prize_pool <= 0:
                logger.error(f"No prize pool in game {game_id} for fake winner")
                return None
            
            # Count total players
            real_players = await Database.count_game_players(game_id)
            fake_count = len(self.fake_user_manager.game_fake_cards.get(game_id, {}))
            total_players = real_players + fake_count
            
            # Get fake user details
            fake_user = self.fake_user_manager.fake_users.get(user_id, {})
            username = fake_user.get('username', f'FakeUser_{user_id}')
            full_name = fake_user.get('full_name', username)
            
            # Extract card numbers - this is the REAL card data
            card_numbers = []
            try:
                card_numbers = json.loads(fake_card['card_numbers'])
                logger.info(f"🎭 Fake winner card numbers: {card_numbers[:10]}... (first 10 of 25)")
            except Exception as e:
                logger.error(f"Error parsing fake card numbers: {e}")
                card_numbers = fake_card.get('card_numbers', [])
                if isinstance(card_numbers, str):
                    try:
                        card_numbers = json.loads(card_numbers)
                    except:
                        card_numbers = []
            
            # Get called numbers to verify pattern
            called_numbers = await Database.get_drawn_numbers(game_id)
            called_set = set(called_numbers)
            
            # ========== VERIFY the winning pattern using actual card numbers ==========
            # This ensures the fake winner's claim is TRUE
            winning_pattern = []
            verified_pattern_type = pattern_type  # Use the pattern type from detection
            
            # Double-check the pattern is actually valid
            has_bingo, verified_pattern, verified_type = await self._fast_verify_bingo_with_pattern(
                {'card_numbers': json.dumps(card_numbers) if isinstance(card_numbers, list) else card_numbers}, 
                called_numbers
            )
            
            if has_bingo:
                # Use the verified pattern numbers
                winning_pattern = verified_pattern
                verified_pattern_type = verified_type
                logger.info(f"🎯 Verified fake winner pattern: {verified_type} with numbers {winning_pattern}")
            else:
                # Fallback: generate pattern based on pattern_type
                logger.warning(f"⚠️ Fake winner pattern verification failed, using generated pattern")
                if pattern_type == "four_corners" and len(card_numbers) >= 25:
                    winning_pattern = [card_numbers[0], card_numbers[4], card_numbers[20], card_numbers[24]]
                    # Filter out 0 (FREE)
                    winning_pattern = [num for num in winning_pattern if num != 0]
                elif pattern_type.startswith("row_") and len(card_numbers) >= 25:
                    row_num = int(pattern_type.split("_")[1])
                    start_idx = row_num * 5
                    winning_pattern = card_numbers[start_idx:start_idx+5]
                    winning_pattern = [num for num in winning_pattern if num != 0]
                elif pattern_type.startswith("column_") and len(card_numbers) >= 25:
                    col_num = int(pattern_type.split("_")[1])
                    indices = [col_num + (i*5) for i in range(5)]
                    winning_pattern = [card_numbers[i] for i in indices]
                    winning_pattern = [num for num in winning_pattern if num != 0]
                elif pattern_type == "main_diagonal" and len(card_numbers) >= 25:
                    indices = [i*5 + i for i in range(5)]
                    winning_pattern = [card_numbers[i] for i in indices]
                    winning_pattern = [num for num in winning_pattern if num != 0]
                elif pattern_type == "anti_diagonal" and len(card_numbers) >= 25:
                    indices = [i*5 + (4-i) for i in range(5)]
                    winning_pattern = [card_numbers[i] for i in indices]
                    winning_pattern = [num for num in winning_pattern if num != 0]
                else:
                    winning_pattern = []
            
            # Create winner data with TRUE claim information
            winner_data = {
                'user_id': user_id,
                'username': username,
                'full_name': full_name,
                'card_index': fake_card.get('card_index'),
                'card_numbers': card_numbers,  # Full 25 numbers for grid display
                'winning_pattern': winning_pattern,  # Actual winning numbers
                'pattern_type': verified_pattern_type,  # Verified pattern type
                'is_fake': True,
                'timestamp': datetime.now().isoformat()
            }
            
            # Add to winners list
            added = await self.add_winner(game_id, winner_data)
            if not added:
                logger.info(f"Could not add fake winner to game {game_id}")
                return None
            
            winners_count = await self.get_winners_count(game_id)
            logger.info(f"🎭 Fake winner added. Game {game_id} now has {winners_count} winner(s)")
            
            # Increment state version
            self._game_state_versions[game_id] = self._game_state_versions.get(game_id, 0) + 1
            
            # Calculate payouts based on number of winners
            all_winners = await self.get_winners(game_id)
            payouts = await self.calculate_winner_payouts(game_id, prize_pool)
            
            # Get this winner's payout
            winner_index = next((i for i, w in enumerate(all_winners) if w.get('user_id') == user_id), 0)
            winner_payout = payouts[winner_index] if winner_index < len(payouts) else prize_pool
            
            # ========== CRITICAL: Fake winner money goes to HOUSE BALANCE ==========
            if winner_payout > 0:
                await Database.add_to_house_balance(
                    amount=winner_payout,
                    description=f'Fake winner #{winners_count} in game {game_id} ({verified_pattern_type})',
                    game_id=game_id
                )
                logger.info(f"🏦 Added {winner_payout} birr to house balance from fake winner")
            
            # ========== SET WINNER DISPLAY STATE ON FIRST WINNER ONLY ==========
            if winners_count == 1:
                winner_display_duration = 10  # 10 seconds for winner display
                winner_display_end = datetime.now() + timedelta(seconds=winner_display_duration)
                
                # Update game status and phase
                await Database.update_game_status(game_id, 'winner_display')
                await Database.update_game_phase(game_id, 'winner_display')
                await Database.set_winner_display_end(game_id, winner_display_end)
                
                # Update local cache
                async with self._lock:
                    self.active_game = await Database.get_game(game_id)
                
                # Start winner display monitor
                if game_id not in self._winner_display_tasks:
                    self._winner_display_tasks[game_id] = asyncio.create_task(
                        self._monitor_winner_display_countdown(game_id, winner_display_end)
                    )
            
            # ========== FIXED: ALWAYS SEND COMPLETE WINNER DATA FOR ALL WINNERS ==========
            # This sends complete data for EVERY winner, regardless of whether it's first or final
            
            # Get all winners with their complete data
            final_all_winners = await self.get_winners(game_id)
            final_payouts = await self.calculate_winner_payouts(game_id, prize_pool)
            
            # Prepare complete winners data with all details
            complete_winners_data = []
            for i, w in enumerate(final_all_winners):
                # Ensure each winner has valid card numbers
                w = await self._ensure_winner_card_numbers(game_id, w)
                
                # Get this winner's card numbers and winning pattern
                winner_card_numbers = w.get('card_numbers', [])
                winner_winning_pattern = w.get('winning_pattern', [])
                
                # Ensure winning pattern is valid
                if not winner_winning_pattern or len(winner_winning_pattern) == 0:
                    # Try to generate from pattern type
                    pattern_type = w.get('pattern_type', '')
                    if pattern_type == "four_corners" and len(winner_card_numbers) >= 25:
                        winner_winning_pattern = [
                            winner_card_numbers[0], 
                            winner_card_numbers[4], 
                            winner_card_numbers[20], 
                            winner_card_numbers[24]
                        ]
                        winner_winning_pattern = [num for num in winner_winning_pattern if num != 0]
                    elif pattern_type.startswith("row_") and len(winner_card_numbers) >= 25:
                        try:
                            row_num = int(pattern_type.split("_")[1])
                            start_idx = row_num * 5
                            winner_winning_pattern = winner_card_numbers[start_idx:start_idx+5]
                            winner_winning_pattern = [num for num in winner_winning_pattern if num != 0]
                        except:
                            pass
                    elif pattern_type.startswith("column_") and len(winner_card_numbers) >= 25:
                        try:
                            col_num = int(pattern_type.split("_")[1])
                            indices = [col_num + (i*5) for i in range(5)]
                            winner_winning_pattern = [winner_card_numbers[i] for i in indices]
                            winner_winning_pattern = [num for num in winner_winning_pattern if num != 0]
                        except:
                            pass
                
                winner_complete = {
                    'user_id': w.get('user_id'),
                    'username': w.get('username'),
                    'full_name': w.get('full_name'),
                    'card_index': w.get('card_index'),
                    'card_numbers': winner_card_numbers,  # Full 25 numbers
                    'winning_pattern': winner_winning_pattern,  # Pattern numbers
                    'pattern_type': w.get('pattern_type', 'BINGO'),
                    'prize_amount': final_payouts[i] if i < len(final_payouts) else 0,
                    'is_fake': w.get('is_fake', False),
                    'winner_number': i + 1
                }
                complete_winners_data.append(winner_complete)
            
            # Create comprehensive winner announcement with ALL winners
            final_winner_data = {
                'type': 'winner_confirmed',
                'game_id': game_id,
                'prize_pool': prize_pool,
                'max_winners': self.max_winners,
                'total_winners': len(final_all_winners),
                'is_final_winner': len(final_all_winners) >= self.max_winners,
                'winners': complete_winners_data,
                'timestamp': datetime.now().isoformat(),
                'state_version': self._game_state_versions.get(game_id, 1),
                'fake_player_stats': {
                    'min_fake_players': self.min_fake_players,
                    'max_fake_players': self.max_fake_players,
                    'current_fake_players': fake_count
                }
            }
            
            # Add corner details for 4 corners pattern if applicable
            for winner in final_all_winners:
                if winner.get('pattern_type') == "four_corners" and len(winner.get('card_numbers', [])) >= 25:
                    card_nums = winner.get('card_numbers', [])
                    if 'corner_details' not in final_winner_data:
                        final_winner_data['corner_details'] = {}
                    final_winner_data['corner_details'][winner.get('user_id')] = {
                        'top_left': card_nums[0],
                        'top_right': card_nums[4],
                        'bottom_left': card_nums[20],
                        'bottom_right': card_nums[24],
                        'corner_indices': [0, 4, 20, 24]
                    }
            
            # Broadcast the complete winner announcement
            try:
                await websocket_server.broadcast_with_retry(final_winner_data)
                logger.info(f"📢 Broadcast COMPLETE winner announcement with data for all {len(final_all_winners)} winners")
                
                # Mark that we've sent the broadcast (only after successful send)
                if len(final_all_winners) >= self.max_winners:
                    self._final_winner_broadcast_sent[game_id] = True
                    
            except Exception as e:
                logger.error(f"Failed to broadcast complete winner data: {e}")
            
            # Update game with winner info
            await Database.update_game_winner(game_id, user_id, prize_pool)
            
            # Mark fake card as winner
            fake_card['is_winner'] = True
            
            # ========== PROCESS GAME COMPLETION (record commission and finalize) ==========
            # Commission should be recorded whenever game ends, regardless of winner count
            logger.info(f"🏆 Game {game_id} ending with {winners_count} winner(s). Finalizing...")
            
            # Record game details with all winners
            await self._record_complete_game_details(
                game_id=game_id,
                winners=all_winners,
                prize_pool=prize_pool,
                winner_payouts=payouts,
                called_numbers=await Database.get_drawn_numbers(game_id),
                total_players=total_players,
                is_fake=True
            )
            
            # ========== CRITICAL CHANGE: Use special fake winner commission (×10 rate) ==========
            # Record commission with special ×10 rate for fake winners
            await self.record_fake_winner_commission(game_id)
            
            # Mark game as completed in our tracking set
            self._completed_games.add(game_id)
            
            # Clean up caches
            await self.cleanup_game_caches(game_id)
            
            return {
                'user_id': user_id,
                'username': username,
                'full_name': full_name,
                'prize_amount': winner_payout,
                'pattern_type': verified_pattern_type,
                'winning_pattern': winning_pattern,
                'status': 'winner_display' if winners_count == 1 else 'additional_winner',
                'winner_number': winners_count,
                'total_winners': winners_count,
                'is_final': len(final_all_winners) >= self.max_winners,
                'is_fake': True,
                'money_to_house': winner_payout
            }
            
        except Exception as e:
            logger.error(f"Error processing fake winner: {e}", exc_info=True)
            return None
    
    async def cleanup_fake_users(self, game_id: str):
        """Clean up fake user data for a completed game"""
        try:
            self.fake_user_manager.cleanup_game(game_id)
            if game_id in self._fake_players_finalized:
                del self._fake_players_finalized[game_id]
            # ==================== NEW: Clean up final winner broadcast flag ====================
            if game_id in self._final_winner_broadcast_sent:
                del self._final_winner_broadcast_sent[game_id]
            logger.info(f"🧹 Cleaned up fake users for game {game_id}")
        except Exception as e:
            logger.error(f"Error cleaning up fake users: {e}")
    
    # ==================== END: Fake player methods ====================
    
    # ==================== TWO WINNER SUPPORT: Winner tracking methods ====================
    
    async def can_add_winner(self, game_id: str) -> bool:
        """Check if we can add another winner to this game"""
        async with self.winner_lock:
            winners = self.game_winners.get(game_id, [])
            return len(winners) < self.max_winners
    
    async def add_winner(self, game_id: str, winner_data: Dict) -> bool:
        """Add a winner to the game's winner list"""
        async with self.winner_lock:
            if game_id not in self.game_winners:
                self.game_winners[game_id] = []
            
            # Check if user already in winners list
            user_id = winner_data.get('user_id')
            for existing_winner in self.game_winners[game_id]:
                if existing_winner.get('user_id') == user_id:
                    logger.warning(f"User {user_id} already in winners list for game {game_id}")
                    return False
            
            # Check if we haven't reached max winners
            if len(self.game_winners[game_id]) >= self.max_winners:
                logger.info(f"Game {game_id} already has {self.max_winners} winners, cannot add more")
                return False
            
            # Ensure card numbers are valid before storing
            if not winner_data.get('card_numbers') or len(winner_data.get('card_numbers', [])) != 25:
                logger.warning(f"Winner data for user {user_id} missing valid card numbers. Will fix on retrieval.")
            
            self.game_winners[game_id].append(winner_data)
            logger.info(f"✅ Added winner #{len(self.game_winners[game_id])} to game {game_id}: User {user_id}")
            
            # Increment state version
            self._game_state_versions[game_id] = self._game_state_versions.get(game_id, 0) + 1
            
            return True
    
    async def get_winners_count(self, game_id: str) -> int:
        """Get the number of winners for a game"""
        async with self.winner_lock:
            return len(self.game_winners.get(game_id, []))
    
    async def get_winners(self, game_id: str) -> List[Dict]:
        """Get all winners for a game - FIXED: Ensure card numbers are always present"""
        async with self.winner_lock:
            winners = self.game_winners.get(game_id, []).copy()
            
            # Ensure each winner has valid card numbers
            for winner in winners:
                if not winner.get('card_numbers') or len(winner.get('card_numbers', [])) != 25:
                    # Try to get from database or fake manager
                    winner = await self._ensure_winner_card_numbers(game_id, winner)
            
            return winners
    
    async def clear_winners(self, game_id: str):
        """Clear winners for a game (when game is reset/completed)"""
        async with self.winner_lock:
            if game_id in self.game_winners:
                del self.game_winners[game_id]
            # ==================== NEW: Clear final winner broadcast flag ====================
            if game_id in self._final_winner_broadcast_sent:
                del self._final_winner_broadcast_sent[game_id]
            logger.info(f"Cleared winners for game {game_id}")
    
    async def calculate_winner_payouts(self, game_id: str, prize_pool: float) -> List[float]:
        """Calculate payouts for all winners (50-50 split for 2 winners)"""
        async with self.winner_lock:
            winners = self.game_winners.get(game_id, [])
            winner_count = len(winners)
            
            if winner_count == 0:
                return []
            elif winner_count == 1:
                return [prize_pool]  # Single winner gets full prize pool
            elif winner_count == 2:
                half_pool = prize_pool / 2
                return [half_pool, half_pool]  # 50-50 split
            else:
                # Should not happen with max_winners = 2, but handle gracefully
                equal_share = prize_pool / winner_count
                return [equal_share] * winner_count
    
    # ==================== NEW: Ensure winner has valid card numbers ====================
    async def _ensure_winner_card_numbers(self, game_id: str, winner_data: Dict) -> Dict:
        """Ensure winner data has valid card numbers - FIXED for fake winners"""
        if winner_data.get('card_numbers') and len(winner_data.get('card_numbers', [])) == 25:
            return winner_data
        
        user_id = winner_data.get('user_id')
        logger.info(f"🔧 Fixing missing card numbers for winner {user_id} in game {game_id}")
        
        # Try to get from fake_user_manager first (for fake winners)
        if winner_data.get('is_fake'):
            fake_card = self.fake_user_manager.game_fake_cards.get(game_id, {}).get(user_id)
            if fake_card:
                card_numbers = fake_card.get('card_numbers', [])
                if isinstance(card_numbers, str):
                    try:
                        card_numbers = json.loads(card_numbers)
                    except:
                        card_numbers = []
                if card_numbers and len(card_numbers) == 25:
                    winner_data['card_numbers'] = card_numbers
                    logger.info(f"✅ Restored card numbers for fake winner {user_id} from memory")
                    return winner_data
        
        # Fall back to database
        from database.db import Database
        user_card = await Database.get_user_card_in_game(user_id, game_id)
        if user_card:
            card_numbers = self._extract_card_numbers(user_card)
            if card_numbers and len(card_numbers) == 25:
                winner_data['card_numbers'] = card_numbers
                logger.info(f"✅ Restored card numbers for winner {user_id} from database")
                return winner_data
        
        # Last resort: generate fallback
        logger.warning(f"⚠️ Using generated fallback card numbers for winner {user_id}")
        winner_data['card_numbers'] = self._generate_bingo_card_numbers()
        return winner_data
    
    # ==================== END: Two winner support ====================
    
    async def _recover_abandoned_games(self):
        """Recover games that were abandoned in card_purchase phase"""
        try:
            from database.db import Database
            
            # Get current game from system_state
            current_game = await self.get_current_game()
            
            if current_game:
                game_id = current_game.get('game_id')
                status = current_game.get('status')
                phase = current_game.get('current_phase')
                
                if phase == 'card_purchase' and status == 'card_purchase':
                    # Calculate remaining time
                    countdown = await Database.calculate_purchase_countdown(game_id)
                    
                    # If countdown is negative (stuck), reset it
                    if countdown < -30:  # Stuck for more than 30 seconds
                        logger.warning(f"Current game {game_id} appears stuck with negative countdown ({countdown}). Resetting...")
                        
                        # Check if there are any real players
                        real_players = await Database.count_game_players(game_id)
                        if real_players > 0:
                            # Refund real players first
                            await self._refund_all_players(game_id)
                        
                        # Clean up fake users
                        self.fake_user_manager.cleanup_game(game_id)
                        
                        # Clear winners for this game
                        await self.clear_winners(game_id)
                        
                        # Clear fake finalized flag
                        if game_id in self._fake_players_finalized:
                            del self._fake_players_finalized[game_id]
                        
                        # Clear final winner broadcast flag
                        if game_id in self._final_winner_broadcast_sent:
                            del self._final_winner_broadcast_sent[game_id]
                        
                        # Reset purchase end time
                        new_end_time = datetime.now() + timedelta(seconds=30)
                        await Database.set_purchase_end_time(game_id, new_end_time)
                        await Database.update_game_countdown(game_id, 30)
                        
                        logger.info(f"Reset stuck current game {game_id} countdown to 30 seconds")
            
        except Exception as e:
            logger.error(f"Error recovering abandoned games: {e}")
    
    async def _refund_all_players(self, game_id: str):
        """Refund all real players in a game"""
        try:
            from database.db import Database
            
            # Get all card purchases for this game
            purchases = await Database.get_all_card_purchases_for_game(game_id)
            
            logger.info(f"Refunding {len(purchases)} real player purchases in game {game_id}")
            
            for purchase in purchases:
                user_id = purchase.get('user_id')
                card_index = purchase.get('card_index')
                
                if user_id and not purchase.get('refunded', False):
                    # Process refund (full 10 birr refund)
                    success = await Database.update_balance_with_transaction(
                        user_id=user_id,
                        amount=10.00,
                        transaction_type='system_refund',
                        description=f'System refund for abandoned game {game_id}, card #{card_index}',
                        game_id=game_id
                    )
                    
                    if success:
                        # Mark purchase as refunded and inactive
                        await Database.mark_purchase_refunded_and_inactive(purchase.get('id'))
                        
                        # Remove from prize pool (8 birr)
                        await Database.remove_from_prize_pool(game_id, 8.00)
                        
                        # Deduct house commission (2 birr)
                        await Database.add_to_house_balance(
                            amount=-2.00,
                            description=f'Commission refund for abandoned game {game_id}',
                            game_id=game_id
                        )
                        
                        logger.info(f"Refunded user {user_id} for card #{card_index} in abandoned game {game_id}")
                    else:
                        logger.error(f"Failed to refund user {user_id} for card #{card_index}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error refunding players in game {game_id}: {e}")
            return False
    
    async def cleanup(self):
        """Cleanup game manager resources"""
        try:
            # Cancel countdown monitor task
            if self._countdown_monitor_task:
                self._countdown_monitor_task.cancel()
                try:
                    await self._countdown_monitor_task
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.error(f"Error cancelling countdown monitor task: {e}")
                logger.info("Countdown monitor task cancelled")
            
            # Cancel game continuity task
            if self.game_continuity_task:
                self.game_continuity_task.cancel()
                try:
                    await self.game_continuity_task
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.error(f"Error cancelling game continuity task: {e}")
                logger.info("Game continuity task cancelled")
            
            # Cancel any winner display tasks
            for game_id, task in list(self._winner_display_tasks.items()):
                if task and not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                    except Exception as e:
                        logger.error(f"Error cancelling winner display task for game {game_id}: {e}")
                    logger.info(f"Cancelled winner display task for game {game_id}")
            self._winner_display_tasks.clear()
            
            # Clean up all fake user data
            for game_id in list(self.fake_user_manager.game_fake_cards.keys()):
                self.fake_user_manager.cleanup_game(game_id)
                logger.info(f"Cleaned up fake users for game {game_id}")
            
            # Clear all winners
            self.game_winners.clear()
            
            # Clear all caches
            self._called_numbers_cache.clear()
            self._user_cards_cache.clear()
            self._pattern_cache.clear()
            self._last_activity_times.clear()
            self._stuck_5s_tracking.clear()
            self._completed_games.clear()
            self._game_state_versions.clear()
            self._last_broadcast_times.clear()
            self._last_5s_log_times.clear()
            self._last_countdown_check.clear()
            self._fake_players_finalized.clear()
            # ==================== NEW: Clear final winner broadcast flag ====================
            self._final_winner_broadcast_sent.clear()
        
        except Exception as e:
            logger.error(f"Error cleaning up game manager: {e}")
    
    async def start_countdown_monitor(self):
        """Start a background task to monitor countdowns and transition phases - FIXED: Better error handling"""
        try:
            logger.info("Starting countdown monitor with recovery...")
            
            # Run recovery check every 30 seconds
            recovery_counter = 0
            
            while True:
                try:
                    # Get the active game with lock
                    async with self._lock:
                        active_game = self.active_game
                    
                    if active_game:
                        game_id = active_game.get('game_id')
                        if game_id:
                            # Use state lock for countdown completion to prevent race conditions
                            async with self._state_lock:
                                await self.check_and_handle_countdown_completion(game_id)
                    
                    # NEW: Check for stuck active games every 10 seconds
                    if recovery_counter % 10 == 0:
                        await self._check_for_stuck_active_games()
                    
                    # NEW: Check for stuck winner displays every 15 seconds
                    if recovery_counter % 15 == 0:
                        await self._check_for_stuck_winner_displays()
                    
                    # Run recovery check every 30 iterations (30 seconds)
                    recovery_counter += 1
                    if recovery_counter >= 30:
                        await self.recover_stuck_games()
                        await self.ensure_game_continuity()
                        recovery_counter = 0
                    
                    # Wait before checking again
                    await asyncio.sleep(1)  # Check every second
                    
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error(f"Error in countdown monitor: {e}")
                    await asyncio.sleep(5)  # Wait longer on error
        
        except asyncio.CancelledError:
            logger.info("Countdown monitor cancelled")
        except Exception as e:
            logger.error(f"Countdown monitor stopped: {e}")
    
    async def _check_for_stuck_winner_displays(self):
        """Check for games stuck in winner_display phase - FIXED: More aggressive recovery"""
        try:
            from database.db import Database
            
            # Get current game from system_state
            current_game = await self.get_current_game()
            
            if not current_game:
                return
            
            game_id = current_game.get('game_id')
            if not game_id:
                return
            
            game = await Database.get_game(game_id)
            if not game:
                return
            
            status = game.get('status')
            phase = game.get('current_phase')
            
            if status != 'winner_display' or phase != 'winner_display':
                return
            
            winner_display_end = game.get('winner_display_end')
            
            if winner_display_end:
                if isinstance(winner_display_end, str):
                    try:
                        winner_display_end = datetime.fromisoformat(winner_display_end.replace('Z', '+00:00'))
                    except:
                        winner_display_end = datetime.fromisoformat(winner_display_end)
                
                current_time = datetime.now()
                
                # Calculate remaining time
                if winner_display_end > current_time:
                    remaining = (winner_display_end - current_time).total_seconds()
                    logger.info(f"⏱️ Game {game_id} winner display: {remaining:.1f}s remaining")
                    
                    # CRITICAL FIX: If stuck at 5 seconds for more than 30 seconds, force complete
                    if 4.5 <= remaining <= 5.5:
                        # Check if we've been stuck at 5 seconds
                        stuck_key = f"stuck_5s_{game_id}"
                        current_timestamp = time.time()
                        
                        if stuck_key in self._stuck_5s_tracking:
                            stuck_time = current_timestamp - self._stuck_5s_tracking[stuck_key]
                            if stuck_time > 30:  # Stuck at 5 seconds for more than 30 seconds
                                logger.warning(f"🚨 Game {game_id} stuck at 5 seconds for {stuck_time:.0f}s. Force completing!")
                                await self.force_complete_winner_display_immediately(game_id)
                                return
                        else:
                            self._stuck_5s_tracking[stuck_key] = current_timestamp
                    else:
                        # Clear stuck tracking if not at 5 seconds
                        stuck_key = f"stuck_5s_{game_id}"
                        if stuck_key in self._stuck_5s_tracking:
                            del self._stuck_5s_tracking[stuck_key]
                
                # If winner display ended more than 2 seconds ago but game is still in winner_display
                if winner_display_end <= current_time:
                    time_since_end = (current_time - winner_display_end).total_seconds()
                    
                    # If ended, force completion
                    if time_since_end > 2:
                        logger.warning(f"🚨 Game {game_id} winner display ended {time_since_end:.0f}s ago but still in winner_display. Force completing...")
                        await self.force_complete_winner_display_immediately(game_id)
        
        except Exception as e:
            logger.error(f"Error checking for stuck winner displays: {e}")
    
    async def _check_for_stuck_active_games(self):
        """Check for games stuck in active phase"""
        try:
            if self._recovery_in_progress:
                return
            
            async with self._lock:
                active_game = self.active_game
            
            if not active_game:
                return
            
            game_id = active_game.get('game_id')
            if not game_id:
                return
            
            from database.db import Database
            game = await Database.get_game(game_id)
            if not game:
                return
            
            status = game.get('status', 'card_purchase')
            phase = game.get('current_phase', 'card_purchase')
            
            # Check if game is stuck in active phase
            if status == 'active' and phase == 'active':
                game_start_time = game.get('game_start_time')
                if game_start_time:
                    time_active = (datetime.now() - game_start_time).total_seconds()
                    
                    # NEW: Check if number caller is running with error handling
                    from utils.number_caller import number_caller
                    # FIX: Use safer method check
                    try:
                        if hasattr(number_caller, 'is_calling_numbers_for_game'):
                            if not number_caller.is_calling_numbers_for_game(game_id):
                                logger.warning(f"Game {game_id} is active but number caller not running! Starting it...")
                                await number_caller.start_number_calling_for_game(game_id)
                                # Don't return, continue checking other conditions
                        else:
                            logger.warning(f"NumberCaller missing is_calling_numbers_for_game method. Starting number calling...")
                            await number_caller.start_number_calling_for_game(game_id)
                            # Don't return, continue checking other conditions
                    except Exception as e:
                        logger.error(f"Error checking number caller: {e}")
                    
                    # Check if game has been active too long without a winner
                    if time_active > 120:  # 2 minutes without a winner
                        winners_count = await self.get_winners_count(game_id)
                        if winners_count == 0:
                            logger.warning(f"Game {game_id} has been active for {time_active:.0f}s without any winner. Checking...")
                            
                            # Check if numbers have been called recently
                            last_number_time = await Database.get_last_number_call_time(game_id)
                            if last_number_time:
                                time_since_last_number = (datetime.now() - last_number_time).total_seconds()
                                if time_since_last_number > 60:  # No numbers for 1 minute
                                    logger.warning(f"Game {game_id} has no number calls for {time_since_last_number:.0f}s. Recovering...")
                                    await self._recover_stuck_active_game(game_id)
        
        except Exception as e:
            logger.error(f"Error checking for stuck active games: {e}")
    
    async def _recover_stuck_active_game(self, game_id: str):
        """Recover a game stuck in active phase"""
        if self._recovery_in_progress:
            return False
        
        self._recovery_in_progress = True
        try:
            logger.warning(f"Attempting to recover stuck active game {game_id}")
            
            from database.db import Database
            from web_server import websocket_server
            from utils.number_caller import number_caller
            
            # Stop any existing number calling
            await number_caller.stop_number_calling_for_game(game_id)
            
            # Wait a moment
            await asyncio.sleep(1)
            
            # Start fresh number calling
            success = await number_caller.start_number_calling_for_game(game_id)
            
            if success:
                # Update game state to ensure it's active
                await Database.update_game_status(game_id, 'active')
                await Database.update_game_phase(game_id, 'active')
                
                # Update last activity time
                if game_id in self._last_activity_times:
                    self._last_activity_times[game_id] = datetime.now()
                
                # Increment state version
                self._game_state_versions[game_id] = self._game_state_versions.get(game_id, 0) + 1
                
                # Broadcast recovery with error handling
                await self._safe_broadcast({
                    'type': 'game_recovered',
                    'game_id': game_id,
                    'message': 'Game has been recovered and resumed',
                    'timestamp': datetime.now().isoformat()
                }, game_id)
                
                logger.info(f"Game {game_id} recovered from stuck state")
                return True
            else:
                logger.error(f"Failed to start number caller for game {game_id}")
                return False
                
        except Exception as e:
            logger.error(f"Error recovering stuck game {game_id}: {e}")
            return False
        finally:
            self._recovery_in_progress = False
    
    async def check_and_handle_countdown_completion(self, game_id: str):
        """Check if countdown has completed and handle phase transition"""
        # Already locked by caller (start_countdown_monitor)
        try:
            from database.db import Database
            from web_server import websocket_server
            
            # Get fresh game state
            game = await Database.get_game(game_id)
            if not game:
                return False
            
            current_phase = game.get('current_phase', 'card_purchase')
            current_status = game.get('status', 'card_purchase')
            
            # ==================== FIXED: REMOVED EARLY BROADCAST AT 6-7 SECONDS ====================
            # Fake players are now broadcast immediately at game creation in _add_initial_fake_users
            # This section is intentionally removed to prevent duplicate broadcasts
            
            # Handle winner_display phase - CRITICAL FIX (10 seconds)
            if current_phase == 'winner_display' and current_status == 'winner_display':
                # Calculate remaining time properly
                winner_display_end = game.get('winner_display_end')
                if not winner_display_end:
                    # If no end time set, assume it should have ended
                    logger.warning(f"Game {game_id} in winner_display but no winner_display_end set. Marking as completed.")
                    await Database.update_game_status(game_id, 'completed')
                    await Database.update_game_phase(game_id, 'completed')
                    
                    # Clean up fake users
                    self.fake_user_manager.cleanup_game(game_id)
                    
                    # Clear winners for this game
                    await self.clear_winners(game_id)
                    
                    # Clean up caches
                    await self.cleanup_game_caches(game_id)
                    
                    # Clear fake finalized flag
                    if game_id in self._fake_players_finalized:
                        del self._fake_players_finalized[game_id]
                    
                    # ==================== NEW: Clear final winner broadcast flag ====================
                    if game_id in self._final_winner_broadcast_sent:
                        del self._final_winner_broadcast_sent[game_id]
                    
                    # Mark as completed in tracking set
                    self._completed_games.add(game_id)
                    
                    # Clear active game
                    async with self._lock:
                        if self.active_game and self.active_game.get('game_id') == game_id:
                            self.active_game = None
                    
                    # Start new round immediately
                    asyncio.create_task(self._schedule_next_round_after_winner_display(game_id))
                    return True
                
                # Parse winner_display_end
                if isinstance(winner_display_end, str):
                    try:
                        winner_display_end = datetime.fromisoformat(winner_display_end.replace('Z', '+00:00'))
                    except:
                        winner_display_end = datetime.fromisoformat(winner_display_end)
                
                current_time = datetime.now()
                
                # Calculate countdown with proper logic
                if winner_display_end > current_time:
                    countdown = (winner_display_end - current_time).total_seconds()
                    logger.info(f"📊 Winner display countdown for game {game_id}: {int(countdown)} seconds")
                    
                    # CRITICAL FIX: If countdown is exactly 5 seconds, ensure we're not stuck
                    if 4.5 <= countdown <= 5.5:
                        # Check if we've been at 5 seconds for too long (stuck detection)
                        last_log_time_key = f"last_5s_log_{game_id}"
                        
                        current_timestamp = time.time()
                        if last_log_time_key in self._last_5s_log_times:
                            time_since_last_log = current_timestamp - self._last_5s_log_times[last_log_time_key]
                            if time_since_last_log > 10:  # Been at 5 seconds for more than 10 seconds
                                logger.warning(f"Game {game_id} stuck at 5-second countdown for {time_since_last_log:.0f}s. Forcing completion.")
                                countdown = 0
                        else:
                            self._last_5s_log_times[last_log_time_key] = current_timestamp
                    
                    # Still in winner display, do nothing
                    return False
                else:
                    # Winner display has ended
                    countdown = 0
                
                logger.info(f"🏁 Winner display completed for game {game_id} (countdown: {countdown}), marking as completed and starting next round")
                
                # Mark game as completed
                await Database.update_game_status(game_id, 'completed')
                await Database.update_game_phase(game_id, 'completed')
                
                # Clean up fake users
                self.fake_user_manager.cleanup_game(game_id)
                
                # Clear winners for this game
                await self.clear_winners(game_id)
                
                # Clean up caches
                await self.cleanup_game_caches(game_id)
                
                # Clear fake finalized flag
                if game_id in self._fake_players_finalized:
                    del self._fake_players_finalized[game_id]
                
                # ==================== NEW: Clear final winner broadcast flag ====================
                if game_id in self._final_winner_broadcast_sent:
                    del self._final_winner_broadcast_sent[game_id]
                
                # Mark as completed in tracking set
                self._completed_games.add(game_id)
                
                # Clear the 5-second stuck detection for this game
                last_log_time_key = f"last_5s_log_{game_id}"
                if last_log_time_key in self._last_5s_log_times:
                    del self._last_5s_log_times[last_log_time_key]
                
                # Broadcast game completion with error handling
                await self._safe_broadcast({
                    'type': 'game_completed',
                    'game_id': game_id,
                    'message': 'Winner display completed, game finished',
                    'timestamp': datetime.now().isoformat()
                }, game_id)
                
                # Clear active game
                async with self._lock:
                    if self.active_game and self.active_game.get('game_id') == game_id:
                        self.active_game = None
                
                # Cancel any winner display task for this game
                if game_id in self._winner_display_tasks:
                    task = self._winner_display_tasks[game_id]
                    if task and not task.done():
                        task.cancel()
                    del self._winner_display_tasks[game_id]
                
                # Start new round immediately without delay
                await self._schedule_next_round_after_winner_display(game_id)
                return True
            
            # Don't transition if game is completed
            if current_status == 'completed':
                return False
            
            # ==================== CRITICAL FIX: Handle card_purchase phase with final counts ====================
            if current_phase == 'card_purchase' and current_status == 'card_purchase':
                countdown = await Database.calculate_purchase_countdown(game_id)
                
                # Log countdown more frequently when it's low
                if countdown <= 10:
                    logger.info(f"⏰ CRITICAL: Purchase countdown for game {game_id}: {countdown} seconds remaining")
                else:
                    logger.info(f"📊 Purchase countdown for game {game_id}: {countdown} seconds")
                
                if countdown <= 0:
                    # ========== CRITICAL FIX: FINALIZE ALL PLAYER DECISIONS BEFORE TRANSITION ==========
                    logger.info(f"⏰ Countdown expired for game {game_id}. Finalizing player counts...")
                    
                    # Step 1: Get fresh counts from database
                    with Database.get_cursor() as cursor:
                        # Get real players count
                        cursor.execute("""
                            SELECT COUNT(*) as count FROM player_cards 
                            WHERE game_id = ? AND is_fake = 0 AND is_active = 1
                        """, (game_id,))
                        real_result = cursor.fetchone()
                        real_players = real_result['count'] if real_result else 0
                        
                        # Get fake players count
                        cursor.execute("""
                            SELECT COUNT(*) as count FROM player_cards 
                            WHERE game_id = ? AND is_fake = 1 AND is_active = 1
                        """, (game_id,))
                        fake_result = cursor.fetchone()
                        fake_players = fake_result['count'] if fake_result else 0
                    
                    total_players = real_players + fake_players
                    
                    # Step 2: Calculate final prize pool based on final player count
                    final_prize_pool = total_players * 8.00
                    
                    # Step 3: Force update the prize pool in database to ensure consistency
                    with Database.get_cursor() as cursor:
                        cursor.execute("""
                            UPDATE games SET prize_pool = ? WHERE game_id = ?
                        """, (final_prize_pool, game_id))
                    
                    logger.info(f"⏰ FINAL counts for game {game_id}: Real={real_players}, Fake={fake_players}, Total={total_players}, Prize={final_prize_pool}")
                    
                    # Start game if we have at least 2 players
                    if total_players >= 2:
                        logger.info(f"Countdown completed for game {game_id} with {total_players} total active players, transitioning to active phase")
                        
                        # Update game to active phase
                        await Database.update_game_phase(game_id, 'active')
                        await Database.update_game_status(game_id, 'active')
                        await Database.update_game_start_time(game_id)
                        await Database.update_game_countdown(game_id, 0)
                        
                        # Update local cache
                        async with self._lock:
                            self.active_game = await Database.get_game(game_id)
                        
                        # Initialize winner tracking for this game
                        if game_id not in self.game_winners:
                            self.game_winners[game_id] = []
                        
                        # Increment state version
                        self._game_state_versions[game_id] = self._game_state_versions.get(game_id, 0) + 1
                        
                        # Start number calling for this game
                        from utils.number_caller import number_caller
                        await number_caller.start_number_calling_for_game(game_id)
                        
                        # ========== CRITICAL FIX: Broadcast FINAL state with correct numbers ==========
                        # Broadcast phase change with final data
                        await self._safe_broadcast({
                            'type': 'phase_change_confirmed',
                            'game_id': game_id,
                            'phase': 'active',
                            'real_players': real_players,
                            'fake_players': fake_players,
                            'total_players': total_players,
                            'prize_pool': final_prize_pool,
                            'timestamp': datetime.now().isoformat()
                        }, game_id)
                        
                        # Broadcast full state update immediately
                        await self._broadcast_full_game_state(game_id)
                        
                        logger.info(f"✅ Game {game_id} successfully transitioned to active phase with {total_players} active players, prize pool {final_prize_pool}")
                        return True
                    else:
                        # Not enough players - RESET COUNTDOWN
                        logger.info(f"Game {game_id} has only {total_players} active player(s). Need at least 2. Resetting countdown...")
                        
                        # Reset purchase end time
                        new_end_time = datetime.now() + timedelta(seconds=30)
                        await Database.set_purchase_end_time(game_id, new_end_time)
                        await Database.update_game_countdown(game_id, 30)
                        
                        # Broadcast countdown reset with error handling
                        await self._safe_broadcast({
                            'type': 'countdown_reset',
                            'game_id': game_id,
                            'message': f'Need at least 2 active players to start. Countdown reset to 30 seconds.',
                            'new_countdown': 30,
                            'total_players': total_players,
                            'required_players': 2,
                            'timestamp': datetime.now().isoformat()
                        }, game_id)
                        
                        return False
            
            # FIXED: Handle active phase - check if game needs recovery with error handling
            elif current_phase == 'active' and current_status == 'active':
                # Update last activity time
                self._last_activity_times[game_id] = datetime.now()
                
                # Check if number caller is running - FIXED: Handle AttributeError
                try:
                    from utils.number_caller import number_caller
                    # Use a safer approach - check if number caller has the method
                    if hasattr(number_caller, 'is_calling_numbers_for_game'):
                        if not number_caller.is_calling_numbers_for_game(game_id):
                            logger.warning(f"Game {game_id} is active but number caller not running. Starting it with 4-second interval...")
                            await number_caller.start_number_calling_for_game(game_id)
                    else:
                        # If method doesn't exist, just try to start it
                        logger.warning(f"NumberCaller missing method. Attempting to start number calling for game {game_id} with 4-second interval...")
                        await number_caller.start_number_calling_for_game(game_id)
                except AttributeError as e:
                    logger.warning(f"Error checking number caller: {e}. Attempting to start it with 4-second interval...")
                    try:
                        await number_caller.start_number_calling_for_game(game_id)
                    except Exception as start_error:
                        logger.error(f"Failed to start number caller: {start_error}")
                except Exception as e:
                    logger.error(f"Unexpected error with number caller: {e}")
            
            return False
            
        except Exception as e:
            logger.error(f"Error in check_and_handle_countdown_completion: {e}", exc_info=True)
            return False
    
    async def get_active_round_game(self):
        """Get active round game - FIXED: Uses system_state as source of truth"""
        async with self._lock:
            # If we already have it cached, return it
            if self.active_game:
                return self.active_game.copy()
            
            # Otherwise fetch from database
            return await self.get_current_game()
    
    # ==================== FIXED: Get game status with correct prize pool and commission calculation ====================
    async def get_game_status(self, game_id: str):
        """Get game status - FIXED: Prize pool based on ALL active players (real + fake), commission based on REAL active players only"""
        try:
            from database.db import Database

            # Get fresh game state
            game = await Database.get_game(game_id)
            if not game:
                return {
                    'success': False,
                    'message': 'Game not found'
                }

            # Get current phase and status
            current_phase = game.get('current_phase', 'card_purchase')
            current_status = game.get('status', 'card_purchase')
            
            # ========== Get player counts from database - ONLY ACTIVE CARDS ==========
            with Database.get_cursor() as cursor:
                cursor.execute("""
                    SELECT 
                        COUNT(CASE WHEN is_fake = 0 AND is_active = 1 THEN 1 END) as real_players,
                        COUNT(CASE WHEN is_fake = 1 AND is_active = 1 THEN 1 END) as fake_players,
                        COUNT(CASE WHEN is_active = 1 THEN 1 END) as total_players
                    FROM player_cards 
                    WHERE game_id = ?
                """, (game_id,))
                row = cursor.fetchone()
                real_players = row['real_players'] if row else 0
                fake_players = row['fake_players'] if row else 0
                total_players = row['total_players'] if row else 0
            
            # ========== Prize pool includes ALL active players (real + fake) ==========
            # Each active player contributes 8 birr to prize pool
            expected_prize_pool = total_players * 8.00
            current_prize_pool = float(game.get('prize_pool', 0))
            
            # If prize pool is incorrect, log warning and fix it
            if abs(current_prize_pool - expected_prize_pool) > 0.01:
                logger.warning(f"⚠️ Prize pool mismatch for game {game_id}: Expected {expected_prize_pool} from {total_players} total players, but DB has {current_prize_pool}")
                # Fix the prize pool in database
                with Database.get_cursor() as cursor:
                    cursor.execute("UPDATE games SET prize_pool = ? WHERE game_id = ?", (expected_prize_pool, game_id))
                current_prize_pool = expected_prize_pool
            
            # ========== Commission based on REAL active players only ==========
            # Each real player paid 10 birr, commission is 2 birr per real player
            commission_base = real_players * 2.00
            
            # Get winners count
            winners_count = await self.get_winners_count(game_id)
            winners = await self.get_winners(game_id)
            
            # Calculate payouts for winners to include in response
            payouts = []
            if winners_count > 0:
                payouts = await self.calculate_winner_payouts(game_id, current_prize_pool)
                
                # Attach payouts to winners for frontend
                for i, winner in enumerate(winners):
                    if i < len(payouts):
                        winner['prize_amount'] = payouts[i]
            
            # Calculate countdown based on phase
            countdown = 0
            if current_phase == 'card_purchase':
                countdown = await Database.calculate_purchase_countdown(game_id)
            elif current_phase == 'winner_display':
                winner_display_end = game.get('winner_display_end')
                if winner_display_end:
                    if isinstance(winner_display_end, str):
                        try:
                            winner_display_end = datetime.fromisoformat(winner_display_end.replace('Z', '+00:00'))
                        except:
                            winner_display_end = datetime.fromisoformat(winner_display_end)
                    
                    current_time = datetime.now()
                    if winner_display_end > current_time:
                        countdown = (winner_display_end - current_time).total_seconds()

            # Log for debugging
            logger.info(f"📊 Game Stats Update: prizePool={current_prize_pool}, expectedCards={total_players}, realPlayers={real_players}, fakePlayers={fake_players}, totalPlayers={total_players}")

            return {
                'success': True,
                'status': current_status,
                'phase': current_phase,
                'real_players': real_players,
                'fake_players': fake_players,
                'total_players': total_players,
                'max_players': 400,
                'prize_pool': current_prize_pool,  # Based on TOTAL active players × 8
                'expected_cards': total_players,   # Should match total_players (active cards only)
                'commission_base': commission_base,  # For UI display (real_players × 2)
                'expected_prize_pool': expected_prize_pool,
                'countdown_remaining': max(0, int(countdown)),
                'round_number': game.get('round_number', 1),
                'minimum_players': self.min_players_to_start,
                'has_enough_players': total_players >= self.min_players_to_start,
                'fake_users_enabled': self.fake_users_enabled,
                'fake_players_remaining': fake_players,
                'min_fake_players': self.min_fake_players,
                'max_fake_players': self.max_fake_players,
                'fake_players_finalized': self._fake_players_finalized.get(game_id, False),
                'fake_players_percentage': (fake_players / max(1, total_players)) * 100 if total_players > 0 else 0,
                'max_winners': self.max_winners,
                'winners_count': winners_count,
                'winners': winners,  # Now includes prize_amount for each winner
                'can_add_more_winners': winners_count < self.max_winners,
                'game_completed': game_id in self._completed_games,
                'state_version': self._game_state_versions.get(game_id, 1)
            }

        except Exception as e:
            logger.error(f"Error getting game status: {e}", exc_info=True)
            return {
                'success': False,
                'message': str(e)
            }
    
    # ==================== FIXED: Toggle card purchase with correct prize pool handling ====================
    # CRITICAL FIX: Commission is ONLY added at game completion, NOT at purchase time
    async def toggle_card_purchase(self, game_id: str, user_id: int, card_index: int, action: str = 'buy'):
        """Toggle card purchase/refund - FIXED: Commission only added at game completion"""
        try:
            from database.db import Database
            
            # Validate game exists
            game = await Database.get_game(game_id)
            if not game:
                return {
                    'success': False,
                    'message': 'Game not found'
                }

            # Get current phase
            current_phase = game.get('current_phase', 'card_purchase')
            current_status = game.get('status', 'card_purchase')

            # Check if game is in card purchase phase
            if current_phase != 'card_purchase' or current_status != 'card_purchase':
                return {
                    'success': False,
                    'message': 'Card purchase is only available during purchase phase'
                }

            # CRITICAL: Check if this is the current active game
            current_game = await self.get_current_game()
            if not current_game or current_game.get('game_id') != game_id:
                return {
                    'success': False,
                    'message': 'This game is no longer active. Please purchase cards in the latest game.'
                }

            # Check countdown
            countdown = await Database.calculate_purchase_countdown(game_id)
            if countdown <= 0:
                return {
                    'success': False,
                    'message': 'Card purchase time has expired'
                }

            if action == 'buy':
                # Check total players doesn't exceed 400
                with Database.get_cursor() as cursor:
                    cursor.execute("""
                        SELECT COUNT(*) as count FROM player_cards 
                        WHERE game_id = ? AND is_active = 1
                    """, (game_id,))
                    total_players_before = cursor.fetchone()['count'] or 0
                    
                    if total_players_before >= 400:
                        return {
                            'success': False,
                            'message': 'Game has reached maximum capacity (400 players)'
                        }
                
                # Check if user already has an active card
                existing_card = await Database.get_user_card_in_game(user_id, game_id)
                if existing_card and existing_card.get('is_active') == 1:
                    return {
                        'success': False,
                        'message': 'You can only buy 1 card per game'
                    }

                # Check if card is already sold to someone else
                with Database.get_cursor() as cursor:
                    cursor.execute("""
                        SELECT id FROM player_cards 
                        WHERE game_id = ? AND card_index = ? AND is_active = 1
                    """, (game_id, card_index))
                    if cursor.fetchone():
                        return {
                            'success': False,
                            'message': 'This card is already sold'
                        }

                # Check user balance
                user = await Database.get_user(user_id)
                if not user:
                    await Database.create_user(
                        user_id=user_id,
                        username=f"User_{user_id}",
                        full_name=f"User {user_id}"
                    )
                    user = await Database.get_user(user_id)

                if float(user.get('balance', 0)) < 10.00:
                    return {
                        'success': False,
                        'message': 'Insufficient balance'
                    }

                # Generate card numbers
                card_numbers = self._generate_bingo_card_numbers()

                # Create player card (is_active = 1 by default)
                card_id = await Database.create_player_card(
                    user_id=user_id,
                    game_id=game_id,
                    card_numbers=card_numbers,
                    price=10.00,
                    card_index=card_index,
                    is_active=1
                )

                if card_id == 0:
                    return {
                        'success': False,
                        'message': 'Failed to create card'
                    }

                # Deduct balance (full 10 birr)
                success = await Database.update_balance_with_transaction(
                    user_id=user_id,
                    amount=-10.00,
                    transaction_type='card_purchase',
                    description=f'Purchased card #{card_index} for 10 birr',
                    game_id=game_id
                )

                if not success:
                    await Database.delete_player_card(card_id)
                    return {
                        'success': False,
                        'message': 'Failed to deduct balance'
                    }

                # ========== Add ONLY 8 birr to prize pool ==========
                # Commission (2 birr) is NOT added here - it will be added at game completion
                await Database.add_to_prize_pool(game_id, 8.00)
                
                # ========== CRITICAL FIX: DO NOT add commission at purchase time ==========
                # The following line is REMOVED:
                # await Database.add_to_house_balance(amount=2.00, ...)

                # Get updated prize pool
                updated_game = await Database.get_game(game_id)
                prize_pool = float(updated_game.get('prize_pool', 0)) if updated_game else 0

                # Get updated user balance
                updated_user = await Database.get_user(user_id)
                new_balance = float(updated_user.get('balance', 0)) if updated_user else 0

                # ========== Handle real user join (NO fake player removal) ==========
                if self.fake_users_enabled:
                    await self.handle_real_user_join(game_id)

                # Get updated player counts
                with Database.get_cursor() as cursor:
                    cursor.execute("""
                        SELECT 
                            COUNT(CASE WHEN is_fake = 0 AND is_active = 1 THEN 1 END) as real_players,
                            COUNT(CASE WHEN is_fake = 1 AND is_active = 1 THEN 1 END) as fake_players
                        FROM player_cards 
                        WHERE game_id = ?
                    """, (game_id,))
                    row = cursor.fetchone()
                    real_players = row['real_players'] if row else 0
                    fake_players = row['fake_players'] if row else 0
                    total_players = real_players + fake_players
                    
                    # Calculate correct prize pool based on total players
                    correct_prize_pool = total_players * 8.00
                    await Database.update_prize_pool(game_id, correct_prize_pool)

                # Broadcast purchase with full state
                await self._safe_broadcast({
                    'type': 'card_purchased',
                    'game_id': game_id,
                    'user_id': user_id,
                    'card_index': card_index,
                    'prize_pool': correct_prize_pool,
                    'real_players': real_players,
                    'fake_players': fake_players,
                    'total_players': total_players,
                    'max_players': 400,
                    'timestamp': datetime.now().isoformat()
                }, game_id)
                
                # Broadcast full state update
                await self._broadcast_full_game_state(game_id)

                return {
                    'success': True,
                    'message': f'Card #{card_index} purchased successfully!',
                    'card_id': card_id,
                    'card_index': card_index,
                    'card_numbers': card_numbers,
                    'prize_pool': correct_prize_pool,
                    'new_balance': new_balance,
                    'real_players': real_players,
                    'fake_players': fake_players,
                    'total_players': total_players,
                    'max_players': 400
                }

            else:  # action == 'refund'
                # Get user's card
                user_card = await Database.get_user_card_in_game(user_id, game_id)
                if not user_card or user_card.get('card_index') != card_index:
                    return {
                        'success': False,
                        'message': 'You do not own this card'
                    }

                # Check if card is already inactive (already refunded)
                if user_card.get('is_active') == 0:
                    return {
                        'success': False,
                        'message': 'This card has already been refunded'
                    }

                # Check countdown
                countdown = await Database.calculate_purchase_countdown(game_id)
                if countdown <= 0:
                    return {
                        'success': False,
                        'message': 'Cannot refund card after game has started'
                    }

                # Refund 100% of price (10 birr)
                refund_amount = 10.00

                # Add refund to user balance
                success = await Database.update_balance_with_transaction(
                    user_id=user_id,
                    amount=refund_amount,
                    transaction_type='card_refund',
                    description=f'Refund for card #{card_index} (100% of 10 birr)',
                    game_id=game_id
                )

                if not success:
                    return {
                        'success': False,
                        'message': 'Failed to process refund'
                    }

                # ========== Remove ONLY 8 birr from prize pool ==========
                await Database.remove_from_prize_pool(game_id, 8.00)

                # ========== CRITICAL FIX: DO NOT deduct commission at refund time ==========
                # The following line is REMOVED:
                # await Database.add_to_house_balance(amount=-2.00, ...)

                # ========== Mark card as inactive ==========
                await Database.deactivate_player_card(user_card['id'])

                # Get updated prize pool
                updated_game = await Database.get_game(game_id)
                prize_pool = float(updated_game.get('prize_pool', 0)) if updated_game else 0

                # Get updated user balance
                updated_user = await Database.get_user(user_id)
                new_balance = float(updated_user.get('balance', 0)) if updated_user else 0

                # ========== Handle real user refund (NO fake player addition) ==========
                if self.fake_users_enabled:
                    await self.handle_real_user_refund(game_id)

                # Get updated player counts
                with Database.get_cursor() as cursor:
                    cursor.execute("""
                        SELECT 
                            COUNT(CASE WHEN is_fake = 0 AND is_active = 1 THEN 1 END) as real_players,
                            COUNT(CASE WHEN is_fake = 1 AND is_active = 1 THEN 1 END) as fake_players
                        FROM player_cards 
                        WHERE game_id = ?
                    """, (game_id,))
                    row = cursor.fetchone()
                    real_players = row['real_players'] if row else 0
                    fake_players = row['fake_players'] if row else 0
                    total_players = real_players + fake_players
                    
                    # Calculate correct prize pool based on total players
                    correct_prize_pool = total_players * 8.00
                    await Database.update_prize_pool(game_id, correct_prize_pool)

                # Broadcast refund with full state
                await self._safe_broadcast({
                    'type': 'card_refunded',
                    'game_id': game_id,
                    'user_id': user_id,
                    'card_index': card_index,
                    'prize_pool': correct_prize_pool,
                    'real_players': real_players,
                    'fake_players': fake_players,
                    'total_players': total_players,
                    'max_players': 400,
                    'timestamp': datetime.now().isoformat()
                }, game_id)
                
                # Broadcast full state update
                await self._broadcast_full_game_state(game_id)

                logger.info(f"REFUND DETAILS - Card #{card_index}: User refunded {refund_amount} birr, Prize pool: {correct_prize_pool}")

                return {
                    'success': True,
                    'message': f'Card #{card_index} refunded successfully!',
                    'refund_amount': refund_amount,
                    'prize_pool': correct_prize_pool,
                    'new_balance': new_balance,
                    'real_players': real_players,
                    'fake_players': fake_players,
                    'total_players': total_players
                }

        except Exception as e:
            logger.error(f"Error in toggle_card_purchase: {e}", exc_info=True)
            return {
                'success': False,
                'message': f'Server error: {str(e)}'
            }
    
    # ==================== FIXED: process_winner with proper winner data for ALL winners ====================
    async def process_winner(self, game_id: str, user_id: int):
        """Process bingo winner - UPDATED: Two winner support with 50-50 split and TRUE claims"""
        # Note: This method already acquires _verification_lock, so we don't need to worry about recursive locks
        # as it's not called from within another _verification_lock context
        async with self._verification_lock:
            try:
                from database.db import Database
                from web_server import websocket_server
                from utils.number_caller import number_caller
                
                logger.info(f"🚀 BINGO VERIFICATION STARTING for user {user_id} in game {game_id}")
                start_time = time.time()
                
                # Get game details
                game = await Database.get_game(game_id)
                if not game:
                    logger.error(f"Game {game_id} not found")
                    return None
                
                # Check if we can add another winner
                if not await self.can_add_winner(game_id):
                    logger.warning(f"Game {game_id} already has maximum winners ({self.max_winners})")
                    return None
                
                # Check if game already has winner and number calling should be stopped
                game_status = game.get('status', 'card_purchase')
                winners_count_before = await self.get_winners_count(game_id)
                
                # Stop number calling on first winner only
                if winners_count_before == 0 and game_status != 'winner_display':
                    await number_caller.stop_number_calling_for_game(game_id)
                
                # Get user card
                user_card = await Database.get_user_card_in_game(user_id, game_id)
                if not user_card:
                    logger.error(f"User {user_id} has no card in game {game_id}")
                    return None
                
                # Fast bingo verification
                called_numbers = await Database.get_drawn_numbers(game_id)
                has_bingo, winning_pattern, pattern_type = await self._fast_verify_bingo_with_pattern(user_card, called_numbers)
                
                verification_time = (time.time() - start_time) * 1000
                logger.info(f"⚡ Bingo verified in {verification_time:.1f}ms - Result: {has_bingo}, Pattern: {pattern_type}")
                
                if not has_bingo:
                    logger.error(f"Invalid bingo claim by user {user_id}")
                    return None
                
                # Get prize pool
                prize_pool = float(game.get('prize_pool', 0.00))
                if prize_pool <= 0:
                    logger.error(f"No prize pool in game {game_id}")
                    return None
                
                # Count players (real only for payout calculations)
                real_players = await Database.count_game_players(game_id)
                fake_count = len(self.fake_user_manager.game_fake_cards.get(game_id, {}))
                total_players = real_players + fake_count
                
                # Get user details for announcement
                user = await Database.get_user(user_id)
                username = user.get('username', f'User_{user_id}') if user else f'User_{user_id}'
                full_name = user.get('full_name', '') if user else ''
                
                # Extract card numbers for display
                card_numbers = self._extract_card_numbers(user_card)
                
                # FIXED: Ensure winning_pattern contains actual corner numbers for 4 corners
                if pattern_type == "four_corners":
                    # Use actual corner numbers from card
                    if len(card_numbers) == 25:
                        actual_corners = [card_numbers[0], card_numbers[4], card_numbers[20], card_numbers[24]]
                        logger.info(f"🎯 Using actual 4 Corners numbers: {actual_corners}")
                        winning_pattern = actual_corners
                
                # Create winner data with TRUE claim information
                winner_data = {
                    'user_id': user_id,
                    'username': username,
                    'full_name': full_name,
                    'card_index': user_card.get('card_index'),
                    'card_numbers': card_numbers,  # Full 25 numbers for grid
                    'winning_pattern': winning_pattern if winning_pattern else [],  # Pattern numbers
                    'pattern_type': pattern_type,
                    'is_fake': False,
                    'timestamp': datetime.now().isoformat()
                }
                
                # Add to winners list
                added = await self.add_winner(game_id, winner_data)
                if not added:
                    logger.warning(f"Could not add winner to game {game_id}")
                    return None
                
                winners_count = await self.get_winners_count(game_id)
                logger.info(f"✅ Winner added. Game {game_id} now has {winners_count} winner(s)")
                
                # Increment state version
                self._game_state_versions[game_id] = self._game_state_versions.get(game_id, 0) + 1
                
                # Calculate payouts based on number of winners
                all_winners = await self.get_winners(game_id)
                payouts = await self.calculate_winner_payouts(game_id, prize_pool)
                
                # Get this winner's payout
                winner_index = next((i for i, w in enumerate(all_winners) if w.get('user_id') == user_id), 0)
                winner_payout = payouts[winner_index] if winner_index < len(payouts) else prize_pool
                
                # ========== SET WINNER DISPLAY STATE ON FIRST WINNER ONLY ==========
                if winners_count == 1:
                    winner_display_duration = 10  # 10 seconds for winner display
                    winner_display_end = datetime.now() + timedelta(seconds=winner_display_duration)
                    
                    # IMPORTANT: Update game status and phase BEFORE processing payment
                    await Database.update_game_status(game_id, 'winner_display')
                    await Database.update_game_phase(game_id, 'winner_display')
                    await Database.set_winner_display_end(game_id, winner_display_end)
                    
                    # Update local cache
                    async with self._lock:
                        self.active_game = await Database.get_game(game_id)
                    
                    # Start winner display monitor
                    if game_id not in self._winner_display_tasks:
                        self._winner_display_tasks[game_id] = asyncio.create_task(
                            self._monitor_winner_display_countdown(game_id, winner_display_end)
                        )
                
                # ========== FIXED: ALWAYS SEND COMPLETE WINNER DATA FOR ALL WINNERS ==========
                # This sends complete data for EVERY winner, regardless of whether it's first or final
                
                # Get all winners with their complete data
                final_all_winners = await self.get_winners(game_id)
                final_payouts = await self.calculate_winner_payouts(game_id, prize_pool)
                
                # Prepare complete winners data with all details
                complete_winners_data = []
                for i, w in enumerate(final_all_winners):
                    # ========== CRITICAL FIX: Properly extract card numbers for each winner ==========
                    # Ensure each winner has valid card numbers
                    w = await self._ensure_winner_card_numbers(game_id, w)
                    
                    winner_card_numbers = w.get('card_numbers', [])
                    winner_winning_pattern = w.get('winning_pattern', [])
                    
                    # Ensure winning pattern is valid
                    if not winner_winning_pattern or len(winner_winning_pattern) == 0:
                        # Try to generate from pattern type
                        pattern_type = w.get('pattern_type', '')
                        if pattern_type == "four_corners" and len(winner_card_numbers) >= 25:
                            winner_winning_pattern = [
                                winner_card_numbers[0], 
                                winner_card_numbers[4], 
                                winner_card_numbers[20], 
                                winner_card_numbers[24]
                            ]
                            winner_winning_pattern = [num for num in winner_winning_pattern if num != 0]
                        elif pattern_type.startswith("row_") and len(winner_card_numbers) >= 25:
                            try:
                                row_num = int(pattern_type.split("_")[1])
                                start_idx = row_num * 5
                                winner_winning_pattern = winner_card_numbers[start_idx:start_idx+5]
                                winner_winning_pattern = [num for num in winner_winning_pattern if num != 0]
                            except:
                                pass
                        elif pattern_type.startswith("column_") and len(winner_card_numbers) >= 25:
                            try:
                                col_num = int(pattern_type.split("_")[1])
                                indices = [col_num + (i*5) for i in range(5)]
                                winner_winning_pattern = [winner_card_numbers[i] for i in indices]
                                winner_winning_pattern = [num for num in winner_winning_pattern if num != 0]
                            except:
                                pass
                    
                    winner_complete = {
                        'user_id': w.get('user_id'),
                        'username': w.get('username'),
                        'full_name': w.get('full_name'),
                        'card_index': w.get('card_index'),
                        'card_numbers': winner_card_numbers,  # Full 25 numbers - now properly populated
                        'winning_pattern': winner_winning_pattern,  # Pattern numbers
                        'pattern_type': w.get('pattern_type', 'BINGO'),
                        'prize_amount': final_payouts[i] if i < len(final_payouts) else 0,
                        'is_fake': w.get('is_fake', False),
                        'winner_number': i + 1
                    }
                    complete_winners_data.append(winner_complete)
                
                # Create comprehensive winner announcement with ALL winners
                final_winner_data = {
                    'type': 'winner_confirmed',
                    'game_id': game_id,
                    'prize_pool': prize_pool,
                    'max_winners': self.max_winners,
                    'total_winners': len(final_all_winners),
                    'is_final_winner': len(final_all_winners) >= self.max_winners,
                    'winners': complete_winners_data,
                    'timestamp': datetime.now().isoformat(),
                    'state_version': self._game_state_versions.get(game_id, 1),
                    'fake_player_stats': {
                        'min_fake_players': self.min_fake_players,
                        'max_fake_players': self.max_fake_players,
                        'current_fake_players': fake_count
                    }
                }
                
                # Add corner details for 4 corners pattern if applicable
                for winner in final_all_winners:
                    if winner.get('pattern_type') == "four_corners" and len(winner.get('card_numbers', [])) >= 25:
                        card_nums = winner.get('card_numbers', [])
                        if 'corner_details' not in final_winner_data:
                            final_winner_data['corner_details'] = {}
                        final_winner_data['corner_details'][winner.get('user_id')] = {
                            'top_left': card_nums[0],
                            'top_right': card_nums[4],
                            'bottom_left': card_nums[20],
                            'bottom_right': card_nums[24],
                            'corner_indices': [0, 4, 20, 24]
                        }
                
                # Broadcast the complete winner announcement
                try:
                    await websocket_server.broadcast_with_retry(final_winner_data)
                    logger.info(f"📢 Broadcast COMPLETE winner announcement with data for all {len(final_all_winners)} winners")
                    
                    # Mark that we've sent the broadcast (only after successful send)
                    if len(final_all_winners) >= self.max_winners:
                        self._final_winner_broadcast_sent[game_id] = True
                        
                except Exception as e:
                    logger.error(f"Failed to broadcast complete winner data: {e}")
                
                # ========== PROCESS PAYMENT FOR THIS WINNER ==========
                success = await Database.update_balance_with_transaction(
                    user_id=user_id,
                    amount=winner_payout,
                    transaction_type='winning',
                    description=f'BINGO win #{winners_count} in game {game_id} (Pattern: {pattern_type}, Prize: {winner_payout:.2f} birr)',
                    game_id=game_id
                )
                
                if not success:
                    logger.error(f"Failed to record transaction for winner {user_id}")
                
                # Update game with winner info
                await Database.update_game_winner(game_id, user_id, prize_pool)
                await Database.mark_bingo(user_card['id'], winner_payout)
                
                # ========== PROCESS GAME COMPLETION (record commission and finalize) ==========
                # Commission should be recorded whenever game ends, regardless of winner count
                logger.info(f"🏆 Game {game_id} ending with {winners_count} winner(s). Finalizing...")
                
                # Validate prize pool before finalizing - use updated player counts
                # Get fresh player counts after winner processing
                fresh_real_players = await Database.count_game_players(game_id)
                fresh_fake_count = len(self.fake_user_manager.game_fake_cards.get(game_id, {}))
                fresh_total_players = fresh_real_players + fresh_fake_count
                
                await self._validate_prize_pool(game_id, fresh_total_players, prize_pool)
                
                # Record game details with all winners
                game_recorded = await self._record_complete_game_details(
                    game_id=game_id,
                    winners=all_winners,
                    prize_pool=prize_pool,
                    winner_payouts=payouts,
                    called_numbers=called_numbers,
                    total_players=fresh_total_players
                )
                
                if not game_recorded:
                    logger.error(f"Failed to record game details for {game_id}")
                    # Continue anyway - commission might still work
                
                # CRITICAL FIX: Record commission with the dedicated method (no games table interference)
                # THIS WILL ALWAYS RUN WHEN THE GAME ENDS, REGARDLESS OF WINNER COUNT
                commission_recorded = False
                max_retries = 5
                retry_delay = 1

                for attempt in range(max_retries):
                    try:
                        logger.info(f"Commission recording attempt {attempt + 1}/{max_retries} for game {game_id}")
                        
                        # Get fresh real player count for commission
                        with Database.get_cursor() as cursor:
                            cursor.execute("""
                                SELECT COUNT(*) as real_players
                                FROM player_cards 
                                WHERE game_id = ? AND is_fake = 0 AND is_active = 1
                            """, (game_id,))
                            result = cursor.fetchone()
                            current_real_players = result['real_players'] if result else 0
                            
                            logger.info(f"Current real players for commission: {current_real_players}")
                        
                        commission_recorded = await self.record_game_commission(game_id)
                        
                        if commission_recorded:
                            logger.info(f"✅ Commission successfully recorded for game {game_id} (attempt {attempt + 1})")
                            break
                        else:
                            logger.warning(f"⚠️ Commission recording attempt {attempt + 1} failed for game {game_id}")
                            
                            # Check if commission already recorded in commission_records table
                            with Database.get_cursor() as cursor:
                                cursor.execute("""
                                    SELECT COUNT(*) as count FROM commission_records WHERE game_id = ?
                                """, (game_id,))
                                result = cursor.fetchone()
                                if result and result['count'] > 0:
                                    logger.info(f"Commission already exists in commission_records for game {game_id}")
                                    commission_recorded = True
                                    break
                            
                            await asyncio.sleep(retry_delay)
                            
                    except Exception as comm_error:
                        logger.error(f"❌ Error recording commission (attempt {attempt + 1}): {comm_error}")
                        if attempt < max_retries - 1:
                            await asyncio.sleep(retry_delay)

                if not commission_recorded:
                    logger.critical(f"🚨 CRITICAL: Failed to record commission for game {game_id} after {max_retries} attempts")
                    
                    # Force commission recording as a last resort - insert directly into commission_records
                    try:
                        with Database.get_cursor() as cursor:
                            # Get fresh real player count
                            cursor.execute("""
                                SELECT COUNT(*) as real_players
                                FROM player_cards 
                                WHERE game_id = ? AND is_fake = 0 AND is_active = 1
                            """, (game_id,))
                            result = cursor.fetchone()
                            forced_real_players = result['real_players'] if result else 0
                            forced_commission = forced_real_players * 2.00
                            
                            logger.warning(f"⚠️ Forcing commission recording into commission_records: {forced_real_players} real players × 2 = {forced_commission}")
                            
                            # Insert directly into commission_records
                            cursor.execute("""
                                INSERT OR IGNORE INTO commission_records 
                                (game_id, round_number, real_players_count, commission_amount, recorded_at, status)
                                VALUES (?, ?, ?, ?, ?, ?)
                            """, (
                                game_id,
                                game.get('round_number', 1),
                                forced_real_players,
                                forced_commission,
                                datetime.now(),
                                'recorded'
                            ))
                            
                            # Add to house_balance if not exists
                            cursor.execute("""
                                SELECT COUNT(*) as count FROM house_balance 
                                WHERE game_id = ? AND transaction_type = 'game_commission'
                            """, (game_id,))
                            exists = cursor.fetchone()['count'] > 0
                            
                            if not exists and forced_commission > 0:
                                cursor.execute("""
                                    INSERT INTO house_balance (amount, transaction_type, description, game_id, created_at)
                                    VALUES (?, 'game_commission', ?, ?, ?)
                                """, (
                                    forced_commission,
                                    f'FORCED commission from game {game_id} ({forced_real_players} real players)',
                                    game_id,
                                    datetime.now()
                                ))
                            
                            logger.info(f"✅ Force-recorded commission for game {game_id}: {forced_commission}")
                            commission_recorded = True
                    except Exception as force_error:
                        logger.error(f"Failed to force-record commission: {force_error}")
                
                # Mark game as completed in tracking set
                self._completed_games.add(game_id)
                
                # Clean up caches
                await self.cleanup_game_caches(game_id)
                
                total_time = (time.time() - start_time) * 1000
                logger.info(f"✅ BINGO #{winners_count} PROCESSED in {total_time:.1f}ms: {username} won {winner_payout:.2f} birr")
                
                return {
                    'user_id': user_id,
                    'username': username,
                    'full_name': full_name,
                    'prize_amount': winner_payout,
                    'pattern_type': pattern_type,
                    'winning_pattern': winning_pattern,
                    'verification_time_ms': verification_time,
                    'status': 'winner_display' if winners_count == 1 else 'additional_winner',
                    'winner_number': winners_count,
                    'total_winners': winners_count,
                    'is_final': len(all_winners) >= self.max_winners,
                    'real_players': real_players,
                    'fake_players': fake_count,
                    'total_players': total_players
                }
                
            except Exception as e:
                logger.error(f"Error processing winner: {e}", exc_info=True)
                return None
    
    async def _validate_prize_pool(self, game_id: str, total_players: int, current_prize_pool: float):
        """Validate that prize pool matches total active players × 8"""
        try:
            from database.db import Database
            expected_prize_pool = total_players * 8.00
            
            if abs(current_prize_pool - expected_prize_pool) > 0.01:
                logger.warning(f"⚠️ Prize pool mismatch at game end for {game_id}: Expected {expected_prize_pool}, Actual {current_prize_pool}")
                # Fix the prize pool
                await Database.update_prize_pool(game_id, expected_prize_pool)
                logger.info(f"✅ Fixed prize pool for game {game_id} to {expected_prize_pool}")
                return expected_prize_pool
            
            return current_prize_pool
        except Exception as e:
            logger.error(f"Error validating prize pool: {e}")
            return current_prize_pool
    
    async def _monitor_winner_display_countdown(self, game_id: str, winner_display_end: datetime):
        """Monitor winner display countdown and ensure completion after exactly 10 seconds"""
        try:
            logger.info(f"⏱️ Starting winner display monitor for game {game_id} until {winner_display_end}")
            
            from database.db import Database
            from web_server import websocket_server
            
            # Calculate initial wait time
            current_time = datetime.now()
            if winner_display_end > current_time:
                initial_wait = (winner_display_end - current_time).total_seconds()
                logger.info(f"⏱️ Winner display for game {game_id} will last {initial_wait:.1f} seconds")
                
                # Wait for the full duration (10 seconds)
                await asyncio.sleep(initial_wait)
            
            # After waiting the full duration, force completion
            logger.info(f"🏁 Winner display duration completed for game {game_id}. Forcing completion...")
            
            # CRITICAL: Force the game to complete immediately
            await Database.update_game_status(game_id, 'completed')
            await Database.update_game_phase(game_id, 'completed')
            
            # Clean up fake users
            self.fake_user_manager.cleanup_game(game_id)
            
            # Clear winners for this game
            await self.clear_winners(game_id)
            
            # Clean up caches
            await self.cleanup_game_caches(game_id)
            
            # Clear fake finalized flag
            if game_id in self._fake_players_finalized:
                del self._fake_players_finalized[game_id]
            
            # ==================== NEW: Clear final winner broadcast flag ====================
            if game_id in self._final_winner_broadcast_sent:
                del self._final_winner_broadcast_sent[game_id]
            
            # Mark as completed in tracking set
            self._completed_games.add(game_id)
            
            # Broadcast completion to ALL clients immediately
            await self._safe_broadcast({
                'type': 'game_completed',
                'game_id': game_id,
                'message': 'Winner display completed, game finished',
                'timestamp': datetime.now().isoformat(),
                'force_refresh': True  # Add flag to force client refresh
            }, game_id)
            
            # Clear active game
            async with self._lock:
                if self.active_game and self.active_game.get('game_id') == game_id:
                    self.active_game = None
            
            # Start new round immediately WITHOUT ANY DELAY
            logger.info(f"🎮 Starting next round immediately after winner display for game {game_id}")
            await self._schedule_next_round_after_winner_display(game_id)
            
            logger.info(f"✅ Winner display monitor completed for game {game_id}")
            
        except asyncio.CancelledError:
            logger.info(f"Winner display monitor cancelled for game {game_id}")
        except Exception as e:
            logger.error(f"Error in winner display monitor for game {game_id}: {e}")
        finally:
            # Clean up task reference
            if game_id in self._winner_display_tasks:
                del self._winner_display_tasks[game_id]
    
    # ==================== FIXED: Record complete game details with correct commission ====================
    async def _record_complete_game_details(self, game_id: str, winners: List[Dict], prize_pool: float, 
                                           winner_payouts: List[float], called_numbers: list, 
                                           total_players: int, is_fake: bool = False):
        """
        Record complete game details for history and reporting - FIXED: Now only records game history,
        commission is handled separately in record_game_commission()
        """
        try:
            from database.db import Database
            
            # Get the game details
            game = await Database.get_game(game_id)
            if not game:
                return False
            
            # Get real players count (for reference only, not for commission)
            real_players = await Database.count_game_players(game_id)
            
            # Get all cards sold in this game - ONLY ACTIVE CARDS
            with Database.get_cursor() as cursor:
                # Count ACTIVE real cards
                cursor.execute("""
                    SELECT COUNT(*) as real_cards_sold, COALESCE(SUM(price), 0) as total_sales
                    FROM player_cards 
                    WHERE game_id = ? AND is_fake = 0 AND is_active = 1
                """, (game_id,))
                cards_sold_result = cursor.fetchone()
                real_cards_sold = cards_sold_result['real_cards_sold'] if cards_sold_result else 0
                total_sales = cards_sold_result['total_sales'] if cards_sold_result else 0.0
                
                # Get fake card count
                fake_cards_sold = await Database.count_active_fake_cards(game_id)
                total_cards_sold = real_cards_sold + fake_cards_sold
                
                # ========== FIXED: Commission is NOT recorded here anymore ==========
                # Commission is now handled exclusively by record_game_commission()
                # This method only records game history, no commission data
                
                logger.info(f"📊 Game history preparation: {real_players} real players, {real_cards_sold} real cards")
                
                # Prepare winners data for storage
                winners_data = []
                for i, winner in enumerate(winners):
                    # Ensure winner has card numbers
                    winner = await self._ensure_winner_card_numbers(game_id, winner)
                    
                    winner_data = {
                        'user_id': winner.get('user_id'),
                        'username': winner.get('username'),
                        'full_name': winner.get('full_name'),
                        'pattern_type': winner.get('pattern_type'),
                        'winning_pattern': winner.get('winning_pattern', []),
                        'card_index': winner.get('card_index'),
                        'prize_amount': winner_payouts[i] if i < len(winner_payouts) else 0,
                        'is_fake': winner.get('is_fake', False),
                        'timestamp': winner.get('timestamp', datetime.now().isoformat())
                    }
                    winners_data.append(winner_data)
                
                # Record in game_history table - NO commission fields
                cursor.execute("""
                    INSERT INTO game_history (
                        game_id, round_number, prize_pool,
                        pattern_type, called_numbers, total_players,
                        real_cards_sold, fake_cards_sold, total_cards_sold, total_sales,
                        winners_count, winners_data, winner_payouts, is_fake_winner,
                        min_fake_players, max_fake_players,
                        game_date, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    game_id,
                    game.get('round_number', 1),
                    prize_pool,
                    'multiple_winners' if len(winners) > 1 else winners[0].get('pattern_type', 'unknown'),
                    json.dumps(called_numbers),
                    total_players,
                    real_cards_sold,
                    fake_cards_sold,
                    total_cards_sold,
                    total_sales,
                    len(winners),
                    json.dumps(winners_data),
                    json.dumps(winner_payouts),
                    is_fake,
                    self.min_fake_players,
                    self.max_fake_players,
                    datetime.now().date(),
                    datetime.now()
                ))
                
                # Update the games table with minimal completion info (NO commission fields)
                try:
                    cursor.execute("""
                        UPDATE games 
                        SET completed_at = ?,
                            real_cards_sold = ?,
                            total_sales = ?,
                            winners_count = ?
                        WHERE game_id = ?
                    """, (
                        datetime.now(),
                        real_cards_sold,
                        total_sales,
                        len(winners),
                        game_id
                    ))
                except:
                    # Fallback if columns don't exist
                    cursor.execute("""
                        UPDATE games 
                        SET completed_at = ?,
                            winners_count = ?
                        WHERE game_id = ?
                    """, (
                        datetime.now(),
                        len(winners),
                        game_id
                    ))
                
                logger.info(f"📊 Game {game_id} recorded in history: {real_players} real players, {real_cards_sold} real cards, "
                           f"{fake_cards_sold} fake cards, {len(winners)} winners, {total_sales:.2f} sales")
                return True
                
        except Exception as e:
            logger.error(f"Error recording complete game details: {e}")
            return False
    
    # ==================== FIXED: Record game commission in dedicated commission_records table ====================
    async def record_game_commission(self, game_id: str):
        """
        Record commission in dedicated commission_records table.
        This method does NOT interfere with the games table at all.
        """
        try:
            from database.db import Database
        
            # Get game details (read-only from games table)
            game = await Database.get_game(game_id)
            if not game:
                logger.error(f"Game {game_id} not found for commission recording")
                return False
            
            # Check if commission already recorded for this game
            with Database.get_cursor() as cursor:
                cursor.execute("""
                    SELECT COUNT(*) as count FROM commission_records 
                    WHERE game_id = ?
                """, (game_id,))
                result = cursor.fetchone()
                if result and result['count'] > 0:
                    logger.info(f"Commission already recorded for game {game_id} in commission_records, skipping")
                    return True
                
                # ========== Count ONLY REAL active player cards (exclude refunded/inactive) ==========
                cursor.execute("""
                    SELECT COUNT(*) as real_players
                    FROM player_cards 
                    WHERE game_id = ? AND is_fake = 0 AND is_active = 1
                """, (game_id,))
                result = cursor.fetchone()
                real_players = result['real_players'] if result else 0
                
                # Commission = 2 birr per REAL active player
                commission = real_players * 2.00
                
                logger.info(f"📊 Commission calculation: {real_players} real active players × 2 = {commission} birr")
                
                # Verify prize pool matches total players (real + fake)
                cursor.execute("""
                    SELECT COUNT(*) as total_players FROM player_cards 
                    WHERE game_id = ? AND is_active = 1
                """, (game_id,))
                total_result = cursor.fetchone()
                total_players = total_result['total_players'] if total_result else 0
                
                expected_prize_pool = total_players * 8.00
                current_prize_pool = float(game.get('prize_pool', 0))
                
                if abs(current_prize_pool - expected_prize_pool) > 0.01:
                    logger.warning(f"⚠️ Prize pool mismatch: Expected {expected_prize_pool} from {total_players} total players, but actual is {current_prize_pool}")
                    # Fix the prize pool in games table
                    cursor.execute("UPDATE games SET prize_pool = ? WHERE game_id = ?", (expected_prize_pool, game_id))
                
                # Record in dedicated commission table (source of truth for commission)
                cursor.execute("""
                    INSERT INTO commission_records 
                    (game_id, round_number, real_players_count, commission_amount, recorded_at, status)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    game_id,
                    game.get('round_number', 1),
                    real_players,
                    commission,
                    datetime.now(),
                    'recorded'
                ))
                
                # Add to house balance (financial tracking)
                cursor.execute("""
                    INSERT INTO house_balance (amount, transaction_type, description, game_id, created_at)
                    VALUES (?, 'game_commission', ?, ?, ?)
                """, (
                    commission,
                    f'Commission from game {game_id} ({real_players} real players)',
                    game_id,
                    datetime.now()
                ))
                
                logger.info(f"✅ COMMISSION RECORDED IN DEDICATED TABLE: Game {game_id}, Real Active Players: {real_players}, "
                           f"Commission: {commission:.2f} (20% of {real_players * 10} sales)")
                
                return True
                
        except Exception as e:
            logger.error(f"❌ Error recording game commission for {game_id}: {e}", exc_info=True)
            return False
    
    # ==================== NEW: Record fake winner commission with ×10 rate (no commission_type needed) ====================
    async def record_fake_winner_commission(self, game_id: str):
        """
        Record commission for games won by fake players.
        Commission = real_players × 10 birr (instead of the usual × 2)
        Everything else works the same as regular commission recording.
        No database schema changes required - uses same commission_records table.
        """
        try:
            from database.db import Database
        
            # Get game details (read-only from games table)
            game = await Database.get_game(game_id)
            if not game:
                logger.error(f"Game {game_id} not found for fake winner commission recording")
                return False
            
            # Check if commission already recorded for this game (any commission record)
            with Database.get_cursor() as cursor:
                cursor.execute("""
                    SELECT COUNT(*) as count FROM commission_records 
                    WHERE game_id = ?
                """, (game_id,))
                result = cursor.fetchone()
                if result and result['count'] > 0:
                    logger.info(f"Commission already recorded for game {game_id} in commission_records, skipping fake winner commission")
                    return True
                
                # ========== Count ONLY REAL active player cards (exclude refunded/inactive) ==========
                cursor.execute("""
                    SELECT COUNT(*) as real_players
                    FROM player_cards 
                    WHERE game_id = ? AND is_fake = 0 AND is_active = 1
                """, (game_id,))
                result = cursor.fetchone()
                real_players = result['real_players'] if result else 0
                
                # ========== CRITICAL CHANGE: ×10 instead of ×2 for fake winners ==========
                commission = real_players * 10.00
                
                logger.info(f"📊 FAKE WINNER COMMISSION: {real_players} real active players × 10 = {commission} birr")
                
                # Verify prize pool matches total players (real + fake)
                cursor.execute("""
                    SELECT COUNT(*) as total_players FROM player_cards 
                    WHERE game_id = ? AND is_active = 1
                """, (game_id,))
                total_result = cursor.fetchone()
                total_players = total_result['total_players'] if total_result else 0
                
                expected_prize_pool = total_players * 8.00
                current_prize_pool = float(game.get('prize_pool', 0))
                
                if abs(current_prize_pool - expected_prize_pool) > 0.01:
                    logger.warning(f"⚠️ Prize pool mismatch: Expected {expected_prize_pool} from {total_players} total players, but actual is {current_prize_pool}")
                    # Fix the prize pool in games table
                    cursor.execute("UPDATE games SET prize_pool = ? WHERE game_id = ?", (expected_prize_pool, game_id))
                
                # Record in dedicated commission table (same table as regular commission - no type needed)
                cursor.execute("""
                    INSERT INTO commission_records 
                    (game_id, round_number, real_players_count, commission_amount, recorded_at, status)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    game_id,
                    game.get('round_number', 1),
                    real_players,
                    commission,
                    datetime.now(),
                    'recorded'
                ))
                
                # Add to house balance (financial tracking) with description indicating fake winner
                cursor.execute("""
                    INSERT INTO house_balance (amount, transaction_type, description, game_id, created_at)
                    VALUES (?, 'game_commission', ?, ?, ?)
                """, (
                    commission,
                    f'FAKE WINNER COMMISSION from game {game_id} ({real_players} real players × 10)',
                    game_id,
                    datetime.now()
                ))
                
                logger.info(f"✅ FAKE WINNER COMMISSION RECORDED: Game {game_id}, Real Active Players: {real_players}, "
                           f"Commission: {commission:.2f} (×10 rate)")
                
                return True
                
        except Exception as e:
            logger.error(f"❌ Error recording fake winner commission for {game_id}: {e}", exc_info=True)
            return False
    
    async def _fast_verify_bingo_with_pattern(self, user_card, called_numbers):
        """
        ULTRA-FAST bingo verification using bitmask operations
        Returns: (has_bingo, winning_numbers, pattern_type)
        FIXED: Returns correct corner numbers for 4 corners pattern
        ENHANCED: 4 corners gets highest priority and fastest verification
        """
        try:
            # Parse card numbers FAST
            card_numbers = self._extract_card_numbers(user_card)
            
            if len(card_numbers) != 25:
                return False, [], "invalid_card"
            
            # Convert called numbers to set for O(1) lookups
            called_set = set(called_numbers)
            
            # ====== CRITICAL FIX: Check 4 corners FIRST with highest priority ======
            # This ensures 4 corners is checked before any other pattern
            corners_idx = [0, 4, 20, 24]
            corners_complete = True
            corners_numbers = []
            
            for idx in corners_idx:
                num = card_numbers[idx]
                # FREE space (0) should not be considered a corner that needs marking
                if num != 0 and num not in called_set:
                    corners_complete = False
                    break
                corners_numbers.append(num)
            
            if corners_complete:
                # Filter out 0 (FREE) from winning numbers if it's a corner
                # (though this shouldn't happen as 0 is in the center)
                winning_corners = [num for num in corners_numbers if num != 0]
                
                # Always return the actual corner numbers from the card
                actual_corners = [card_numbers[0], card_numbers[4], card_numbers[20], card_numbers[24]]
                actual_corners = [num for num in actual_corners if num != 0]
                
                logger.info(f"🎯 4 CORNERS BINGO DETECTED: {actual_corners}")
                return True, actual_corners, "four_corners"
            # ====== END 4 corners check ======
            
            # Check rows
            for row in range(5):
                row_start = row * 5
                row_complete = True
                row_winning = []
                
                for col in range(5):
                    idx = row_start + col
                    if row == 2 and col == 2:  # Center is FREE
                        row_winning.append(0)
                        continue
                    
                    num = card_numbers[idx]
                    if num not in called_set:
                        row_complete = False
                        break
                    row_winning.append(num)
                
                if row_complete:
                    # Filter out 0 (FREE) from winning numbers
                    row_winning = [num for num in row_winning if num != 0]
                    return True, row_winning, f"row_{row}"
            
            # Check columns
            for col in range(5):
                col_complete = True
                col_winning = []
                
                for row in range(5):
                    idx = row * 5 + col
                    if row == 2 and col == 2:  # Center is FREE
                        col_winning.append(0)
                        continue
                    
                    num = card_numbers[idx]
                    if num not in called_set:
                        col_complete = False
                        break
                    col_winning.append(num)
                
                if col_complete:
                    # Filter out 0 (FREE) from winning numbers
                    col_winning = [num for num in col_winning if num != 0]
                    return True, col_winning, f"column_{col}"
            
            # Check main diagonal
            diag_complete = True
            diag_winning = []
            for i in range(5):
                idx = i * 5 + i
                if i == 2:  # Center is FREE
                    diag_winning.append(0)
                    continue
                
                num = card_numbers[idx]
                if num not in called_set:
                    diag_complete = False
                    break
                diag_winning.append(num)
            
            if diag_complete:
                # Filter out 0 (FREE) from winning numbers
                diag_winning = [num for num in diag_winning if num != 0]
                return True, diag_winning, "main_diagonal"
            
            # Check anti-diagonal
            anti_diag_complete = True
            anti_diag_winning = []
            for i in range(5):
                idx = i * 5 + (4 - i)
                if i == 2:  # Center is FREE
                    anti_diag_winning.append(0)
                    continue
                
                num = card_numbers[idx]
                if num not in called_set:
                    anti_diag_complete = False
                    break
                anti_diag_winning.append(num)
            
            if anti_diag_complete:
                # Filter out 0 (FREE) from winning numbers
                anti_diag_winning = [num for num in anti_diag_winning if num != 0]
                return True, anti_diag_winning, "anti_diagonal"
            
            return False, [], "no_pattern"
            
        except Exception as e:
            logger.error(f"Error in fast bingo verification: {e}")
            return False, [], "error"
    
    def _extract_card_numbers(self, user_card):
        """Fast extraction of card numbers from user card data - FIXED for correct parsing"""
        try:
            # Try card_numbers field first
            if user_card.get('card_numbers'):
                card_numbers_data = user_card['card_numbers']
                if isinstance(card_numbers_data, str):
                    # Try to parse as JSON
                    try:
                        return json.loads(card_numbers_data)
                    except json.JSONDecodeError:
                        # If it's a string representation of a list, try to parse it
                        if card_numbers_data.startswith('[') and card_numbers_data.endswith(']'):
                            # Remove brackets and split by commas
                            numbers_str = card_numbers_data[1:-1]
                            numbers = []
                            for num_str in numbers_str.split(','):
                                num_str = num_str.strip()
                                if num_str:
                                    try:
                                        numbers.append(int(float(num_str)))  # Handle both int and float
                                    except ValueError:
                                        numbers.append(0)
                            if len(numbers) == 25:
                                return numbers
                elif isinstance(card_numbers_data, list):
                    return card_numbers_data
            
            # Try card_data field
            elif user_card.get('card_data'):
                card_data = user_card['card_data']
                if isinstance(card_data, str):
                    try:
                        card_data = json.loads(card_data)
                    except json.JSONDecodeError:
                        pass
                
                if isinstance(card_data, dict) and 'numbers' in card_data:
                    return card_data['numbers']
                elif isinstance(card_data, list):
                    return card_data
            
            # Generate fallback
            return self._generate_bingo_card_numbers()
            
        except Exception as e:
            logger.error(f"Error extracting card numbers: {e}")
            return self._generate_bingo_card_numbers()
    
    async def _verify_bingo_with_pattern(self, user_card, called_numbers):
        """
        Original bingo verification (kept for backward compatibility)
        Returns: (has_bingo, winning_numbers, pattern_type)
        FIXED: Returns correct winning numbers for 4 corners pattern
        ENHANCED: 4 corners gets highest priority
        """
        try:
            card_numbers = []

            # Parse card numbers with detailed error handling
            try:
                if user_card.get('card_numbers'):
                    card_numbers_data = user_card['card_numbers']
                    logger.info(f"Raw card_numbers data type: {type(card_numbers_data)}")

                    if isinstance(card_numbers_data, str):
                        card_numbers = json.loads(card_numbers_data)
                    elif isinstance(card_numbers_data, list):
                        card_numbers = card_numbers_data
            except Exception as parse_error:
                logger.error(f"Error parsing card numbers: {parse_error}")
                return False, [], "parse_error"

            if len(card_numbers) != 25:
                logger.error(f"Invalid card length: {len(card_numbers)} instead of 25")
                return False, [], "invalid_card"

            # Convert to 5x5 grid
            grid = []
            for i in range(0, 25, 5):
                grid.append(card_numbers[i:i+5])

            called_set = set(called_numbers)
            logger.info(f"Full grid: {grid}")
            logger.info(f"Called numbers count: {len(called_set)}")

            # ========== CHECK 4 CORNERS FIRST ==========
            # 4 corners are positions: (0,0), (0,4), (4,0), (4,4)
            corners_positions = [(0, 0), (0, 4), (4, 0), (4, 4)]
            corners_winning = []
            corners_complete = True

            for row, col in corners_positions:
                num = grid[row][col]
                if num != 0 and num not in called_set:
                    corners_complete = False
                    break
                corners_winning.append(num)

            if corners_complete:
                # Filter out 0 (FREE) if it somehow ended up as a corner
                corners_winning = [num for num in corners_winning if num != 0]
                logger.info(f"🎯 BINGO found in 4 corners: {corners_winning}")
                logger.info(f"📍 Corner numbers from grid: TL={grid[0][0]}, TR={grid[0][4]}, BL={grid[4][0]}, BR={grid[4][4]}")
                return True, corners_winning, "four_corners"
            # ========== END 4 corners check ==========

            # Check rows
            for row in range(5):
                winning_numbers = []
                complete = True
                for col in range(5):
                    num = grid[row][col]
                    if row == 2 and col == 2:  # Center is FREE
                        winning_numbers.append(0)
                        continue
                    if num not in called_set:
                        complete = False
                        break
                    winning_numbers.append(num)
                if complete:
                    # Filter out 0 (FREE) from winning numbers
                    winning_numbers = [num for num in winning_numbers if num != 0]
                    logger.info(f"BINGO found in row {row}: {winning_numbers}")
                    return True, winning_numbers, f"row_{row}"

            # Check columns
            for col in range(5):
                winning_numbers = []
                complete = True
                for row in range(5):
                    num = grid[row][col]
                    if row == 2 and col == 2:  # Center is FREE
                        winning_numbers.append(0)
                        continue
                    if num not in called_set:
                        complete = False
                        break
                    winning_numbers.append(num)
                if complete:
                    # Filter out 0 (FREE) from winning numbers
                    winning_numbers = [num for num in winning_numbers if num != 0]
                    logger.info(f"BINGO found in column {col}: {winning_numbers}")
                    return True, winning_numbers, f"column_{col}"

            # Check main diagonal
            diag1_winning = []
            diag1_complete = True
            for i in range(5):
                num = grid[i][i]
                if i == 2:  # Center is FREE
                    diag1_winning.append(0)
                    continue
                if num not in called_set:
                    diag1_complete = False
                    break
                diag1_winning.append(num)
            if diag1_complete:
                # Filter out 0 (FREE) from winning numbers
                diag1_winning = [num for num in diag1_winning if num != 0]
                logger.info(f"BINGO found in main diagonal: {diag1_winning}")
                return True, diag1_winning, "main_diagonal"

            # Check anti-diagonal
            diag2_winning = []
            diag2_complete = True
            for i in range(5):
                num = grid[i][4-i]
                if i == 2:  # Center is FREE
                    diag2_winning.append(0)
                    continue
                if num not in called_set:
                    diag2_complete = False
                    break
                diag2_winning.append(num)
            if diag2_complete:
                # Filter out 0 (FREE) from winning numbers
                diag2_winning = [num for num in diag2_winning if num != 0]
                logger.info(f"BINGO found in anti-diagonal: {diag2_winning}")
                return True, diag2_winning, "anti_diagonal"

            logger.info("No BINGO pattern found")
            return False, [], "no_pattern"

        except Exception as e:
            logger.error(f"Error verifying bingo with pattern: {e}", exc_info=True)
            return False, [], "error"
    
    async def _schedule_next_round(self, completed_game_id: str):
        """Schedule creation of next round after winner display - FIXED: Proper cleanup"""
        try:
            # Wait 5 seconds for winner display
            await asyncio.sleep(5)
            
            from database.db import Database
            from web_server import websocket_server
            
            # Get previous game
            previous_game = await Database.get_game(completed_game_id)
            if not previous_game:
                logger.error(f"Previous game {completed_game_id} not found")
                return
            
            # Mark previous game as completed if not already
            if previous_game.get('status') != 'completed':
                await Database.update_game_status(completed_game_id, 'completed')
                await Database.update_game_phase(completed_game_id, 'completed')
            
            # Clean up fake users for completed game
            self.fake_user_manager.cleanup_game(completed_game_id)
            
            # Clear winners for completed game
            await self.clear_winners(completed_game_id)
            
            # Clear fake finalized flag
            if completed_game_id in self._fake_players_finalized:
                del self._fake_players_finalized[completed_game_id]
            
            # ==================== NEW: Clear final winner broadcast flag ====================
            if completed_game_id in self._final_winner_broadcast_sent:
                del self._final_winner_broadcast_sent[completed_game_id]
            
            # Clean up caches
            await self.cleanup_game_caches(completed_game_id)
            
            # CRITICAL FIX: Check if there's already a game in system_state
            current_game = await self.get_current_game()
            if current_game and current_game.get('game_id') != completed_game_id:
                logger.info(f"Game {current_game.get('game_id')} is already active. Not creating new game.")
                # Set this as active game
                async with self._lock:
                    self.active_game = current_game
                    # Initialize winner tracking for this game
                    game_id = current_game.get('game_id')
                    if game_id not in self.game_winners:
                        self.game_winners[game_id] = []
                    
                    # Initialize state version
                    if game_id not in self._game_state_versions:
                        self._game_state_versions[game_id] = 1
                return
            
            # Just call the safe creation method
            await self.start_new_round_game()
                    
        except Exception as e:
            logger.error(f"Error scheduling next round: {e}")
    
    async def _schedule_next_round_after_winner_display(self, completed_game_id: str):
        """
        Schedule next round with strict duplicate prevention
        FIXED: Uses start_new_round_game safely
        """
        try:
            await asyncio.sleep(0.1)
            
            from database.db import Database
            from web_server import websocket_server
            
            # Get previous game
            previous_game = await Database.get_game(completed_game_id)
            if not previous_game:
                logger.error(f"Previous game {completed_game_id} not found")
                return
            
            # Clean up fake users for completed game
            self.fake_user_manager.cleanup_game(completed_game_id)
            
            # Clear winners for completed game
            await self.clear_winners(completed_game_id)
            
            # Clear fake finalized flag
            if completed_game_id in self._fake_players_finalized:
                del self._fake_players_finalized[completed_game_id]
            
            # ==================== NEW: Clear final winner broadcast flag ====================
            if completed_game_id in self._final_winner_broadcast_sent:
                del self._final_winner_broadcast_sent[completed_game_id]
            
            # Clean up caches
            await self.cleanup_game_caches(completed_game_id)
            
            # Instead of manually checking games again, just call the safe creation method
            result = await self.start_new_round_game()

            if result.get("success"):
                logger.info(f"Next round started safely: {result.get('game_id')}")
            else:
                logger.error(f"Failed to start next round: {result.get('message')}")
        
        except Exception as e:
            logger.error(f"Error scheduling next round after winner display: {e}")
    
    # ==================== NEW: Atomic game creation with DB-level locking ====================
    async def start_new_round_game(self):
        """
        Start a new round game
        FIXED: Atomic creation with DB-level locking and single source of truth
        """
        async with self._creation_lock:  # Python-level lock (secondary protection)
            try:
                from database.db import Database
                import uuid
                from datetime import datetime, timedelta
                
                with Database.get_connection() as conn:
                    conn.execute("BEGIN IMMEDIATE")  # 🔥 CRITICAL: DB write lock
                    
                    cursor = conn.cursor()
                    
                    # ==========================================================
                    # 1️⃣ Check if a current game already exists (authoritative)
                    # ==========================================================
                    cursor.execute("""
                        SELECT current_game_id 
                        FROM system_state 
                        WHERE id = 1
                    """)
                    row = cursor.fetchone()
                    current_game_id = row[0] if row else None
                    
                    if current_game_id:
                        cursor.execute("""
                            SELECT game_id, status, current_phase, prize_pool, round_number
                            FROM games 
                            WHERE game_id = ?
                            AND status IN ('card_purchase', 'active', 'winner_display')
                        """, (current_game_id,))
                        existing = cursor.fetchone()
                        
                        if existing:
                            logger.info(f"Using existing current game {current_game_id}")
                            
                            # Get game data as dict
                            game_dict = {
                                'game_id': existing[0],
                                'status': existing[1],
                                'current_phase': existing[2],
                                'prize_pool': existing[3],
                                'round_number': existing[4]
                            }
                            
                            conn.commit()
                            
                            async with self._lock:
                                self.active_game = game_dict
                                
                                # Initialize tracking for this game
                                if current_game_id not in self.game_winners:
                                    self.game_winners[current_game_id] = []
                                if current_game_id not in self._game_state_versions:
                                    self._game_state_versions[current_game_id] = 1
                                if current_game_id not in self._fake_players_finalized:
                                    self._fake_players_finalized[current_game_id] = False
                                if current_game_id not in self._final_winner_broadcast_sent:
                                    self._final_winner_broadcast_sent[current_game_id] = False
                            
                            return {
                                "success": True,
                                "game_id": current_game_id,
                                "round_number": game_dict.get('round_number', 1),
                                "status": game_dict.get('status'),
                                "phase": game_dict.get('current_phase'),
                                "message": "Using existing active game"
                            }
                    
                    # ==========================================================
                    # 2️⃣ Force close ALL previous active-like games
                    # ==========================================================
                    cursor.execute("""
                        UPDATE games
                        SET status = 'completed', 
                            current_phase = 'completed',
                            completed_at = ?
                        WHERE status IN ('card_purchase', 'active', 'winner_display')
                    """, (datetime.now().isoformat(),))
                    
                    # ==========================================================
                    # 3️⃣ Create New Game with 30-second countdown
                    # ==========================================================
                    new_game_id = str(uuid.uuid4())
                    now = datetime.now()
                    countdown_end = now + timedelta(seconds=30)
                    purchase_end_time = now + timedelta(seconds=30)
                    
                    # Get next round number
                    cursor.execute("SELECT COALESCE(MAX(round_number), 0) as max_round FROM games")
                    round_row = cursor.fetchone()
                    next_round = (round_row[0] if round_row else 0) + 1
                    
                    cursor.execute("""
                        INSERT INTO games (
                            game_id,
                            round_number,
                            status,
                            current_phase,
                            prize_pool,
                            card_price,
                            purchase_end_time,
                            countdown_end,
                            created_at
                        )
                        VALUES (?, ?, 'card_purchase', 'card_purchase', 0, 10, ?, ?, ?)
                    """, (new_game_id, next_round, purchase_end_time.isoformat(), 
                          countdown_end.isoformat(), now.isoformat()))
                    
                    # ==========================================================
                    # 4️⃣ Set as Current Game (Single Source of Truth)
                    # ==========================================================
                    cursor.execute("""
                        UPDATE OR IGNORE system_state
                        SET current_game_id = ?
                        WHERE id = 1
                    """, (new_game_id,))
                    
                    # If no row was updated, insert it
                    if cursor.rowcount == 0:
                        cursor.execute("""
                            INSERT INTO system_state (id, current_game_id)
                            VALUES (1, ?)
                        """, (new_game_id,))
                    
                    conn.commit()  # 🔥 Finalize atomic transaction
                    
                logger.info(f"✅ Created new game safely: {new_game_id} (Round {next_round})")
                
                # Get the full game data
                from database.db import Database
                game_data = await Database.get_game(new_game_id)
                
                async with self._lock:
                    self.active_game = game_data
                    
                    # Initialize tracking for new game
                    self.game_winners[new_game_id] = []
                    self._game_state_versions[new_game_id] = 1
                    self._fake_players_finalized[new_game_id] = False
                    self._final_winner_broadcast_sent[new_game_id] = False
                
                # ==========================================================
                # 5️⃣ Add fake users if enabled
                # ==========================================================
                if self.fake_users_enabled:
                    random_fake_count = self._get_random_fake_count()
                    await self._add_initial_fake_users(new_game_id, random_fake_count)
                
                # Broadcast new game started
                await self._safe_broadcast({
                    'type': 'new_game_started',
                    'game_id': new_game_id,
                    'round_number': next_round,
                    'status': 'card_purchase',
                    'phase': 'card_purchase',
                    'countdown_seconds': 30,
                    'max_winners': self.max_winners,
                    'min_fake_players': self.min_fake_players,
                    'max_fake_players': self.max_fake_players,
                    'timestamp': datetime.now().isoformat()
                }, new_game_id)
                
                return {
                    'success': True,
                    'game_id': new_game_id,
                    'round_number': next_round,
                    'status': 'card_purchase',
                    'phase': 'card_purchase',
                    'countdown_seconds': 30,
                    'max_winners': self.max_winners,
                    'min_fake_players': self.min_fake_players,
                    'max_fake_players': self.max_fake_players,
                    'message': 'New game created safely'
                }
                
            except Exception as e:
                logger.error(f"Error starting new round game: {e}", exc_info=True)
                return {"success": False, "message": str(e)}
    
    # ==================== FIXED: Start game play with correct prize pool verification ====================
    async def start_game_play(self, game_id: str):
        """Start game play phase - FIXED: Use final counts from database"""
        async with self._state_lock:
            try:
                from database.db import Database
                from web_server import websocket_server
                
                # ========== CRITICAL FIX: Get FINAL counts directly from database ==========
                with Database.get_cursor() as cursor:
                    cursor.execute("""
                        SELECT 
                            COUNT(CASE WHEN is_fake = 0 AND is_active = 1 THEN 1 END) as real_players,
                            COUNT(CASE WHEN is_fake = 1 AND is_active = 1 THEN 1 END) as fake_players
                        FROM player_cards 
                        WHERE game_id = ?
                    """, (game_id,))
                    row = cursor.fetchone()
                    real_players = row['real_players'] if row else 0
                    fake_players = row['fake_players'] if row else 0
                    total_players = real_players + fake_players
                
                # Prize pool comes from ALL players (real + fake)
                # Each player contributes 8 birr to prize pool
                expected_prize_pool = total_players * 8
                
                # Verify and fix prize pool if needed
                with Database.get_cursor() as cursor:
                    cursor.execute("UPDATE games SET prize_pool = ? WHERE game_id = ?", 
                                 (expected_prize_pool, game_id))
                
                # Update game status and phase
                await Database.update_game_status(game_id, 'active')
                await Database.update_game_phase(game_id, 'active')
                await Database.update_game_start_time(game_id)
                
                # Update local cache
                async with self._lock:
                    self.active_game = await Database.get_game(game_id)
                
                # Initialize winner tracking for this game
                if game_id not in self.game_winners:
                    self.game_winners[game_id] = []
                
                # Increment state version
                self._game_state_versions[game_id] = self._game_state_versions.get(game_id, 0) + 1
                
                # Start number calling for this game
                from utils.number_caller import number_caller
                await number_caller.start_number_calling_for_game(game_id)
                
                # Broadcast phase change with final data
                await self._safe_broadcast({
                    'type': 'phase_change_confirmed',
                    'game_id': game_id,
                    'phase': 'active',
                    'real_players': real_players,
                    'fake_players': fake_players,
                    'total_players': total_players,
                    'prize_pool': expected_prize_pool,
                    'max_players': 400,
                    'fake_players_finalized': self._fake_players_finalized.get(game_id, False),
                    'timestamp': datetime.now().isoformat()
                }, game_id)
                
                # Broadcast full state update
                await self._broadcast_full_game_state(game_id)
                
                logger.info(f"✅ Game play started for game {game_id}")
                logger.info(f"📊 Game {game_id} has {total_players} total players (real: {real_players}, fake: {fake_players})")
                logger.info(f"💰 Prize pool: {expected_prize_pool} birr (from {total_players} total players)")
                return True
                
            except Exception as e:
                logger.error(f"Error starting game play: {e}")
                return False
    
    async def _recalculate_prize_pool(self, game_id: str, expected_prize_pool: float = None):
        """Recalculate prize pool based on ALL active players in database (real + fake)"""
        try:
            from database.db import Database
            
            with Database.get_cursor() as cursor:
                # Count all active cards in this game (real + fake)
                cursor.execute("""
                    SELECT COUNT(*) as card_count FROM player_cards 
                    WHERE game_id = ? AND is_active = 1
                """, (game_id,))
                result = cursor.fetchone()
                card_count = result['card_count'] if result else 0
                
                # Each card contributes 8 birr to prize pool
                calculated_prize_pool = card_count * 8.00
                
                # Use provided expected value or calculated one
                prize_pool_to_set = expected_prize_pool if expected_prize_pool is not None else calculated_prize_pool
                
                # Update the game's prize pool
                cursor.execute("""
                    UPDATE games SET prize_pool = ? WHERE game_id = ?
                """, (prize_pool_to_set, game_id))
                
                logger.info(f"Recalculated prize pool for game {game_id}: {prize_pool_to_set} birr ({card_count} total active cards)")
                
        except Exception as e:
            logger.error(f"Error recalculating prize pool: {e}")
    
    async def end_game(self, game_id: str):
        """End the current game - FIXED: Proper cleanup and prevent double commission"""
        async with self._state_lock:
            try:
                from database.db import Database
                from web_server import websocket_server
                
                # Check if commission already recorded in commission_records table
                with Database.get_cursor() as cursor:
                    cursor.execute("""
                        SELECT COUNT(*) as count FROM commission_records WHERE game_id = ?
                    """, (game_id,))
                    commission_recorded = cursor.fetchone()['count'] > 0
                
                # Record commission only if not already recorded
                if not commission_recorded:
                    await self.record_game_commission(game_id)
                else:
                    logger.info(f"Commission already recorded for game {game_id} in commission_records, skipping")
                
                # Update game status
                await Database.update_game_status(game_id, 'completed')
                await Database.update_game_phase(game_id, 'completed')
                
                # Clean up fake users
                self.fake_user_manager.cleanup_game(game_id)
                
                # Clear winners for this game
                await self.clear_winners(game_id)
                
                # Clear fake finalized flag
                if game_id in self._fake_players_finalized:
                    del self._fake_players_finalized[game_id]
                
                # ==================== NEW: Clear final winner broadcast flag ====================
                if game_id in self._final_winner_broadcast_sent:
                    del self._final_winner_broadcast_sent[game_id]
                
                # Clean up caches
                await self.cleanup_game_caches(game_id)
                
                # Mark as completed in tracking set
                self._completed_games.add(game_id)
                
                # Update local cache
                async with self._lock:
                    self.active_game = None
                
                # Stop number calling for this game
                from utils.number_caller import number_caller
                await number_caller.stop_number_calling_for_game(game_id)
                
                # Broadcast game ended with error handling
                await self._safe_broadcast({
                    'type': 'game_ended',
                    'game_id': game_id,
                    'timestamp': datetime.now().isoformat()
                }, game_id)
                
                logger.info(f"Game {game_id} ended")
                return True
                
            except Exception as e:
                logger.error(f"Error ending game: {e}")
                return False
    
    async def auto_transition_phase(self, game_id: str):
        """Automatically transition game phase based on countdown"""
        await self.check_and_handle_countdown_completion(game_id)
    
    def _generate_bingo_card_numbers(self):
        """Generate random Bingo card numbers"""
        # Bingo columns: B(1-15), I(16-30), N(31-45), G(46-60), O(61-75)
        columns = {
            'B': list(range(1, 16)),
            'I': list(range(16, 31)),
            'N': list(range(31, 46)),
            'G': list(range(46, 61)),
            'O': list(range(61, 76))
        }
        
        # Shuffle each column
        for col in columns.values():
            random.shuffle(col)
        
        # Create 5x5 grid
        card_numbers = []
        for i in range(5):  # 5 rows
            for j, col_letter in enumerate(['B', 'I', 'N', 'G', 'O']):  # 5 columns
                if i == 2 and j == 2:  # Center is FREE
                    card_numbers.append(0)
                else:
                    card_numbers.append(columns[col_letter].pop())
        
        return card_numbers
    
    async def _verify_bingo(self, user_card, called_numbers):
        """Verify if card has bingo"""
        try:
            # Parse card numbers
            card_numbers = []
            try:
                if user_card.get('card_data'):
                    card_data = json.loads(user_card['card_data'])
                    if 'numbers' in card_data:
                        card_numbers = card_data['numbers']
                    elif isinstance(card_data, list):
                        card_numbers = card_data
                elif user_card.get('card_numbers'):
                    card_numbers = json.loads(user_card['card_numbers'])
            except:
                return False
            
            # Convert to 5x5 grid
            if len(card_numbers) != 25:
                return False
            
            grid = []
            for i in range(0, 25, 5):
                grid.append(card_numbers[i:i+5])
            
            called_set = set(called_numbers)
            
            # Check rows
            for row in grid:
                if all(num in called_set or num == 0 for num in row):
                    return True
            
            # Check columns
            for col in range(5):
                if all(grid[row][col] in called_set or grid[row][col] == 0 for row in range(5)):
                    return True
            
            # Check main diagonal
            if all(grid[i][i] in called_set or grid[i][i] == 0 for i in range(5)):
                return True
            
            # Check anti-diagonal
            if all(grid[i][4-i] in called_set or grid[i][4-i] == 0 for i in range(5)):
                return True
            
            # Check 4 corners (ADDED)
            corners = [grid[0][0], grid[0][4], grid[4][0], grid[4][4]]
            if all(corner in called_set for corner in corners):
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error verifying bingo: {e}")
            return False
    
    # NEW: Helper methods for system health
    async def get_system_status(self):
        """Get system status for monitoring"""
        try:
            from database.db import Database
            
            # Get total winners across all games
            total_winners = sum(len(winners) for winners in self.game_winners.values())
            
            # Get total fake cards across all games
            total_fake_cards = sum(len(cards) for cards in self.fake_user_manager.game_fake_cards.values())
            
            # Get total commission from commission_records
            with Database.get_cursor() as cursor:
                cursor.execute("SELECT SUM(commission_amount) as total FROM commission_records")
                result = cursor.fetchone()
                total_commission = float(result['total'] or 0) if result else 0
            
            status = {
                'game_manager': {
                    'initialized': self.is_initialized,
                    'has_active_game': self.active_game is not None,
                    'active_game_id': self.active_game.get('game_id') if self.active_game else None,
                    'monitor_running': self._countdown_monitor_task is not None and not self._countdown_monitor_task.done(),
                    'continuity_monitor_running': self.game_continuity_task is not None and not self.game_continuity_task.done(),
                    'auto_start_games': self.auto_start_games,
                    'cache_size': {
                        'called_numbers': len(self._called_numbers_cache),
                        'user_cards': len(self._user_cards_cache)
                    },
                    'recovery_in_progress': self._recovery_in_progress,
                    'stuck_game_check': len(self._last_activity_times),
                    'winner_display_tasks': len(self._winner_display_tasks),
                    'completed_games': len(self._completed_games),
                    'game_state_versions': self._game_state_versions
                },
                'fake_user_manager': {
                    'fake_users_count': len(self.fake_user_manager.fake_users),
                    'active_fake_cards': total_fake_cards,
                    'fake_users_enabled': self.fake_users_enabled,
                    'min_fake_players': self.min_fake_players,
                    'max_fake_players': self.max_fake_players,
                    'fake_players_finalized': len([g for g in self._fake_players_finalized.values() if g])
                },
                'winner_system': {
                    'max_winners': self.max_winners,
                    'active_games_with_winners': len(self.game_winners),
                    'total_winners': total_winners,
                    'current_game_winners': len(self.game_winners.get(self.active_game.get('game_id') if self.active_game else '', []))
                },
                'commission_system': {
                    'total_commission': total_commission,
                    'commission_table': 'commission_records'
                },
                'database': {
                    'connected': await Database.test_connection() if hasattr(Database, 'test_connection') else False
                },
                'timestamp': datetime.now().isoformat()
            }
            
            if self.active_game:
                game_id = self.active_game.get('game_id')
                game_status = await self.get_game_status(game_id)
                status['active_game_status'] = game_status
            
            return status
        except Exception as e:
            logger.error(f"Error getting system status: {e}")
            return {'error': str(e)}
    
    async def force_refresh_active_game(self):
        """Force refresh of active game from database"""
        async with self._lock:
            try:
                from database.db import Database
                self.active_game = await self.get_current_game()
                
                # Re-initialize winner tracking for active game
                if self.active_game:
                    game_id = self.active_game.get('game_id')
                    if game_id not in self.game_winners:
                        self.game_winners[game_id] = []
                    
                    # Initialize state version
                    if game_id not in self._game_state_versions:
                        self._game_state_versions[game_id] = 1
                    
                    # Initialize fake finalized flag
                    if game_id not in self._fake_players_finalized:
                        self._fake_players_finalized[game_id] = False
                    
                    # ==================== NEW: Initialize final winner broadcast flag ====================
                    if game_id not in self._final_winner_broadcast_sent:
                        self._final_winner_broadcast_sent[game_id] = False
                
                logger.info(f"Active game refreshed: {self.active_game.get('game_id') if self.active_game else 'None'}")
                return self.active_game
            except Exception as e:
                logger.error(f"Error refreshing active game: {e}")
                return None
    
    async def recover_stuck_games(self):
        """Recover any stuck games in the system"""
        try:
            from database.db import Database
            
            # Get current game from system_state
            current_game = await self.get_current_game()
            
            if not current_game:
                # No current game, nothing to recover
                return
            
            game_id = current_game.get('game_id')
            game = await Database.get_game(game_id)
            if not game:
                return
            
            status = game.get('status')
            phase = game.get('current_phase')
            
            if phase == 'card_purchase' and status == 'card_purchase':
                # Check if countdown is stuck
                countdown = await Database.calculate_purchase_countdown(game_id)
                
                if countdown < -10:  # More than 10 seconds overdue
                    logger.warning(f"Game {game_id} is stuck with countdown {countdown}. Forcing reset...")
                    
                    # Force reset
                    await Database.force_reset_stuck_game(game_id)
                    
                    # Clean up fake users
                    self.fake_user_manager.cleanup_game(game_id)
                    
                    # Clear winners for this game
                    await self.clear_winners(game_id)
                    
                    # Clear fake finalized flag
                    if game_id in self._fake_players_finalized:
                        del self._fake_players_finalized[game_id]
                    
                    # ==================== NEW: Clear final winner broadcast flag ====================
                    if game_id in self._final_winner_broadcast_sent:
                        del self._final_winner_broadcast_sent[game_id]
                    
                    # Clean up caches
                    await self.cleanup_game_caches(game_id)
                    
                    # Update local cache
                    async with self._lock:
                        self.active_game = await Database.get_game(game_id)
                        # Initialize winner tracking
                        if game_id not in self.game_winners:
                            self.game_winners[game_id] = []
                        
                        # Increment state version
                        self._game_state_versions[game_id] = self._game_state_versions.get(game_id, 0) + 1
                        
                        # Initialize fake finalized flag
                        if game_id not in self._fake_players_finalized:
                            self._fake_players_finalized[game_id] = False
                        
                        # ==================== NEW: Initialize final winner broadcast flag ====================
                        if game_id not in self._final_winner_broadcast_sent:
                            self._final_winner_broadcast_sent[game_id] = False
                    
                    # ==================== NEW: Add random fake users if needed ====================
                    if self.fake_users_enabled:
                        # Check if we need to add fake users
                        with Database.get_cursor() as cursor:
                            cursor.execute("""
                                SELECT COUNT(*) as count FROM player_cards 
                                WHERE game_id = ? AND is_fake = 1 AND is_active = 1
                            """, (game_id,))
                            result = cursor.fetchone()
                            current_fake_count = result['count'] if result else 0
                        
                        if current_fake_count == 0:
                            random_fake_count = self._get_random_fake_count()
                            await self._add_initial_fake_users(game_id, random_fake_count)
                    
                    logger.info(f"Recovered stuck game {game_id}")
        
        except Exception as e:
            logger.error(f"Error recovering stuck games: {e}")
    
    async def ensure_game_continuity(self):
        """Ensure game continues without interruption"""
        try:
            from database.db import Database
            
            # Get current game from system_state
            current_game = await self.get_current_game()
            
            if not current_game:
                # No current game, create one
                logger.info("No current game found, creating new game...")
                await self.start_new_round_game()
                return
            
            game_id = current_game.get('game_id')
            if not game_id:
                return
            
            # Check current state
            game = await Database.get_game(game_id)
            if not game:
                logger.error(f"Game {game_id} not found in database")
                await self.start_new_round_game()
                return
            
            status = game.get('status', 'card_purchase')
            phase = game.get('current_phase', 'card_purchase')
            
            # Initialize winner tracking if needed
            if game_id not in self.game_winners:
                self.game_winners[game_id] = []
            
            # Initialize state version if needed
            if game_id not in self._game_state_versions:
                self._game_state_versions[game_id] = 1
            
            # Initialize fake finalized flag if needed
            if game_id not in self._fake_players_finalized:
                self._fake_players_finalized[game_id] = False
            
            # ==================== NEW: Initialize final winner broadcast flag if needed ====================
            if game_id not in self._final_winner_broadcast_sent:
                self._final_winner_broadcast_sent[game_id] = False
            
            # NEW: Check for stuck active games
            if status == 'active' and phase == 'active':
                # Check if number caller is running
                try:
                    from utils.number_caller import number_caller
                    # FIX: Use safer method check
                    if hasattr(number_caller, 'is_calling_numbers_for_game'):
                        if not number_caller.is_calling_numbers_for_game(game_id):
                            logger.warning(f"Game {game_id} is active but number caller not running. Starting it with 4-second interval...")
                            await number_caller.start_number_calling_for_game(game_id)
                            
                            # Update last activity time
                            self._last_activity_times[game_id] = datetime.now()
                    else:
                        logger.warning(f"NumberCaller missing is_calling_numbers_for_game method. Starting number calling with 4-second interval...")
                        await number_caller.start_number_calling_for_game(game_id)
                        self._last_activity_times[game_id] = datetime.now()
                except Exception as e:
                    logger.error(f"Error checking number caller: {e}")
            
            # If game is completed, start new one
            if status == 'completed' or game_id in self._completed_games:
                logger.info(f"Game {game_id} is completed, starting new round")
                await self._schedule_next_round(game_id)
            
            # If game is stuck, recover it
            elif status == 'card_purchase' and phase == 'card_purchase':
                countdown = await Database.calculate_purchase_countdown(game_id)
                if countdown < -60:  # Stuck for more than 1 minute
                    logger.warning(f"Game {game_id} stuck for {abs(countdown)} seconds. Recovering...")
                    
                    # Check for real players
                    real_players = await Database.count_game_players(game_id)
                    if real_players > 0:
                        await self._refund_all_players(game_id)
                    
                    # Clean up fake users
                    self.fake_user_manager.cleanup_game(game_id)
                    
                    # Clear winners for this game
                    await self.clear_winners(game_id)
                    
                    # Clear fake finalized flag
                    if game_id in self._fake_players_finalized:
                        del self._fake_players_finalized[game_id]
                    
                    # ==================== NEW: Clear final winner broadcast flag ====================
                    if game_id in self._final_winner_broadcast_sent:
                        del self._final_winner_broadcast_sent[game_id]
                    
                    # Clean up caches
                    await self.cleanup_game_caches(game_id)
                    
                    await Database.force_reset_stuck_game(game_id)
                    async with self._lock:
                        self.active_game = await Database.get_game(game_id)
                        # Initialize winner tracking
                        if game_id not in self.game_winners:
                            self.game_winners[game_id] = []
                        
                        # Increment state version
                        self._game_state_versions[game_id] = self._game_state_versions.get(game_id, 0) + 1
                        
                        # Initialize fake finalized flag
                        if game_id not in self._fake_players_finalized:
                            self._fake_players_finalized[game_id] = False
                        
                        # ==================== NEW: Initialize final winner broadcast flag ====================
                        if game_id not in self._final_winner_broadcast_sent:
                            self._final_winner_broadcast_sent[game_id] = False
                    
                    # ==================== NEW: Add random fake users if needed ====================
                    if self.fake_users_enabled:
                        # Check if we need to add fake users
                        with Database.get_cursor() as cursor:
                            cursor.execute("""
                                SELECT COUNT(*) as count FROM player_cards 
                                WHERE game_id = ? AND is_fake = 1 AND is_active = 1
                            """, (game_id,))
                            result = cursor.fetchone()
                            current_fake_count = result['count'] if result else 0
                        
                        if current_fake_count == 0:
                            random_fake_count = self._get_random_fake_count()
                            await self._add_initial_fake_users(game_id, random_fake_count)
        
        except Exception as e:
            logger.error(f"Error ensuring game continuity: {e}")

    # ADDED: Debug method for testing bingo verification
    async def debug_verify_bingo(self, game_id: str, user_id: int):
        """Debug bingo verification"""
        try:
            from database.db import Database
            
            # Get user card
            user_card = await Database.get_user_card_in_game(user_id, game_id)
            if not user_card:
                return {"error": "No card found"}
            
            # Get called numbers
            called_numbers = await Database.get_drawn_numbers(game_id)
            
            # Verify bingo
            has_bingo, pattern, pattern_type = await self._fast_verify_bingo_with_pattern(user_card, called_numbers)
            
            # Also check grid positions for corners
            card_numbers = []
            try:
                if user_card.get('card_numbers'):
                    card_numbers_data = user_card['card_numbers']
                    if isinstance(card_numbers_data, str):
                        card_numbers = json.loads(card_numbers_data)
                    elif isinstance(card_numbers_data, list):
                        card_numbers = card_numbers_data
            except:
                pass
            
            # Get corner numbers if available
            corner_numbers = []
            if len(card_numbers) == 25:
                grid = [card_numbers[i:i+5] for i in range(0, 25, 5)]
                corners_positions = [(0, 0), (0, 4), (4, 0), (4, 4)]
                corner_numbers = [grid[row][col] for row, col in corners_positions]
            
            # Get winners count for this game
            winners_count = await self.get_winners_count(game_id)
            can_add = await self.can_add_winner(game_id)
            
            # Get fake player stats
            fake_count = len(self.fake_user_manager.game_fake_cards.get(game_id, {}))
            
            return {
                "has_bingo": has_bingo,
                "pattern": pattern,
                "pattern_type": pattern_type,
                "called_numbers": called_numbers,
                "card_data": user_card.get('card_data'),
                "card_numbers": user_card.get('card_numbers'),
                "corner_numbers": corner_numbers,
                "user_id": user_id,
                "game_id": game_id,
                "winners_count": winners_count,
                "can_add_winner": can_add,
                "max_winners": self.max_winners,
                "fake_players": {
                    "current": fake_count,
                    "min": self.min_fake_players,
                    "max": self.max_fake_players,
                    "finalized": self._fake_players_finalized.get(game_id, False)
                }
            }
        except Exception as e:
            logger.error(f"Debug error: {e}")
            return {"error": str(e)}

    # NEW: Optimized method for handling bingo claims
    async def handle_bingo_claim(self, game_id: str, user_id: int):
        """Handle bingo claim with ultra-fast verification and two winner support"""
        try:
            start_time = time.time()
            
            # First, do a quick validation
            from database.db import Database
            
            # Check if game is active
            game = await Database.get_game(game_id)
            if not game or game.get('status') != 'active':
                return {'success': False, 'message': 'Game is not active'}
            
            # Check if we can add another winner
            if not await self.can_add_winner(game_id):
                winners_count = await self.get_winners_count(game_id)
                return {
                    'success': False, 
                    'message': f'Game already has {winners_count}/{self.max_winners} winners'
                }
            
            # Check if user has a card
            user_card = await Database.get_user_card_in_game(user_id, game_id)
            if not user_card:
                return {'success': False, 'message': 'No card found'}
            
            # Get called numbers
            called_numbers = await Database.get_drawn_numbers(game_id)
            
            # Fast verification with 4 corners priority
            has_bingo, winning_pattern, pattern_type = await self._fast_verify_bingo_with_pattern(user_card, called_numbers)
            
            verification_time = (time.time() - start_time) * 1000
            
            if has_bingo:
                # Process immediately
                result = await self.process_winner(game_id, user_id)
                
                if result:
                    winners_count = await self.get_winners_count(game_id)
                    return {
                        'success': True,
                        'message': f'BINGO! Winner #{result.get("winner_number")} verified and processed',
                        'pattern_type': pattern_type,
                        'winning_pattern': winning_pattern,
                        'verification_time_ms': verification_time,
                        'total_time_ms': (time.time() - start_time) * 1000,
                        'winner_display_seconds': 10 if winners_count == 1 else 0,
                        'winner_number': result.get('winner_number'),
                        'total_winners': result.get('total_winners'),
                        'is_final': result.get('is_final', False)
                    }
                else:
                    return {'success': False, 'message': 'Failed to process winner'}
            else:
                return {
                    'success': False,
                    'message': 'No valid bingo pattern found',
                    'verification_time_ms': verification_time
                }
                
        except Exception as e:
            logger.error(f"Error handling bingo claim: {e}")
            return {'success': False, 'message': f'Error: {str(e)}'}
    
    # NEW: Immediate bingo claim handling for 4 corners priority
    async def handle_immediate_bingo_claim(self, game_id: str, user_id: int):
        """Handle bingo claim with immediate verification and processing (10-second display)"""
        try:
            from database.db import Database
            
            logger.info(f"🚨 IMMEDIATE BINGO CLAIM from user {user_id} in game {game_id}")
            
            # Get game status immediately
            game = await Database.get_game(game_id)
            if not game or game.get('status') != 'active':
                logger.warning(f"Game {game_id} not active for bingo claim")
                return None
            
            # Check if we can add another winner
            if not await self.can_add_winner(game_id):
                winners_count = await self.get_winners_count(game_id)
                logger.warning(f"Game {game_id} already has {winners_count}/{self.max_winners} winners")
                return None
            
            # Get user card
            user_card = await Database.get_user_card_in_game(user_id, game_id)
            if not user_card:
                logger.warning(f"User {user_id} has no card in game {game_id}")
                return None
            
            # Get called numbers
            called_numbers = await Database.get_drawn_numbers(game_id)
            
            # Fast verification with 4 corners priority
            has_bingo, winning_pattern, pattern_type = await self._fast_verify_bingo_with_pattern(user_card, called_numbers)
            
            if has_bingo:
                logger.info(f"✅ IMMEDIATE BINGO VERIFIED: User {user_id}, Pattern: {pattern_type}")
                
                # Note: process_winner already has its own _verification_lock
                # So we don't need to lock here to avoid deadlock
                # Double-check game is still active and we can add winner
                current_game = await Database.get_game(game_id)
                if current_game and current_game.get('status') == 'active' and await self.can_add_winner(game_id):
                    return await self.process_winner(game_id, user_id)
                else:
                    logger.warning(f"Game {game_id} no longer active or cannot add winner during processing")
                    return None
            else:
                logger.info(f"❌ No bingo found for user {user_id}")
                return None
                
        except Exception as e:
            logger.error(f"Error in immediate bingo claim: {e}")
            return None
    
    # NEW: Manual game recovery API method
    async def recover_stuck_game(self, game_id: str, admin_id: int):
        """Manually recover a stuck game (for admin API)"""
        try:
            # Verify admin
            from database.db import Database
            admin = await Database.get_admin_by_user_id(admin_id)
            if not admin:
                return {'success': False, 'message': 'Unauthorized'}
            
            # Get game
            game = await Database.get_game(game_id)
            if not game:
                return {'success': False, 'message': 'Game not found'}
            
            status = game.get('status', 'card_purchase')
            phase = game.get('current_phase', 'card_purchase')
            
            # Check if game is stuck in active phase
            if status == 'active' and phase == 'active':
                logger.info(f"Admin {admin_id} manually recovering stuck active game {game_id}")
                success = await self._recover_stuck_active_game(game_id)
                
                if success:
                    return {
                        'success': True,
                        'message': f'Game {game_id} recovery initiated',
                        'action': 'recovered_stuck_active_game'
                    }
                else:
                    return {
                        'success': False,
                        'message': f'Failed to recover game {game_id}'
                    }
            elif status == 'card_purchase' and phase == 'card_purchase':
                # Check countdown
                countdown = await Database.calculate_purchase_countdown(game_id)
                if countdown <= 0:
                    logger.info(f"Admin {admin_id} forcing game {game_id} to start")
                    
                    # Check players including fake users
                    real_players = await Database.count_game_players(game_id)
                    fake_count = len(self.fake_user_manager.game_fake_cards.get(game_id, {}))
                    total_players = real_players + fake_count
                    
                    if total_players >= self.min_players_to_start:
                        # Force start game
                        await self.start_game_play(game_id)
                        return {
                            'success': True,
                            'message': f'Game {game_id} forced to start',
                            'action': 'forced_game_start',
                            'real_players': real_players,
                            'fake_players': fake_count,
                            'total_players': total_players
                        }
                    else:
                        return {
                            'success': False,
                            'message': f'Not enough players ({total_players}/{self.min_players_to_start}) to start game'
                        }
                else:
                    return {
                        'success': False,
                        'message': f'Game {game_id} is still in countdown ({countdown}s remaining)'
                    }
            else:
                return {
                    'success': False,
                    'message': f'Game {game_id} is in {status}/{phase} state, not stuck'
                }
                
        except Exception as e:
            logger.error(f"Error in manual game recovery: {e}")
            return {'success': False, 'message': str(e)}

    async def _queue_commission_recovery(self, game_id: str):
        """Queue game commission for recovery if initial recording fails"""
        try:
            from database.db import Database
            
            with Database.get_cursor() as cursor:
                cursor.execute("""
                    INSERT OR REPLACE INTO pending_commissions 
                    (game_id, recovery_attempts, last_attempt, next_attempt, status)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    game_id,
                    1,  # First recovery attempt
                    datetime.now(),
                    datetime.now() + timedelta(minutes=5),  # Retry in 5 minutes
                    'pending'
                ))
            
            logger.warning(f"📝 Queued game {game_id} commission for recovery")
            
        except Exception as e:
            logger.error(f"Error queueing commission recovery: {e}")
    
    # NEW: Force completion of stuck winner display
    async def force_complete_winner_display(self, game_id: str):
        """Force complete a stuck winner display"""
        try:
            from database.db import Database
            from web_server import websocket_server
            
            logger.warning(f"🛠️ Force completing winner display for game {game_id}")
            
            # Check if game is in winner_display
            game = await Database.get_game(game_id)
            if not game or game.get('status') != 'winner_display':
                return {'success': False, 'message': 'Game not in winner_display'}
            
            # Mark game as completed
            await Database.update_game_status(game_id, 'completed')
            await Database.update_game_phase(game_id, 'completed')
            
            # Clean up fake users
            self.fake_user_manager.cleanup_game(game_id)
            
            # Clear winners for this game
            await self.clear_winners(game_id)
            
            # Clear fake finalized flag
            if game_id in self._fake_players_finalized:
                del self._fake_players_finalized[game_id]
            
            # ==================== NEW: Clear final winner broadcast flag ====================
            if game_id in self._final_winner_broadcast_sent:
                del self._final_winner_broadcast_sent[game_id]
            
            # Clean up caches
            await self.cleanup_game_caches(game_id)
            
            # Mark as completed in tracking set
            self._completed_games.add(game_id)
            
            # Clear active game
            async with self._lock:
                if self.active_game and self.active_game.get('game_id') == game_id:
                    self.active_game = None
            
            # Broadcast completion
            await self._safe_broadcast({
                'type': 'game_completed',
                'game_id': game_id,
                'message': 'Winner display force-completed by system',
                'timestamp': datetime.now().isoformat()
            }, game_id)
            
            # Start new round
            await self._schedule_next_round_after_winner_display(game_id)
            
            return {'success': True, 'message': f'Winner display force-completed for game {game_id}'}
            
        except Exception as e:
            logger.error(f"Error force completing winner display: {e}")
            return {'success': False, 'message': str(e)}

    async def force_complete_winner_display_immediately(self, game_id: str):
        """Force complete winner display immediately (for stuck games)"""
        try:
            from database.db import Database
            from web_server import websocket_server
            
            logger.warning(f"🛠️ FORCE COMPLETING winner display for game {game_id}")
            
            # Mark game as completed
            await Database.update_game_status(game_id, 'completed')
            await Database.update_game_phase(game_id, 'completed')
            
            # Clean up fake users
            self.fake_user_manager.cleanup_game(game_id)
            
            # Clear winners for this game
            await self.clear_winners(game_id)
            
            # Clear fake finalized flag
            if game_id in self._fake_players_finalized:
                del self._fake_players_finalized[game_id]
            
            # ==================== NEW: Clear final winner broadcast flag ====================
            if game_id in self._final_winner_broadcast_sent:
                del self._final_winner_broadcast_sent[game_id]
            
            # Clean up caches
            await self.cleanup_game_caches(game_id)
            
            # Mark as completed in tracking set
            self._completed_games.add(game_id)
            
            # Clear active game
            async with self._lock:
                if self.active_game and self.active_game.get('game_id') == game_id:
                    self.active_game = None
            
            # Broadcast completion
            await self._safe_broadcast({
                'type': 'game_completed',
                'game_id': game_id,
                'message': 'Game completed',
                'timestamp': datetime.now().isoformat()
            }, game_id)
            
            # Start new round IMMEDIATELY
            await self._schedule_next_round_after_winner_display(game_id)
            
            logger.info(f"✅ Winner display force-completed for game {game_id}, new game starting")
            return {'success': True, 'message': f'Winner display force-completed for game {game_id}'}
            
        except Exception as e:
            logger.error(f"Error force completing winner display: {e}")
            return {'success': False, 'message': str(e)}

    # ==================== NEW: Complete game state for client reconnection ====================
    
    async def get_complete_game_state(self, game_id: str, user_id: int = None):
        """Get complete game state for a client (for reconnection) - FIXED: Includes winner payouts"""
        try:
            from database.db import Database
            
            game = await Database.get_game(game_id)
            if not game:
                return {'success': False, 'message': 'Game not found'}
            
            # Get user's card if user_id provided
            user_card = None
            if user_id:
                user_card = await Database.get_user_card_in_game(user_id, game_id)
            
            # Get all called numbers
            called_numbers = await Database.get_drawn_numbers(game_id)
            
            # Get player counts (ONLY ACTIVE CARDS)
            with Database.get_cursor() as cursor:
                cursor.execute("""
                    SELECT 
                        COUNT(CASE WHEN is_fake = 0 AND is_active = 1 THEN 1 END) as real_players,
                        COUNT(CASE WHEN is_fake = 1 AND is_active = 1 THEN 1 END) as fake_players,
                        COUNT(CASE WHEN is_active = 1 THEN 1 END) as total_players
                    FROM player_cards 
                    WHERE game_id = ?
                """, (game_id,))
                row = cursor.fetchone()
                real_players = row['real_players'] if row else 0
                fake_players = row['fake_players'] if row else 0
                total_players = row['total_players'] if row else 0
            
            # Get winners
            winners = await self.get_winners(game_id)
            
            # Calculate payouts for winners
            payouts = []
            if winners:
                prize_pool = float(game.get('prize_pool', 0))
                payouts = await self.calculate_winner_payouts(game_id, prize_pool)
            
            # Format winners with payouts
            formatted_winners = []
            for i, winner in enumerate(winners):
                # Ensure winner has card numbers
                winner = await self._ensure_winner_card_numbers(game_id, winner)
                formatted_winner = winner.copy()
                formatted_winner['prize_amount'] = payouts[i] if i < len(payouts) else 0
                formatted_winners.append(formatted_winner)
            
            # Get countdown
            countdown = 0
            if game.get('current_phase') == 'card_purchase':
                countdown = await Database.calculate_purchase_countdown(game_id)
            elif game.get('current_phase') == 'winner_display':
                winner_display_end = game.get('winner_display_end')
                if winner_display_end:
                    if isinstance(winner_display_end, str):
                        try:
                            winner_display_end = datetime.fromisoformat(winner_display_end.replace('Z', '+00:00'))
                        except:
                            winner_display_end = datetime.fromisoformat(winner_display_end)
                    if winner_display_end > datetime.now():
                        countdown = (winner_display_end - datetime.now()).total_seconds()
            
            return {
                'success': True,
                'game_id': game_id,
                'round_number': game.get('round_number', 1),
                'game_phase': game.get('current_phase'),
                'game_status': game.get('status'),
                'countdown_remaining': max(0, int(countdown)),
                'prize_pool': float(game.get('prize_pool', 0)),
                'called_numbers': called_numbers,
                'real_players': real_players,
                'fake_players': fake_players,
                'total_players': total_players,
                'max_players': 400,
                'user_has_card': user_card is not None,
                'user_card': user_card,
                'winners': formatted_winners,  # Now includes prize_amount for each winner
                'winners_count': len(winners),
                'max_winners': self.max_winners,
                'min_fake_players': self.min_fake_players,
                'max_fake_players': self.max_fake_players,
                'fake_players_finalized': self._fake_players_finalized.get(game_id, False),
                'fake_users_enabled': self.fake_users_enabled,
                'game_completed': game_id in self._completed_games,
                'state_version': self._game_state_versions.get(game_id, 1),
                'timestamp': datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"Error getting complete game state: {e}")
            return {'success': False, 'message': str(e)}
    
    # ==================== NEW: Cache cleanup ====================
    
    async def cleanup_game_caches(self, game_id: str):
        """Clean up caches for a completed game"""
        try:
            if game_id in self._called_numbers_cache:
                del self._called_numbers_cache[game_id]
            if game_id in self._user_cards_cache:
                del self._user_cards_cache[game_id]
            if game_id in self._pattern_cache:
                del self._pattern_cache[game_id]
            if game_id in self._last_activity_times:
                del self._last_activity_times[game_id]
            if game_id in self._game_state_versions:
                del self._game_state_versions[game_id]
            if game_id in self._last_broadcast_times:
                keys_to_delete = [k for k in self._last_broadcast_times if game_id in k]
                for key in keys_to_delete:
                    del self._last_broadcast_times[key]
            if game_id in self._last_countdown_check:
                del self._last_countdown_check[game_id]
            if game_id in self._fake_players_finalized:
                del self._fake_players_finalized[game_id]
            if game_id in self._final_winner_broadcast_sent:
                del self._final_winner_broadcast_sent[game_id]
            logger.info(f"🧹 Cleaned up caches for game {game_id}")
        except Exception as e:
            logger.error(f"Error cleaning up caches: {e}")

    # ==================== INTEGRATION: Admin methods for fake users ====================
    
    async def set_fake_users_enabled(self, enabled: bool, admin_id: int):
        """Enable or disable fake users (admin only)"""
        try:
            from database.db import Database
            admin = await Database.get_admin_by_user_id(admin_id)
            if not admin:
                return {'success': False, 'message': 'Unauthorized'}
            
            self.fake_users_enabled = enabled
            logger.info(f"Admin {admin_id} {'enabled' if enabled else 'disabled'} fake users")
            
            # If enabled and we have an active game in card_purchase, add fake users
            if enabled and self.active_game:
                game_id = self.active_game.get('game_id')
                phase = self.active_game.get('current_phase', 'card_purchase')
                if phase == 'card_purchase' and not self._fake_players_finalized.get(game_id, False):
                    # Check if we already have fake users
                    with Database.get_cursor() as cursor:
                        cursor.execute("""
                            SELECT COUNT(*) as count FROM player_cards 
                            WHERE game_id = ? AND is_fake = 1 AND is_active = 1
                        """, (game_id,))
                        result = cursor.fetchone()
                        current_fake_count = result['count'] if result else 0
                    
                    if current_fake_count == 0:
                        random_fake_count = self._get_random_fake_count()
                        await self._add_initial_fake_users(game_id, random_fake_count)
                    
                    # Increment state version
                    if game_id in self._game_state_versions:
                        self._game_state_versions[game_id] += 1
            
            return {
                'success': True,
                'fake_users_enabled': self.fake_users_enabled,
                'min_fake_players': self.min_fake_players,
                'max_fake_players': self.max_fake_players,
                'message': f'Fake users {"enabled" if enabled else "disabled"}'
            }
        except Exception as e:
            logger.error(f"Error setting fake users enabled: {e}")
            return {'success': False, 'message': str(e)}
    
    async def set_fake_player_range(self, min_fake: int, max_fake: int, admin_id: int):
        """Set minimum and maximum fake players per game (admin only)"""
        try:
            from database.db import Database
            admin = await Database.get_admin_by_user_id(admin_id)
            if not admin:
                return {'success': False, 'message': 'Unauthorized'}
            
            if min_fake < 2:
                return {'success': False, 'message': 'Minimum fake players must be at least 2'}
            
            if max_fake < min_fake:
                return {'success': False, 'message': 'Maximum fake players must be greater than or equal to minimum'}
            
            if max_fake > 400:
                return {'success': False, 'message': 'Maximum fake players cannot exceed 400'}
            
            old_min = self.min_fake_players
            old_max = self.max_fake_players
            
            self.min_fake_players = min_fake
            self.max_fake_players = max_fake
            
            logger.info(f"Admin {admin_id} set fake player range: min={min_fake}, max={max_fake} (was: min={old_min}, max={old_max})")
            
            return {
                'success': True,
                'min_fake_players': self.min_fake_players,
                'max_fake_players': self.max_fake_players,
                'old_min_fake_players': old_min,
                'old_max_fake_players': old_max,
                'message': f'Fake player range set to min={min_fake}, max={max_fake}'
            }
        except Exception as e:
            logger.error(f"Error setting fake player range: {e}")
            return {'success': False, 'message': str(e)}
    
    async def set_auto_start_games(self, auto_start: bool, admin_id: int):
        """Set whether games should auto-start with fake players (admin only)"""
        try:
            from database.db import Database
            admin = await Database.get_admin_by_user_id(admin_id)
            if not admin:
                return {'success': False, 'message': 'Unauthorized'}
            
            self.auto_start_games = auto_start
            logger.info(f"Admin {admin_id} set auto-start games to {auto_start}")
            
            return {
                'success': True,
                'auto_start_games': self.auto_start_games,
                'message': f'Auto-start games {"enabled" if auto_start else "disabled"}'
            }
        except Exception as e:
            logger.error(f"Error setting auto-start games: {e}")
            return {'success': False, 'message': str(e)}
    
    async def get_fake_users_status(self):
        """Get fake users status"""
        try:
            active_fake_cards = {}
            for game_id, cards in self.fake_user_manager.game_fake_cards.items():
                active_fake_cards[game_id] = len(cards)
            
            # Get current game stats
            current_game_fake = 0
            current_game_real = 0
            current_game_total = 0
            current_game_finalized = False
            
            if self.active_game:
                game_id = self.active_game.get('game_id')
                current_game_fake = len(self.fake_user_manager.game_fake_cards.get(game_id, {}))
                from database.db import Database
                current_game_real = await Database.count_game_players(game_id)
                current_game_total = current_game_real + current_game_fake
                current_game_finalized = self._fake_players_finalized.get(game_id, False)
            
            return {
                'success': True,
                'fake_users_enabled': self.fake_users_enabled,
                'auto_start_games': self.auto_start_games,
                'min_fake_players': self.min_fake_players,
                'max_fake_players': self.max_fake_players,
                'min_players_to_start': self.min_players_to_start,
                'total_fake_users': len(self.fake_user_manager.fake_users),
                'active_fake_cards': active_fake_cards,
                'total_active_fake_cards': sum(active_fake_cards.values()),
                'current_game': {
                    'game_id': self.active_game.get('game_id') if self.active_game else None,
                    'fake_players': current_game_fake,
                    'real_players': current_game_real,
                    'total_players': current_game_total,
                    'fake_percentage': (current_game_fake / max(1, current_game_total)) * 100 if current_game_total > 0 else 0,
                    'fake_players_finalized': current_game_finalized,
                    'within_range': self.min_fake_players <= current_game_fake <= self.max_fake_players if not current_game_finalized else True
                }
            }
        except Exception as e:
            logger.error(f"Error getting fake users status: {e}")
            return {'success': False, 'message': str(e)}
    
    # ==================== DEBUG: Player counts verification ====================
    
    async def debug_player_counts(self, game_id: str):
        """Debug function to verify player counts - FIXED: Shows active vs inactive cards"""
        try:
            from database.db import Database
            
            logger.info(f"=== DEBUG PLAYER COUNTS for game {game_id} ===")
            
            # Get all cards from database with active/inactive breakdown
            with Database.get_cursor() as cursor:
                cursor.execute("""
                    SELECT 
                        COUNT(*) as total_cards,
                        SUM(CASE WHEN is_active = 1 THEN 1 ELSE 0 END) as active_cards,
                        SUM(CASE WHEN is_active = 0 THEN 1 ELSE 0 END) as inactive_cards,
                        SUM(CASE WHEN is_fake = 0 AND is_active = 1 THEN 1 ELSE 0 END) as real_active_cards,
                        SUM(CASE WHEN is_fake = 1 AND is_active = 1 THEN 1 ELSE 0 END) as fake_active_cards,
                        SUM(CASE WHEN is_fake = 0 AND is_active = 0 THEN 1 ELSE 0 END) as real_inactive_cards,
                        SUM(CASE WHEN is_fake = 1 AND is_active = 0 THEN 1 ELSE 0 END) as fake_inactive_cards
                    FROM player_cards 
                    WHERE game_id = ?
                """, (game_id,))
                row = cursor.fetchone()
                
                if row:
                    logger.info(f"📊 Database counts for game {game_id}:")
                    logger.info(f"  ├─ TOTAL CARDS: {row['total_cards']}")
                    logger.info(f"  ├─ ACTIVE CARDS: {row['active_cards']}")
                    logger.info(f"  │   ├─ Real active: {row['real_active_cards']}")
                    logger.info(f"  │   └─ Fake active: {row['fake_active_cards']}")
                    logger.info(f"  └─ INACTIVE CARDS: {row['inactive_cards']}")
                    logger.info(f"      ├─ Real inactive (refunded): {row['real_inactive_cards']}")
                    logger.info(f"      └─ Fake inactive: {row['fake_inactive_cards']}")
                
                # Get prize pool
                cursor.execute("SELECT prize_pool FROM games WHERE game_id = ?", (game_id,))
                game_row = cursor.fetchone()
                if game_row:
                    prize_pool = float(game_row['prize_pool'] or 0)
                    expected_cards_from_prize = prize_pool / 8 if prize_pool > 0 else 0
                    logger.info(f"💰 Prize pool: {prize_pool} birr")
                    logger.info(f"📈 Expected active cards from prize pool: {expected_cards_from_prize}")
                    
                    if row and abs(row['active_cards'] - expected_cards_from_prize) > 0.1:
                        logger.warning(f"⚠️ MISMATCH: Prize pool suggests {expected_cards_from_prize} active cards, but found {row['active_cards']}")
                
                # Get fake count from memory
                fake_memory = len(self.fake_user_manager.game_fake_cards.get(game_id, {}))
                logger.info(f"🎭 Fake cards in memory: {fake_memory}")
                
            logger.info("=" * 40)
            
            return {
                'success': True,
                'game_id': game_id,
                'total_cards': row['total_cards'] if row else 0,
                'active_cards': row['active_cards'] if row else 0,
                'real_active_cards': row['real_active_cards'] if row else 0,
                'fake_active_cards': row['fake_active_cards'] if row else 0,
                'inactive_cards': row['inactive_cards'] if row else 0,
                'real_inactive_cards': row['real_inactive_cards'] if row else 0,
                'prize_pool': prize_pool if 'prize_pool' in locals() else 0,
                'expected_cards_from_prize': expected_cards_from_prize if 'expected_cards_from_prize' in locals() else 0,
                'fake_cards_in_memory': fake_memory,
                'fake_players_finalized': self._fake_players_finalized.get(game_id, False)
            }
            
        except Exception as e:
            logger.error(f"Error in debug_player_counts: {e}", exc_info=True)
            return {'success': False, 'message': str(e)}

    # ==================== TWO WINNER SUPPORT: Admin methods for winner configuration ====================
    
    async def set_max_winners(self, max_winners: int, admin_id: int):
        """Set maximum number of winners per game (admin only)"""
        try:
            from database.db import Database
            admin = await Database.get_admin_by_user_id(admin_id)
            if not admin:
                return {'success': False, 'message': 'Unauthorized'}
            
            if max_winners < 1 or max_winners > 5:
                return {'success': False, 'message': 'Max winners must be between 1 and 5'}
            
            old_max = self.max_winners
            self.max_winners = max_winners
            logger.info(f"Admin {admin_id} changed max winners from {old_max} to {max_winners}")
            
            return {
                'success': True,
                'max_winners': self.max_winners,
                'old_max_winners': old_max,
                'message': f'Maximum winners per game set to {max_winners}'
            }
        except Exception as e:
            logger.error(f"Error setting max winners: {e}")
            return {'success': False, 'message': str(e)}
    
    async def get_winner_configuration(self):
        """Get winner configuration"""
        try:
            current_game_winners = 0
            if self.active_game:
                game_id = self.active_game.get('game_id')
                current_game_winners = len(self.game_winners.get(game_id, []))
            
            return {
                'success': True,
                'max_winners': self.max_winners,
                'current_game_winners': current_game_winners,
                'can_add_more': current_game_winners < self.max_winners
            }
        except Exception as e:
            logger.error(f"Error getting winner configuration: {e}")
            return {'success': False, 'message': str(e)}

    # ==================== NEW: Force game completion for admin reset ====================
    
    async def force_game_completion(self, game_id: str):
        """Force complete a game - for admin reset functionality"""
        try:
            from database.db import Database
            from utils.number_caller import number_caller
            
            logger.warning(f"🛠️ Force completing game {game_id}")
            
            # Stop number calling
            await number_caller.stop_number_calling_for_game(game_id)
            
            # Update game status
            await Database.update_game_status(game_id, 'completed')
            await Database.update_game_phase(game_id, 'completed')
            
            # Clean up fake users
            self.fake_user_manager.cleanup_game(game_id)
            
            # Clear winners for this game
            await self.clear_winners(game_id)
            
            # Clear fake finalized flag
            if game_id in self._fake_players_finalized:
                del self._fake_players_finalized[game_id]
            
            # Clear final winner broadcast flag
            if game_id in self._final_winner_broadcast_sent:
                del self._final_winner_broadcast_sent[game_id]
            
            # Clean up caches
            await self.cleanup_game_caches(game_id)
            
            # Mark as completed in tracking set
            self._completed_games.add(game_id)
            
            # Clear active game if this is the active one
            async with self._lock:
                if self.active_game and self.active_game.get('game_id') == game_id:
                    self.active_game = None
            
            logger.info(f"✅ Game {game_id} force completed")
            return True
            
        except Exception as e:
            logger.error(f"Error force completing game: {e}")
            return False

# Global instance of game manager
game_manager = GameManager()