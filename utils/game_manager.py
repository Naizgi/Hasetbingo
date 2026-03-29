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
# RANDOM FAKE PLAYERS: Random number between 60-70 per game (decided at game creation)
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
# ==================== FIXED: PROPER TRANSACTION HANDLING ====================
# Added synchronous transaction context manager for database operations
# Added thread pool executor for running sync DB operations in async context
# Fixed toggle_card_purchase to use transaction methods
# Fixed process_winner to use transaction for payment processing
# Added dedicated transaction methods for purchases, refunds, and commission
# ==================== FIXED: DATABASE SCHEMA COMPATIBILITY ====================
# Fixed _record_complete_game_details to use card_price from games table instead of price column
# Fixed _execute_purchase_transaction to handle missing price column gracefully
# Added fallback for databases without price column in player_cards table
# ==================== SINGLE CONTINUOUS GAME LOOP ====================
# Added continuous game loop that handles entire lifecycle:
# card_purchase → active → winner_display → reset and repeat
# Removed separate monitor tasks for countdowns, winner displays, and game continuity
# All game flow now controlled from a single while loop
# ==================== CRITICAL FIX: TRANSACTIONS.BALANCE_AFTER NOT NULL ERROR ====================
# Fixed _execute_purchase_transaction to update balance BEFORE getting new balance
# Fixed _execute_refund_transaction to update balance BEFORE recording transaction
# Fixed _process_winner_payment_transaction to update balance BEFORE recording transaction
# Fixed _record_transaction to use correct balance_after value
# ==================== OPTIMIZED: CARD PURCHASE PHASE TRANSITION ====================
# Optimized _run_card_purchase_phase to transition immediately after countdown
# Optimized _has_enough_players with single query for faster execution
# Added immediate phase change broadcast
# ==================== FIXED: CARD REFUND FUNCTIONALITY ====================
# Fixed _execute_refund_transaction to properly handle refund logic
# Added proper error handling and transaction management
# Ensured prize pool is correctly updated on refund
# ==================== FIXED: SQLite GREATEST FUNCTION COMPATIBILITY ====================
# Replaced GREATEST with MAX(0, prize_pool - ?) for SQLite compatibility
# ==================== FIXED: STATIC CARD SYSTEM ====================
# Added 400 pre-generated fixed cards that never change between games
# Card index 0-399 always have the same numbers in every game
# Modified _generate_bingo_card_numbers to use static data
# Modified _execute_purchase_transaction to use fixed cards
# Modified _add_initial_fake_users to use fixed cards
# ==================== FIXED: INSTANT GAME TRANSITION ====================
# Fixed _run_card_purchase_phase to transition IMMEDIATELY when countdown hits 0
# Removed any delay in checking players and transitioning
# Added synchronous phase change broadcast without awaiting
# ==================== ADDED: CONFIGURABLE FAKE PLAYER LIMITS ====================
# Added set_fake_player_range method to control min/max fake players from admin panel
# Fake player limits can now be configured dynamically without restart
# ==================== ADDED: PERIODIC STUCK GAME CHECKER ====================
# Added periodic checker that runs every 30 seconds to identify and recover stuck games
# Checks games in card_purchase, active, and winner_display phases
# Automatically refunds players in abandoned games
# Verifies number caller is running for active games
# ==================== FIXED: FAKE WINNER PROCESSING SYNCHRONOUS ====================
# Fake winners now processed synchronously with thread pool to prevent race conditions
# Added _execute_fake_winner_transaction for thread-safe DB operations
# Added _generate_fallback_pattern helper method
# ============================================================

import asyncio
import logging
import random
import json
from datetime import datetime, timedelta
from typing import Dict, List, Any
import time
import concurrent.futures
import functools
from database.db import Database
from utils.bingo_cards import bingo_cards

# ==================== IMPORT WEBSOCKET SERVER ====================
try:
    from web_server import websocket_server
except ImportError:
    logger = logging.getLogger(__name__)
    logger.warning("WebSocket server not available - broadcasts will fail")
    websocket_server = None

# ==================== INTEGRATION: Import FakeUserManager ====================
from database.db import Database
from utils.fake_users import fake_user_manager, FakeUserManager

logger = logging.getLogger(__name__)

# ==================== DATABASE TRANSACTION CONTEXT MANAGER ====================
class transaction:
    """Context manager for synchronous database transactions"""
    def __init__(self):
        from database.db import Database
        self.db = Database
        self.cursor = None
        self.conn = None
        
    def __enter__(self):
        from database.db import Database
        self.conn = Database.get_connection()
        self.cursor = self.conn.cursor()
        self.cursor.execute("BEGIN IMMEDIATE TRANSACTION")
        return self.cursor
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self.conn.commit()
        else:
            self.conn.rollback()
            logger.error(f"Transaction rolled back due to: {exc_val}")
        self.cursor.close()

class GameManager:
    """Manages game logic and coordination - SIMPLIFIED with single continuous loop"""
    
    def __init__(self):
        self.active_game = None
        self.is_initialized = False
        self._game_loop_task = None  # Single task for the entire game loop
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
        
        # ==================== NEW: RANDOM FAKE PLAYER RANGE (60-80) ====================
        # Random fake players between 60-80 per game - decided at game creation
        self.min_fake_players = 60  # Minimum fake players per game
        self.max_fake_players = 80  # Maximum fake players per game
        # No dynamic adjustments - once set, fake count is frozen
        
        # ==================== TWO WINNER SUPPORT: Track winners in current game ====================
        self.game_winners = {}  # game_id -> list of winner dicts
        self.max_winners = 2  # Maximum number of winners allowed per game
        self.winner_lock = asyncio.Lock()  # Lock for winner operations
        
        # ==================== GAME CONTINUITY: Auto-start games with fake players ====================
        self.auto_start_games = True  # Automatically start games with fake players
        self.game_continuity_task = None  # Background task for game continuity
        
        # ==================== NEW: Thread pool for sync database operations ====================
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)
        
        # ==================== FIXED: 400 Pre-generated static cards ====================
        self.fixed_cards = self._load_fixed_cards()
        
        # ==================== NEW: Stuck game checker task ====================
        self._stuck_game_checker = None

        self.INITIAL_DEPOSIT = 5
        
        logger.info(f"GameManager initialized with RANDOM FAKE PLAYERS ({self.min_fake_players}-{self.max_fake_players}) per game")
        logger.info(f"📇 Loaded {len(self.fixed_cards)} fixed cards for consistent gameplay")
    
    # ==================== FIXED: Load pre-generated cards (your provided data) ====================
    def _load_fixed_cards(self):
        """Load the 400 pre-generated fixed cards that never change between games"""
        # Your provided 400 cards data
        cards_data = bingo_cards
        
        # Create dictionary mapping card_index to card numbers
        fixed_cards = {}
        for i, card_numbers in enumerate(cards_data):
            fixed_cards[f"card_{i}"] = card_numbers
            
        return fixed_cards
    
    # ==================== SINGLE CONTINUOUS GAME LOOP ====================
    
    async def run_game_loop(self):
        """
        Single continuous game loop that handles the entire lifecycle:
        card_purchase → active → winner_display → reset and repeat
        """
        logger.info("🚀 Starting continuous game loop")
        
        while True:
            try:
                # Step 1: Create or get the current game
                game_id = await self._ensure_game_exists()
                
                if not game_id:
                    logger.error("Failed to create/get game, retrying in 5 seconds...")
                    await asyncio.sleep(5)
                    continue
                
                # Step 2: Run the CARD PURCHASE phase (30 seconds)
                # purchase_successful = await self._run_card_purchase_phase(game_id)
                
                # if not purchase_successful:
                #     logger.info(f"Purchase phase for game {game_id} was reset or interrupted")
                #     continue
                
                remaning_count_down = await Database.get_game_countdown(game_id)
                await asyncio.sleep(int(remaning_count_down))
                # Step 3: Check if we have enough players to start
                if not await self._has_enough_players(game_id):
                    logger.info(f"Game {game_id} doesn't have enough players, resetting countdown")
                    continue  # Go back to card purchase phase
                
                # Step 4: Run the ACTIVE GAME phase (number calling)
                game_ended_normally = await self._run_active_game_phase(game_id)
                
                # Step 5: If game ended normally (with winner), run winner display
                if game_ended_normally:
                    await self._run_winner_display_phase(game_id)
                else:
                    logger.warning(f"Game {game_id} ended without winners, resetting...")
                
                # Step 6: Clean up and reset for next game
                await self._reset_for_next_game(game_id)
                
                # Small pause before starting next game
                await asyncio.sleep(1)
                
            except asyncio.CancelledError:
                logger.info("Game loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in game loop: {e}", exc_info=True)
                # On error, wait a bit and try to recover
                await asyncio.sleep(5)
                
                # Try to clean up any stuck state
                try:
                    if self.active_game:
                        game_id = self.active_game.get('game_id')
                        if game_id:
                            await self._emergency_cleanup(game_id)
                except:
                    pass
        
        logger.info("🛑 Game loop ended")
    
    async def _ensure_game_exists(self):
        """Ensure there's a game in card_purchase phase, create if needed"""
        from database.db import Database
        
        # First check if there's already a game in card_purchase
        with Database.get_cursor() as cursor:
            cursor.execute("""
                SELECT game_id FROM games 
                WHERE status = 'card_purchase' AND current_phase = 'card_purchase'
                ORDER BY created_at DESC LIMIT 1
            """)
            existing = cursor.fetchone()
            
            if existing:
                game_id = existing['game_id']
                async with self._lock:
                    self.active_game = await Database.get_game(game_id)
                
                # Initialize tracking for this game
                await self._initialize_game_tracking(game_id)
                logger.info(f"Using existing game: {game_id}")
                return game_id
        
        # No existing game, create new one
        return await self._create_new_game()
    
    async def _create_new_game(self):
        """Create a new game with fake players"""
        from database.db import Database
        
        async with self._creation_lock:
            try:
                latest_round = await Database.get_latest_round_number()
                round_number = latest_round + 1
                
                current_time = datetime.now()
                countdown_end = current_time + timedelta(seconds=30)
                purchase_end_time = current_time + timedelta(seconds=30)
                
                game_id = await Database.create_new_round_game(
                    admin_id=0,
                    round_number=round_number,
                    status='card_purchase',
                    current_phase='card_purchase',
                    countdown_end=countdown_end,
                    purchase_end_time=purchase_end_time
                )
                
                if game_id:
                    async with self._lock:
                        self.active_game = await Database.get_game(game_id)
                    
                    # Initialize tracking
                    await self._initialize_game_tracking(game_id)
                    #added new task
                    self.purchase_successful_task = asyncio.create_task(self._run_card_purchase_phase(game_id))
                    # Add fake players immediately
                    if self.fake_users_enabled:
                        random_fake_count = random.randint(self.min_fake_players, self.max_fake_players)
                        logger.info(f"🎲 Adding {random_fake_count} fake players to new game {game_id}")
                        await self._add_initial_fake_users(game_id, random_fake_count)
                    #awaiting task
                    await self.purchase_successful_task
                    # Broadcast new game
                    await self._safe_broadcast({
                        'type': 'new_game_started',
                        'game_id': game_id,
                        'round_number': round_number,
                        'status': 'card_purchase',
                        'phase': 'card_purchase',
                        'countdown_seconds': 0,
                        'max_winners': self.max_winners,
                        'timestamp': datetime.now().isoformat()
                    }, game_id)
                    
                    logger.info(f"✅ Created NEW game: {game_id} (Round {round_number})")
                    return game_id
                
                return None
                
            except Exception as e:
                logger.error(f"Error creating new game: {e}")
                return None
    
    async def _initialize_game_tracking(self, game_id: str):
        """Initialize all tracking structures for a game"""
        if game_id not in self.game_winners:
            self.game_winners[game_id] = []
        
        if game_id not in self._game_state_versions:
            self._game_state_versions[game_id] = 1
        
        if game_id not in self._fake_players_finalized:
            self._fake_players_finalized[game_id] = False
        
        if game_id not in self._final_winner_broadcast_sent:
            self._final_winner_broadcast_sent[game_id] = False
    
    async def _run_card_purchase_phase(self, game_id: str) -> bool:
        """Run the card purchase phase with countdown - OPTIMIZED for instant transition"""
        from database.db import Database
        
        logger.info(f"🔄 Starting CARD PURCHASE phase for game {game_id}")
        
        # Broadcast phase start
        await self._safe_broadcast({
            'type': 'phase_started',
            'game_id': game_id,
            'phase': 'card_purchase',
            'duration': 30,
            'timestamp': datetime.now().isoformat()
        }, game_id)
        
        # Countdown from 30 to 0 - ensure we reach 0 exactly
        for seconds_remaining in range(30, 0, -1):
            # Update countdown in database
            start_time = time.time()
            await Database.update_game_countdown(game_id, seconds_remaining)
                
            await self._safe_broadcast({
                'type': 'countdown_update',
                'game_id': game_id,
                'phase': 'card_purchase',
                'seconds_remaining': seconds_remaining,
                'timestamp': datetime.now().isoformat()
            }, game_id)
            end_time = time.time()
            if seconds_remaining > 0:
                await asyncio.sleep(1-max(end_time-start_time, 0))
        
        logger.info(f"⏰ Card purchase phase ended for game {game_id}")
        
        # FIXED: IMMEDIATELY check players and transition - NO DELAY
        # Call has_enough_players which will update game state and broadcast
        # has_players = await self._has_enough_players(game_id)
        
        # if has_players:
        #     logger.info(f"✅ Game {game_id} transitioned to active phase INSTANTLY")
        #     return True
        # else:
        #     logger.info(f"⚠️ Game {game_id} not enough players, resetting countdown")
        #     return False
        return True

    async def _has_enough_players(self, game_id: str) -> bool:
        """Check if game has enough players to start - OPTIMIZED with single query"""
        from database.db import Database
        # Single optimized query to get all counts at once
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
            
            # Calculate and update prize pool in the same query
            final_prize_pool = total_players * 8.00
            cursor.execute("""
                UPDATE games SET prize_pool = ? WHERE game_id = ?
            """, (final_prize_pool, game_id))
        
        logger.info(f"📊 FINAL counts for game {game_id}: Real={real_players}, Fake={fake_players}, Total={total_players}, Prize={final_prize_pool}")
        
        # Check if we have enough players
        if total_players >= 2:
            # Immediately update game to active phase
            await Database.update_game_phase(game_id, 'active')
            await Database.update_game_status(game_id, 'active')
            await Database.update_game_start_time(game_id)
            
            # Update local cache
            async with self._lock:
                self.active_game = await Database.get_game(game_id)
            
            # Initialize winner tracking if needed
            if game_id not in self.game_winners:
                self.game_winners[game_id] = []
            
            # Increment state version
            self._game_state_versions[game_id] = self._game_state_versions.get(game_id, 0) + 1
            
            # Broadcast phase change immediately - don't await to avoid delay
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
            
            # Start number calling for this game immediately (don't wait)
            # from utils.number_caller import number_caller
            # asyncio.create_task(number_caller.start_number_calling_for_game(game_id))
            
            logger.info(f"✅ Game {game_id} transitioned to active phase with {total_players} players")
            return True
        else:
            logger.info(f"Game {game_id} has only {total_players} active player(s). Need at least 2.")
            
            # Reset purchase phase
            new_end_time = datetime.now() + timedelta(seconds=30)
            await Database.set_purchase_end_time(game_id, new_end_time)
            await Database.update_game_countdown(game_id, 30)
            
            # Broadcast reset
            await self._safe_broadcast({
                'type': 'countdown_reset',
                'game_id': game_id,
                'message': 'Need at least 2 active players to start. Countdown reset to 30 seconds.',
                'new_countdown': 30,
                'timestamp': datetime.now().isoformat()
            }, game_id)
            
            return False
    
    async def _run_active_game_phase(self, game_id: str) -> bool:
        """
        Run the active game phase (number calling)
        Returns: True if game ended with winner(s), False if error/forced end
        """
        from utils.number_caller import number_caller
        logger.info(f"🎯 Starting ACTIVE GAME phase for game {game_id}")
        # Update game to active phase
        await Database.update_game_phase(game_id, 'active')
        await Database.update_game_status(game_id, 'active')
        await Database.update_game_start_time(game_id)
        
        # Update local cache
        async with self._lock:
            self.active_game = await Database.get_game(game_id)
        
        # Initialize winner tracking if needed
        if game_id not in self.game_winners:
            self.game_winners[game_id] = []
        
        # Increment state version
        self._game_state_versions[game_id] = self._game_state_versions.get(game_id, 0) + 1
        
        # Broadcast phase change
        await self._broadcast_full_game_state(game_id)
        
        # Start number calling (this runs in background)
        await number_caller.start_number_calling_for_game(game_id)
        
        # Monitor the game until it ends
        game_active = True
        last_winner_count = 0
        
        while game_active:
            # Check if we've reached max winners
            winners_count = await self.get_winners_count(game_id)
            
            #changed to self.max_winners to 1
            max_winners = 1
            if winners_count >= max_winners:
                logger.info(f"🏆 Game {game_id} reached max winners ({max_winners})")
                game_active = False
                break
            
            # Check if game has been active too long (timeout)
            game = await Database.get_game(game_id)
            game_start_time = game.get('started_at')
            if game_start_time:
                # Parse datetime
                if isinstance(game_start_time, str):
                    try:
                        game_start_time = datetime.fromisoformat(game_start_time.replace('Z', '+00:00'))
                    except:
                        game_start_time = datetime.now()
                
                time_active = (datetime.now() - game_start_time).total_seconds()
                if time_active > 304:  # (75*4)+4 minutes timeout
                    logger.warning(f"Game {game_id} active for {time_active:.0f}s, forcing end")
                    game_active = False
                    break
            
            # Check if number caller is still running
            try:
                if hasattr(number_caller, 'is_calling_numbers_for_game'):
                    if not number_caller.is_calling_numbers_for_game(game_id):
                        logger.warning(f"Number caller stopped for game {game_id}")
                        game_active = False
                        break
            except:
                pass
            
            # If winners count changed, broadcast update
            # if winners_count != last_winner_count:
            #     await self._broadcast_full_game_state(game_id)
            #     last_winner_count = winners_count
            
            # Wait before next check
            await asyncio.sleep(0.5)
        
        # Stop number calling
        await number_caller.stop_number_calling_for_game(game_id)
        
        # Check if we actually had any winners
        final_winners_count = await self.get_winners_count(game_id)
        if final_winners_count == 0:
            logger.warning(f"Game {game_id} ended with no winners")
            return False
        
        return True
    
    async def _run_winner_display_phase(self, game_id: str):
        """Run the winner display phase for 10 seconds"""
        from database.db import Database
        
        logger.info(f"🏆 Starting WINNER DISPLAY phase for game {game_id}")
        
        # Set winner display end time
        winner_display_duration = 10
        winner_display_end = datetime.now() + timedelta(seconds=winner_display_duration)
        
        # Update game status
        await Database.update_game_status(game_id, 'winner_display')
        await Database.update_game_phase(game_id, 'winner_display')
        await Database.set_winner_display_end(game_id, winner_display_end)
        
        # Update local cache
        async with self._lock:
            self.active_game = await Database.get_game(game_id)
        
        # Broadcast winner announcement (if not already broadcast)
        # await self._broadcast_winners_if_needed(game_id)
        
        # Countdown from 10 to 0
        for seconds_remaining in range(10, -1, -1):
            await self._safe_broadcast({
                'type': 'winner_display_countdown',
                'game_id': game_id,
                'seconds_remaining': seconds_remaining,
                'timestamp': datetime.now().isoformat()
            }, game_id)
            
            if seconds_remaining > 0:
                await asyncio.sleep(1)
        
        logger.info(f"✅ Winner display completed for game {game_id}")
    
    async def _broadcast_winners_if_needed(self, game_id: str):
        """Broadcast winner data if not already sent"""
        if self._final_winner_broadcast_sent.get(game_id, False):
            return
        
        from database.db import Database
        from web_server import websocket_server
        
        # Get game details
        game = await Database.get_game(game_id)
        prize_pool = float(game.get('prize_pool', 0))
        
        # Get winners and payouts
        all_winners = await self.get_winners(game_id)
        payouts = await self.calculate_winner_payouts(game_id, prize_pool)
        
        # Prepare complete winners data
        complete_winners_data = []
        for i, w in enumerate(all_winners):
            w = await self._ensure_winner_card_numbers(game_id, w)
            
            winner_complete = {
                'user_id': w.get('user_id'),
                'username': w.get('username'),
                'full_name': w.get('full_name'),
                'card_index': w.get('card_index'),
                'card_numbers': w.get('card_numbers', []),
                'winning_pattern': w.get('winning_pattern', []),
                'pattern_type': w.get('pattern_type', 'BINGO'),
                'prize_amount': payouts[i] if i < len(payouts) else 0,
                'is_fake': w.get('is_fake', False),
                'winner_number': i + 1
            }
            complete_winners_data.append(winner_complete)
        
        # Broadcast winner announcement
        final_winner_data = {
            'type': 'winner_confirmed',
            'game_id': game_id,
            'prize_pool': prize_pool,
            'max_winners': self.max_winners,
            'total_winners': len(all_winners),
            'is_final_winner': True,
            'winners': complete_winners_data,
            'timestamp': datetime.now().isoformat(),
            'display_duration': 10
        }
        
        try:
            await websocket_server.broadcast_with_retry(final_winner_data)
            logger.info(f"📢 Broadcast winner announcement for {len(all_winners)} winners")
            self._final_winner_broadcast_sent[game_id] = True
        except Exception as e:
            logger.error(f"Failed to broadcast winner data: {e}")
    
    async def _reset_for_next_game(self, completed_game_id: str):
        """Clean up completed game and prepare for next"""
        from database.db import Database
        
        logger.info(f"🧹 Cleaning up game {completed_game_id} for next round")
        
        # Record commission and game details
        await self._record_game_commission(completed_game_id)
        
        # Update game status to completed
        await Database.update_game_status(completed_game_id, 'completed')
        await Database.update_game_phase(completed_game_id, 'completed')
        
        # Clean up fake users
        self.fake_user_manager.cleanup_game(completed_game_id)
        
        # Clear winners for this game
        await self.clear_winners(completed_game_id)
        
        # Clean up caches
        await self._cleanup_game_caches(completed_game_id)
        
        # Mark as completed in tracking set
        self._completed_games.add(completed_game_id)
        
        # Clear active game reference
        async with self._lock:
            if self.active_game and self.active_game.get('game_id') == completed_game_id:
                self.active_game = None
        
        # Broadcast game completion
        await self._safe_broadcast({
            'type': 'game_completed',
            'game_id': completed_game_id,
            'message': 'Game completed, preparing next round...',
            'timestamp': datetime.now().isoformat()
        }, completed_game_id)
        
        logger.info(f"✅ Game {completed_game_id} cleaned up, ready for next round")
    
    async def _emergency_cleanup(self, game_id: str):
        """Emergency cleanup for stuck games"""
        from database.db import Database
        from utils.number_caller import number_caller
        
        logger.warning(f"🚨 Emergency cleanup for game {game_id}")
        
        # Stop number calling
        await number_caller.stop_number_calling_for_game(game_id)
        
        # Force game to completed
        await Database.update_game_status(game_id, 'completed')
        await Database.update_game_phase(game_id, 'completed')
        
        # Clean up all resources
        self.fake_user_manager.cleanup_game(game_id)
        await self.clear_winners(game_id)
        await self._cleanup_game_caches(game_id)
        
        # Remove from tracking
        if game_id in self._fake_players_finalized:
            del self._fake_players_finalized[game_id]
        if game_id in self._final_winner_broadcast_sent:
            del self._final_winner_broadcast_sent[game_id]
        
        self._completed_games.add(game_id)
        
        # Clear active game
        async with self._lock:
            if self.active_game and self.active_game.get('game_id') == game_id:
                self.active_game = None
    
    async def _cleanup_game_caches(self, game_id: str):
        """Clean up caches for a completed game"""
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
        if game_id in self._fake_players_finalized:
            del self._fake_players_finalized[game_id]
        if game_id in self._final_winner_broadcast_sent:
            del self._final_winner_broadcast_sent[game_id]
        
        # Clean up broadcast timers
        keys_to_delete = [k for k in self._last_broadcast_times if game_id in k]
        for key in keys_to_delete:
            del self._last_broadcast_times[key]
    
    async def _run_in_transaction(self, func, *args, **kwargs):
        """Run a synchronous database operation in a transaction using thread pool"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._executor,
            functools.partial(func, *args, **kwargs)
        )
    
    # ==================== FIXED: SAFE BROADCAST HELPER - SENDS TO ALL CLIENTS SIMULTANEOUSLY ====================
    async def _safe_broadcast(self, message: dict, game_id: str = None):
        """
        Safely triggers a simultaneous broadcast to all clients.
        """
        if not websocket_server:
            logger.debug("WebSocket server not available, broadcast skipped")
            return

        if 'timestamp' not in message:
            message['timestamp'] = datetime.now().isoformat()
     
        if game_id:
            current_time = time.time()
            # Update tracking for debugging
            self._last_broadcast_times[f"{game_id}_{message.get('type', 'unknown')}"] = current_time

        try:
            # We now await the gathered broadcast
            await websocket_server.broadcast_with_retry(message)
        
            # Log critical game events
            if message.get('type') in ['winner_confirmed', 'phase_change_confirmed']:
                logger.info(f"📢 GATHERED BROADCAST SUCCESS: {message.get('type')} for game {game_id}")
            
        except Exception as e:
            logger.error(f"Failed to initiate gathered broadcast: {e}")
    
    # ==================== NEW: Get random fake player count for a game ====================
    def _get_random_fake_count(self) -> int:
        """Generate random number of fake players between min_fake_players and max_fake_players"""
        return random.randint(self.min_fake_players, self.max_fake_players)
    
    # ==================== NEW: Periodic stuck game checker ====================
    
    async def _check_for_stuck_games_periodically(self):
        """
        Periodically check for stuck games and recover them.
        This runs as a background task alongside the main game loop.
        """
        while True:
            try:
                await asyncio.sleep(30)  # Check every 30 seconds
                
                from database.db import Database
                
                # Get all non-completed games
                with Database.get_cursor() as cursor:
                    cursor.execute("""
                        SELECT game_id, status, current_phase, created_at, started_at, completed_at
                        FROM games 
                        WHERE status NOT IN ('completed', 'archived')
                        ORDER BY created_at DESC
                    """)
                    rows = cursor.fetchall()
                
                for game in rows:
                    game_id = game['game_id']
                    status = game['status']
                    phase = game['current_phase']
                    created_at = game['created_at']
                    
                    # Skip the active game (let main loop handle it)
                    if self.active_game and self.active_game.get('game_id') == game_id:
                        continue
                    
                    # Check for games stuck in card_purchase for too long
                    if status == 'card_purchase' and phase == 'card_purchase':
                        if created_at:
                            # Parse datetime
                            if isinstance(created_at, str):
                                try:
                                    created_time = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                                except:
                                    created_time = datetime.now()
                            else:
                                created_time = created_at
                            
                            age_minutes = (datetime.now() - created_time).total_seconds() / 60
                            
                            if age_minutes > 5:  # Stuck for more than 5 minutes
                                logger.warning(f"Found abandoned game {game_id} in card_purchase for {age_minutes:.1f} minutes")
                                
                                # Check if it has any active players
                                cursor.execute("""
                                    SELECT COUNT(*) as count FROM player_cards 
                                    WHERE game_id = ? AND is_active = 1
                                """, (game_id,))
                                player_count = cursor.fetchone()['count'] or 0
                                
                                if player_count == 0:
                                    # No players, safe to delete or mark as completed
                                    logger.info(f"Game {game_id} has no players, marking as completed")
                                    await Database.update_game_status(game_id, 'completed')
                                    await Database.update_game_phase(game_id, 'completed')
                                else:
                                    # Has players, need to refund them
                                    logger.warning(f"Game {game_id} has {player_count} players but is abandoned. Refunding...")
                                    await self._refund_all_players(game_id)
                                    await Database.update_game_status(game_id, 'completed')
                                    await Database.update_game_phase(game_id, 'completed')
                    
                    # Check for games stuck in active phase with no number caller
                    elif status == 'active' and phase == 'active':
                        started_at = game.get('started_at')
                        if started_at:
                            # Parse datetime
                            if isinstance(started_at, str):
                                try:
                                    start_time = datetime.fromisoformat(started_at.replace('Z', '+00:00'))
                                except:
                                    start_time = datetime.now()
                            else:
                                start_time = started_at
                            
                            active_duration = (datetime.now() - start_time).total_seconds()
                            
                            if active_duration > 180:  # Active for more than 3 minutes
                                logger.warning(f"Game {game_id} active for {active_duration:.0f}s with no winners")
                                
                                # Check if number caller is still running
                                from utils.number_caller import number_caller
                                try:
                                    is_calling = number_caller.is_calling_numbers_for_game(game_id)
                                    if not is_calling:
                                        logger.warning(f"Number caller not running for game {game_id}, forcing completion")
                                        await self.force_game_completion(game_id)
                                except:
                                    # If we can't check, assume it's stuck
                                    await self.force_game_completion(game_id)
                    
                    # Check for games stuck in winner display for too long
                    elif status == 'winner_display' and phase == 'winner_display':
                        completed_at = game.get('completed_at')
                        if completed_at:
                            # Parse datetime
                            if isinstance(completed_at, str):
                                try:
                                    complete_time = datetime.fromisoformat(completed_at.replace('Z', '+00:00'))
                                except:
                                    complete_time = datetime.now()
                            else:
                                complete_time = completed_at
                            
                            display_duration = (datetime.now() - complete_time).total_seconds()
                            
                            if display_duration > 20:  # Winner display for more than 20 seconds
                                logger.warning(f"Game {game_id} in winner display for {display_duration:.0f}s, forcing completion")
                                await Database.update_game_status(game_id, 'completed')
                                await Database.update_game_phase(game_id, 'completed')
            
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in periodic stuck game check: {e}")
    
    async def initialize(self):
        """Initialize the game manager and start the single game loop"""
        if self._initialization_complete:
            logger.info("GameManager already initialized")
            return True
            
        async with self._creation_lock:
            if self._initialization_complete:
                return True
                
            try:
                from database.db import Database
                
                # Initialize database
                await Database.init_db()
                await Database.migrate_db()
                
                # FIX: Get active game with proper locking
                async with self._lock:
                    self.active_game = await Database.get_active_round_game()
                
                # CRITICAL FIX: Check for any stuck games in card_purchase phase
                await self._recover_abandoned_games()
                
                # Start the single continuous game loop
                self._game_loop_task = asyncio.create_task(self.run_game_loop())
                
                # Start periodic stuck game checker
                self._stuck_game_checker = asyncio.create_task(self._check_for_stuck_games_periodically())
                
                self.is_initialized = True
                self._initialization_complete = True
                logger.info("GameManager initialized with continuous game loop and stuck game checker")
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
            
            # wait 1 second before claiming
            if len(fake_winners)>0:
                await asyncio.sleep(1.6)
            # Process any fake winners with error handling - NOW SYNCHRONOUS
            for fake_card, pattern_type in fake_winners:
                user_id = fake_card['user_id']
                logger.info(f"🎭 FAKE WINNER: User {user_id} got BINGO with pattern: {pattern_type}")
                
                # Process fake winner SYNCHRONOUSLY (not in background) with lock
                try:
                    # This will now run with proper locking and thread pool
                    await self.process_fake_winner(game_id, user_id, fake_card, pattern_type)
                except Exception as e:
                    logger.error(f"Failed to process fake winner: {e}")
            
            return len(fake_winners)
            
        except Exception as e:
            logger.error(f"Error marking number on all cards: {e}")
            return 0
    
    # ==================== NEW: Synchronous fake winner transaction ====================
    
    def _execute_fake_winner_transaction(self, game_id: str, user_id: int, fake_card: Dict, pattern_type: str) -> dict:
        """
        Synchronous version of process_fake_winner that runs in thread pool
        to prevent race conditions with process_winner
        """
        from database.db import Database
        import json
        from datetime import datetime

        try:
            logger.info(f"🎭 [SYNC] Processing fake winner transaction: User {user_id} in game {game_id}")
        
            with transaction() as cursor:
                # Get game details
                cursor.execute("SELECT * FROM games WHERE game_id = ?", (game_id,))
                game_row = cursor.fetchone()
                if not game_row:
                    return {'success': False, 'error': 'Game not found'}
                
                # Convert row to dict for easier access
                game = dict(game_row)
                
                # Get prize pool
                prize_pool = float(game.get('prize_pool', 0.00))
                if prize_pool <= 0:
                    return {'success': False, 'error': 'No prize pool'}
                
                # Count real players
                cursor.execute("""
                    SELECT COUNT(*) as real_players
                    FROM player_cards 
                    WHERE game_id = ? AND is_fake = 0 AND is_active = 1
                """, (game_id,))
                real_players_row = cursor.fetchone()
                real_players = real_players_row['real_players'] if real_players_row else 0
                
                # Extract card numbers
                card_numbers = []
                try:
                    if isinstance(fake_card.get('card_numbers'), str):
                        card_numbers = json.loads(fake_card['card_numbers'])
                    else:
                        card_numbers = fake_card.get('card_numbers', [])
                except:
                    card_numbers = []
                
                # Get called numbers
                cursor.execute("""
                    SELECT called_numbers FROM games 
                    WHERE game_id = ?
                """, (game_id,))
                called_rows = cursor.fetchone()
                called_numbers = json.loads(called_rows[0]) if called_rows and called_rows[0] else []
                
                # Create winner data base (without username/fullname which we'll add in async part)
                winner_data = {
                    'user_id': user_id,
                    'card_index': fake_card.get('card_index'),
                    'card_numbers': card_numbers,
                    'pattern_type': pattern_type,
                    'is_fake': True,
                    'timestamp': datetime.now().isoformat()
                }
                
                return {
                    'success': True,
                    'game': game,
                    'real_players': real_players,
                    'card_numbers': card_numbers,
                    'winner_data': winner_data,
                    'called_numbers': called_numbers,
                    'prize_pool': prize_pool
                }
                
        except Exception as e:
            logger.error(f"Error in sync fake winner transaction: {e}", exc_info=True)
            return {'success': False, 'error': str(e)}
    
    # ==================== NEW: Generate fallback pattern ====================
    
    def _generate_fallback_pattern(self, card_numbers, pattern_type):
        """Generate fallback pattern when verification fails"""
        winning_pattern = []
    
        if not card_numbers or len(card_numbers) < 25:
            return []
    
        if pattern_type == "four_corners":
            winning_pattern = [card_numbers[0], card_numbers[4], card_numbers[20], card_numbers[24]]
            winning_pattern = [num for num in winning_pattern if num != 0]
    
        elif pattern_type.startswith("row_"):
            try:
                row_num = int(pattern_type.split("_")[1])
                if 0 <= row_num <= 4:
                    start_idx = row_num * 5
                    winning_pattern = card_numbers[start_idx:start_idx+5]
                    winning_pattern = [num for num in winning_pattern if num != 0]
            except:
                pass
    
        elif pattern_type.startswith("column_"):
            try:
                col_num = int(pattern_type.split("_")[1])
                if 0 <= col_num <= 4:
                    indices = [col_num + (i*5) for i in range(5)]
                    winning_pattern = [card_numbers[i] for i in indices]
                    winning_pattern = [num for num in winning_pattern if num != 0]
            except:
                pass
    
        elif pattern_type == "main_diagonal":
            indices = [i*5 + i for i in range(5)]
            winning_pattern = [card_numbers[i] for i in indices]
            winning_pattern = [num for num in winning_pattern if num != 0]
    
        elif pattern_type == "anti_diagonal":
            indices = [i*5 + (4-i) for i in range(5)]
            winning_pattern = [card_numbers[i] for i in indices]
            winning_pattern = [num for num in winning_pattern if num != 0]
    
        return winning_pattern
    
    # ==================== FIXED: Fake winner processing with money going to house ====================
    async def process_fake_winner(self, game_id: str, user_id: int, fake_card: Dict, pattern_type: str):
        """
        Process a fake winner - NOW RUNS SYNCHRONOUSLY with thread pool to prevent race conditions
        Supports 2-winner system with real/fake combinations
        """
        try:
            # First, acquire the verification lock to prevent race conditions with real winners
            async with self._verification_lock:
                logger.info(f"🎭 Processing fake winner with lock: User {user_id} in game {game_id} with pattern {pattern_type}")
                
                # Check if we can add another winner (respects 2-winner limit)
                if not await self.can_add_winner(game_id):
                    logger.info(f"Game {game_id} already has maximum winners (2), cannot add fake winner")
                    return None
                
                # Get game details
                game = await Database.get_game(game_id)
                if not game:
                    logger.error(f"Game {game_id} not found for fake winner")
                    return None
                
                game_status = game.get('status', 'card_purchase')
                winners_count_before = await self.get_winners_count(game_id)
                logger.info(f"Current winners before adding: {winners_count_before}/2")
                
                # Stop number calling on first winner only
                if winners_count_before == 0 and game_status != 'winner_display':
                    from utils.number_caller import number_caller
                    await number_caller.stop_number_calling_for_game(game_id)
                    logger.info(f"Stopped number calling for game {game_id} (first winner)")
                
                # # Get called numbers for verification
                called_numbers = await Database.get_drawn_numbers(game_id)
                
                # # Extract card numbers for verification
                card_numbers_for_verify = []
                try:
                    if isinstance(fake_card.get('card_numbers'), str):
                        card_numbers_for_verify = json.loads(fake_card['card_numbers'])
                    else:
                        card_numbers_for_verify = fake_card.get('card_numbers', [])
                except:
                    card_numbers_for_verify = []
                
                # Verify the bingo pattern
                has_bingo, verified_pattern, verified_type = await self._fast_verify_bingo_with_pattern(
                    {'card_numbers': json.dumps(card_numbers_for_verify) if isinstance(card_numbers_for_verify, list) else str(card_numbers_for_verify)}, 
                    called_numbers
                )
                
                if not has_bingo:
                    logger.warning(f"⚠️ Fake winner pattern verification failed for user {user_id}, using provided pattern {pattern_type}")
                else:
                    pattern_type = verified_type  # Use verified pattern type
                
                # Run the synchronous transaction in thread pool for DB operations
                result = await self._run_in_transaction(
                    self._execute_fake_winner_transaction,
                    game_id, user_id, fake_card, pattern_type
                )
                
                if not result.get('success'):
                    logger.error(f"Fake winner transaction failed: {result.get('error')}")
                    return None
                
                # Extract results from transaction
                # game_data = result.get('game', {})
                real_players = result.get('real_players', 0)
                card_numbers = result.get('card_numbers', [])
                winner_data_base = result.get('winner_data', {})
                prize_pool = result.get('prize_pool', 0)
                
                # Get fake user details
                fake_user = self.fake_user_manager.fake_users.get(user_id, {})
                username = fake_user.get('username', f'FakeUser_{user_id}')
                full_name = fake_user.get('full_name', username)
                
                # Determine winning pattern
                winning_pattern = verified_pattern if has_bingo else self._generate_fallback_pattern(card_numbers,pattern_type)
                
                # Get fake count
                fake_count = len(self.fake_user_manager.game_fake_cards.get(game_id, {}))
                total_players = real_players + fake_count
                
                # Create complete winner data
                winner_data = {
                    **winner_data_base,
                    'username': username,
                    'full_name': full_name,
                    'winning_pattern': winning_pattern,
                    'pattern_type': pattern_type
                }
                
                # Add to winners list (async operation with winner_lock)
                await self.add_winner(game_id, winner_data)
                
                winners_count = await self.get_winners_count(game_id)
                logger.info(f"🎭 Fake winner added. Game {game_id} now has {winners_count}/2 winner(s)")
                 # Set winner display state on FIRST WINNER ONLY
                if winners_count == 1:
                    winner_display_duration = 10
                    winner_display_end = datetime.now() + timedelta(seconds=winner_display_duration)
                    
                    await Database.update_game_status(game_id, 'winner_display')
                    await Database.update_game_phase(game_id, 'winner_display')
                    await Database.set_winner_display_end(game_id, winner_display_end)
                    
                    async with self._lock:
                        self.active_game = await Database.get_game(game_id)
               
                # Increment state version
                self._game_state_versions[game_id] = self._game_state_versions.get(game_id, 0) + 1
                
                # Get all winners and calculate payouts
                all_winners = await self.get_winners(game_id)
                payouts = await self.calculate_winner_payouts(game_id, prize_pool)
                
                # Get this winner's payout
                winner_index = next((i for i, w in enumerate(all_winners) if w.get('user_id') == user_id), 0)
                winner_payout = payouts[winner_index] if winner_index < len(payouts) else prize_pool
                
                logger.info(f"Winner #{winner_index + 1} payout: {winner_payout} birr (total prize pool: {prize_pool})")
                
                # CRITICAL: Fake winner money goes to HOUSE BALANCE
                if winner_payout > 0:
                    await Database.add_to_house_balance(
                        amount=winner_payout,
                        description=f'Fake winner #{winners_count} in game {game_id} ({pattern_type})',
                        game_id=game_id
                    )
                    logger.info(f"🏦 Added {winner_payout} birr to house balance from fake winner")          
                    
                
                # ========== BROADCAST WINNER DATA ==========
                # Get fresh winners and payouts for broadcast
                final_all_winners = await self.get_winners(game_id)
                final_payouts = await self.calculate_winner_payouts(game_id, prize_pool)
                
                # Prepare complete winners data with all details
                complete_winners_data = []
                for i, w in enumerate(final_all_winners):
                    # # Ensure each winner has valid card numbers
                    # w = await self._ensure_winner_card_numbers(game_id, w)
                    winner_card_numbers = w.get('card_numbers', [])
                    winner_winning_pattern = w.get('winning_pattern', [])
                    # Ensure winning pattern is valid
                    if not winner_winning_pattern or len(winner_winning_pattern) == 0:
                        w_pattern_type = w.get('pattern_type', '')
                        winner_winning_pattern = self._generate_fallback_pattern(winner_card_numbers, w_pattern_type)
                    
                    winner_complete = {
                        'user_id': w.get('user_id'),
                        'username': w.get('username'),
                        'full_name': w.get('full_name'),
                        'card_index': w.get('card_index'),
                        'card_numbers': winner_card_numbers,
                        'winning_pattern': winner_winning_pattern,
                        'pattern_type': w.get('pattern_type', 'BINGO'),
                        'prize_amount': final_payouts[i] if i < len(final_payouts) else 0,
                        'is_fake': w.get('is_fake', False),
                        'winner_number': i + 1
                    }
                    complete_winners_data.append(winner_complete)
                
                # Create comprehensive winner announcement
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
                    
                    # Mark final broadcast if we have 2 winners
                    if len(final_all_winners) >= self.max_winners:
                        self._final_winner_broadcast_sent[game_id] = True
                        logger.info(f"Game {game_id} has reached 2 winners - marked as final")
                        
                except Exception as e:
                    logger.error(f"Failed to broadcast complete winner data: {e}")
                
                # Update game with winner info
                await Database.update_game_winner(game_id, user_id, prize_pool)
                
                # Mark fake card as winner
                if game_id in self.fake_user_manager.game_fake_cards:
                    if user_id in self.fake_user_manager.game_fake_cards[game_id]:
                        self.fake_user_manager.game_fake_cards[game_id][user_id]['is_winner'] = True
                
                # If this is the SECOND winner (game complete), record final details
                # if len(final_all_winners) >= self.max_winners:
                #     logger.info(f"🏆 Game {game_id} ending with {winners_count} winner(s). Finalizing...")
                  
                # Record game details with all winners
                await self._record_complete_game_details(
                    game_id=game_id,
                    winners=all_winners,
                    prize_pool=prize_pool,
                    winner_payouts=payouts,
                    called_numbers=called_numbers,
                    total_players=total_players,
                    is_fake=True
                )
                # Record commission with special ×10 rate for fake winners
                await self.record_fake_winner_commission(game_id)
                
                return {
                    'user_id': user_id,
                    'username': username,
                    'full_name': full_name,
                    'prize_amount': winner_payout,
                    'pattern_type': pattern_type,
                    'winning_pattern': winning_pattern,
                    'status': 'winner_display' if winners_count == 1 else 'additional_winner',
                    'winner_number': winners_count,
                    'total_winners': len(final_all_winners),
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
            
            # Get all games in card_purchase phase
            card_purchase_games = await Database.get_games_by_status('card_purchase')
            
            if len(card_purchase_games) > 1:
                logger.warning(f"Found {len(card_purchase_games)} games in card_purchase phase. Need to recover...")
                
                # Sort by creation time (oldest first)
                card_purchase_games.sort(key=lambda x: x.get('created_at', datetime.min))
                
                # Keep only the newest game, refund players in older games
                for i, game in enumerate(card_purchase_games):
                    game_id = game.get('game_id')
                    
                    if i == len(card_purchase_games) - 1:
                        # This is the newest game, keep it as active
                        async with self._lock:
                            self.active_game = game
                        logger.info(f"Keeping game {game_id} as active (newest)")
                    else:
                        # Older game, refund players and mark as completed
                        logger.warning(f"Game {game_id} is an older game in card_purchase. Refunding players...")
                        
                        # Refund all real players
                        await self._refund_all_players(game_id)
                        
                        # Clean up fake users
                        self.fake_user_manager.cleanup_game(game_id)
                        
                        # Clear winners for this game
                        await self.clear_winners(game_id)
                        
                        # Clear fake finalized flag
                        if game_id in self._fake_players_finalized:
                            del self._fake_players_finalized[game_id]
                        
                        # Mark game as completed/abandoned
                        await Database.update_game_status(game_id, 'completed')
                        await Database.update_game_phase(game_id, 'completed')
                        
                        logger.info(f"Game {game_id} marked as completed and players refunded")
            
            elif len(card_purchase_games) == 1:
                # Only one game, set it as active
                async with self._lock:
                    self.active_game = card_purchase_games[0]
                game_id = self.active_game.get('game_id')
                if game_id:
                    # Initialize winner tracking
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
            # Shutdown thread pool executor
            if hasattr(self, '_executor'):
                self._executor.shutdown(wait=True)
                logger.info("Thread pool executor shut down")
            
            # Cancel stuck game checker
            if hasattr(self, '_stuck_game_checker') and self._stuck_game_checker:
                self._stuck_game_checker.cancel()
                try:
                    await self._stuck_game_checker
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.error(f"Error cancelling stuck game checker: {e}")
                logger.info("Stuck game checker cancelled")
            
            # Cancel the main game loop
            if self._game_loop_task:
                self._game_loop_task.cancel()
                try:
                    await self._game_loop_task
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.error(f"Error cancelling game loop task: {e}")
                logger.info("Game loop task cancelled")
            
            # Cancel any winner display tasks (backup)
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
        """Legacy method - kept for compatibility but does nothing"""
        logger.info("Countdown monitor is deprecated - using continuous game loop instead")
        pass
    
    async def _check_for_stuck_winner_displays(self):
        """Legacy method - kept for compatibility but does nothing"""
        pass
    
    async def _check_for_stuck_active_games(self):
        """Legacy method - kept for compatibility but does nothing"""
        pass
    
    async def _recover_stuck_active_game(self, game_id: str):
        """Legacy method - kept for compatibility"""
        pass
    
    async def check_and_handle_countdown_completion(self, game_id: str):
        """Legacy method - kept for compatibility but does nothing"""
        return False
    
    async def get_active_round_game(self):
        """Get active round game - FIXED: Return a copy from cache with lock"""
        async with self._lock:
            # Return a copy to prevent external modification
            if self.active_game:
                return self.active_game.copy()
            return None
    
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
    
     # ==================== FIXED: Toggle card purchase with proper transaction handling ====================
    async def toggle_card_purchase(self, game_id: str, user_id: int, card_index: int, action: str = 'buy'):
        """Toggle card purchase/refund - FIXED: With transaction helper and balance_after"""
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
            async with self._lock:
                if self.active_game and self.active_game.get('game_id') != game_id:
                    return {
                        'success': False,
                        'message': 'This game is no longer active. Please purchase cards in the latest game.'
                    }
 
            # Check countdown
            countdown = await Database.get_game_countdown(game_id)
            if countdown <= 0:
                return {
                    'success': False,
                    'message': 'Card purchase time has expired'
                }
 
            if action == 'buy':
                # Run purchase transaction in thread pool
                purchase_result = await self._run_in_transaction(
                    self._execute_purchase_transaction,
                    game_id, user_id, card_index
                )
                
                if not purchase_result.get('success'):
                    return purchase_result
             
                card_id = purchase_result['card_id']
                card_numbers = purchase_result['card_numbers']
                new_balance = purchase_result['new_balance']
              
                # Handle real user join
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
                    cursor.execute("UPDATE games SET prize_pool = ? WHERE game_id = ?", 
                                 (correct_prize_pool, game_id))
  
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
                # Run refund transaction in thread pool
                refund_result = await self._run_in_transaction(
                    self._execute_refund_transaction,
                    game_id, user_id, card_index
                )
             
                if not refund_result.get('success'):
                    return refund_result
             
                refund_amount = refund_result['refund_amount']
                new_balance = refund_result['new_balance']
              
                # Handle real user refund
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
                    cursor.execute("UPDATE games SET prize_pool = ? WHERE game_id = ?", 
                                 (correct_prize_pool, game_id))
 
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
    
    # ==================== FIXED: Transaction helper methods with correct balance_after ====================
    
    def _record_transaction(self, cursor, user_id: int, amount: float, transaction_type: str, description: str, game_id: str = None):
        """Record financial transaction with correct balance_after - FIXED"""
        
        # Get current balance AFTER the transaction has been applied
        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        if not result:
            raise Exception(f"User {user_id} not found")
        
        current_balance = float(result['balance'])
        
        # Insert transaction with balance_after
        cursor.execute("""
            INSERT INTO transactions 
            (user_id, amount, balance_after, transaction_type, description, game_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            amount,
            current_balance,  # This is the balance AFTER the transaction
            transaction_type,
            description,
            game_id,
            datetime.now()
        ))
    
    # ==================== SYNCHRONOUS TRANSACTION METHODS ====================
    
    def _execute_purchase_transaction(self, game_id: str, user_id: int, card_index: int) -> dict:
        """Execute purchase transaction synchronously with proper locking - FIXED: Correct balance_after and uses fixed cards"""
        from database.db import Database
        
        with transaction() as cursor:
            try:
                # Check total players doesn't exceed 400
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
                cursor.execute("""
                    SELECT id FROM player_cards 
                    WHERE game_id = ? AND user_id = ? AND is_active = 1
                """, (game_id, user_id))
                if cursor.fetchone():
                    return {
                        'success': False,
                        'message': 'You can only buy 1 card per game'
                    }

                # Check if card is already sold
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
                cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
                user_row = cursor.fetchone()
                if not user_row:
                    # Create user if doesn't exist
                    cursor.execute("""
                        INSERT INTO users (user_id, username, full_name, balance, created_at)
                        VALUES (?, ?, ?, ?, ?)
                    """, (user_id, f"User_{user_id}", f"User {user_id}", 0, datetime.now()))
                    balance = 0
                else:
                    balance = float(user_row['balance'])

                if balance < 10.00:
                    return {
                        'success': False,
                        'message': 'Insufficient balance'
                    }

                # ==================== FIXED: Use static card numbers instead of generating random ones ====================
                card_numbers = self.fixed_cards.get(f"card_{card_index}")
                
                # Fallback in case card index is out of range (shouldn't happen)
                if not card_numbers:
                    logger.error(f"Card index {card_index} not found in fixed cards! Using fallback generation.")
                    card_numbers = self._generate_bingo_card_numbers()

                # Create player card - FIXED: Handle missing price column gracefully
                try:
                    # Try with price column first
                    cursor.execute("""
                        INSERT INTO player_cards (user_id, game_id, card_numbers, price, card_index, is_active, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        user_id, game_id, json.dumps(card_numbers), 10.00, card_index, 1, datetime.now()
                    ))
                except Exception as e:
                    # If price column doesn't exist, try without it
                    logger.warning(f"Price column may not exist, trying without: {e}")
                    cursor.execute("""
                        INSERT INTO player_cards (user_id, game_id, card_numbers, card_index, is_active, created_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        user_id, game_id, json.dumps(card_numbers), card_index, 1, datetime.now()
                    ))
                
                card_id = cursor.lastrowid

                # Deduct balance (THIS COMES FIRST - updates the balance)
                cursor.execute("""
                    UPDATE users SET balance = balance - 10.00 WHERE user_id = ?
                """, (user_id,))
                
                # Get the NEW balance after deduction
                cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
                new_balance_row = cursor.fetchone()
                new_balance = float(new_balance_row['balance'])

                # Add transaction record with the CORRECT balance_after (which is the new balance)
                cursor.execute("""
                    INSERT INTO transactions (user_id, amount, balance_after, transaction_type, description, game_id, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    user_id, -10.00, new_balance, 'card_purchase', 
                    f'Purchased card #{card_index} for 10 birr', game_id, datetime.now()
                ))

                # Add to prize pool (8 birr)
                cursor.execute("""
                                UPDATE games 
                                SET 
                                    prize_pool = COALESCE(prize_pool, 0) + 8.00,
                                    total_players = COALESCE(total_players, 0) + 1
                                WHERE game_id = ?
                            """, (game_id,))

                return {
                    'success': True,
                    'card_id': card_id,
                    'card_numbers': card_numbers,
                    'new_balance': new_balance
                }
                
            except Exception as e:
                logger.error(f"Error in purchase transaction: {e}")
                raise  # Let transaction manager handle rollback
    
    # ==================== FIXED: Refund Transaction with proper logic and SQLite compatibility ====================
    
    def _execute_refund_transaction(self, game_id: str, user_id: int, card_index: int) -> dict:
        """Execute refund transaction synchronously with proper locking - FIXED: Removed GREATEST for SQLite compatibility"""
        from database.db import Database
    
        with transaction() as cursor:
            try:
                # Get user's active card with all details
                cursor.execute("""
                    SELECT id, purchase_price, card_index, created_at
                    FROM player_cards 
                    WHERE game_id = ? AND user_id = ? AND card_index = ? AND is_active = 1
                """, (game_id, user_id, card_index))
                card_row = cursor.fetchone()
            
                if not card_row:
                    logger.error(f"Refund failed: Card #{card_index} not found for user {user_id} in game {game_id}")
                    return {
                        'success': False,
                        'message': 'You do not own this card or it is not active'
                    }
            
                card_id = card_row['id']
                purchase_price = float(card_row['purchase_price']) if card_row['purchase_price'] else 10.00
            
                # Get current balance
                cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
                user_row = cursor.fetchone()
                if not user_row:
                    return {
                        'success': False,
                        'message': 'User not found'
                    }
                current_balance = float(user_row['balance'])
            
                # Refund amount (full purchase price)
                refund_amount = purchase_price

                # Calculate new balance after refund
                new_balance = current_balance + refund_amount

                # Refund user (full amount) - THIS COMES FIRST
                cursor.execute("""
                    UPDATE users SET balance = ? WHERE user_id = ?
                """, (new_balance, user_id))
             
                # Remove from prize pool (80% of purchase price goes to prize pool)
                prize_pool_deduction = purchase_price * 0.8  # 8 birr from 10 birr purchase
                
                # FIXED: Replace GREATEST with MAX(0, prize_pool - ?) for SQLite compatibility
                cursor.execute("""
                    UPDATE games SET 
                               prize_pool = MAX(0, prize_pool - ?),
                               total_players = COALESCE(total_players, 0) - 1
                    WHERE game_id = ?
                """, (prize_pool_deduction, game_id))
 
                # Mark card as inactive
                cursor.execute("""
                    UPDATE player_cards SET is_active = 0, refunded_at = ? WHERE id = ?
                """, (datetime.now(), card_id))
                
                # Record transaction using helper (now with correct balance_after)
                self._record_transaction(
                    cursor,
                    user_id,
                    refund_amount,
                    'card_refund',
                    f'Refund for card #{card_index} (100% of {purchase_price} birr)',
                    game_id
                )
  
                logger.info(f"✅ Refund successful: User {user_id} refunded {refund_amount} birr for card #{card_index} in game {game_id}")
  
                return {
                    'success': True,
                    'refund_amount': refund_amount,
                    'new_balance': new_balance
                }
             
            except Exception as e:
                logger.error(f"Error in refund transaction: {e}")
                raise
    
    # ==================== FIXED: process_winner with transaction handling ====================
    async def process_winner(self, game_id: str, user_id: int):
        """Process bingo winner - UPDATED: Two winner support with 50-50 split and TRUE claims"""
        async with self._verification_lock:
            try:
                from utils.number_caller import number_caller
                
                logger.info(f"🚀 BINGO VERIFICATION STARTING for user {user_id} in game {game_id}")
                start_time = time.time()
                
                # Get game details (async DB operation)
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
                
                # Get user card (async DB operation)
                user_card = await Database.get_user_card_in_game(user_id, game_id)
                if not user_card:
                    logger.error(f"User {user_id} has no card in game {game_id}")
                    return None
                
                # Fast bingo verification (sync - no DB)
                called_numbers = await Database.get_drawn_numbers(game_id)
                has_bingo, winning_pattern, pattern_type = await self._fast_verify_bingo_with_pattern(user_card, called_numbers)
                
                verification_time = (time.time() - start_time) * 1000
                logger.info(f"⚡ Bingo verified in {verification_time:.1f}ms - Result: {has_bingo}, Pattern: {pattern_type}")
                
                if not has_bingo:
                    logger.error(f"Invalid bingo claim by user {user_id}")
                    return None
                
                # Get prize pool (already have from game)
                prize_pool = float(game.get('prize_pool', 0.00))
                if prize_pool <= 0:
                    logger.error(f"No prize pool in game {game_id}")
                    return None
                
                # Count players (async DB operation)
                real_players = await Database.count_game_players(game_id)
                fake_count = len(self.fake_user_manager.game_fake_cards.get(game_id, {}))
                total_players = real_players + fake_count
                
                # Get user details (async DB operation)
                user = await Database.get_user(user_id)
                username = user.get('username', f'User_{user_id}') if user else f'User_{user_id}'
                full_name = user.get('full_name', '') if user else ''
                
                # Extract card numbers for display
                card_numbers = self._extract_card_numbers(user_card)
                
                # FIXED: Ensure winning_pattern contains actual corner numbers for 4 corners
                if pattern_type == "four_corners":
                    if len(card_numbers) == 25:
                        actual_corners = [card_numbers[0], card_numbers[4], card_numbers[20], card_numbers[24]]
                        logger.info(f"🎯 Using actual 4 Corners numbers: {actual_corners}")
                        winning_pattern = actual_corners
                
                # Create winner data
                winner_data = {
                    'user_id': user_id,
                    'username': username,
                    'full_name': full_name,
                    'card_index': user_card.get('card_index'),
                    'card_numbers': card_numbers,
                    'winning_pattern': winning_pattern if winning_pattern else [],
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
                    
                
                # ========== PROCESS PAYMENT FOR THIS WINNER (in transaction) ==========
                payment_result = await self._run_in_transaction(
                    self._process_winner_payment_transaction,
                    game_id, user_id, winner_payout, winners_count, pattern_type
                )
                
                if not payment_result.get('success'):
                    logger.error(f"Failed to process winner payment: {payment_result.get('message')}")
                
                # Update game with winner info (async DB operation)
                await Database.update_game_winner(game_id, user_id, prize_pool)
                await Database.mark_bingo(user_card['id'], winner_payout)
                
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
                
                # ========== PROCESS GAME COMPLETION (record commission and finalize) ==========
                # Commission should be recorded whenever game ends, regardless of winner count
                logger.info(f"🏆 Game {game_id} ending with {winners_count} winner(s). Finalizing...")
                
                # Validate prize pool before finalizing - use updated player counts
                # Get fresh player counts after winner processing
                fresh_real_players = await Database.count_game_players(game_id)
                fresh_fake_count = len(self.fake_user_manager.game_fake_cards.get(game_id, {}))
                fresh_total_players = fresh_real_players + fresh_fake_count
                
                await self._validate_prize_pool(game_id, fresh_total_players, prize_pool)
                
                # Record game details with all winners - FIXED method below
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
                
                # Record commission in transaction
                await self._run_in_transaction(
                    self._record_game_commission_transaction,
                    game_id, game.get('round_number', 1),user_id)

                # Mark game as completed in tracking set
                self._completed_games.add(game_id)
                
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
    
    def _process_winner_payment_transaction(self, game_id: str, user_id: int, 
                                           winner_payout: float, winners_count: int, 
                                           pattern_type: str) -> dict:
        """Process winner payment in a transaction - FIXED: Correct balance_after"""
        from database.db import Database
        
        with transaction() as cursor:
            try:
                # Get current balance
                cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
                user_row = cursor.fetchone()
                current_balance = float(user_row['balance']) if user_row else 0.00
                
                # Calculate new balance
                new_balance = current_balance + winner_payout
                
                # Update user balance (THIS COMES FIRST)
                cursor.execute("""
                    UPDATE users SET balance = ? WHERE user_id = ?
                """, (new_balance, user_id))
                
                # Add transaction record with correct balance_after
                cursor.execute("""
                    INSERT INTO transactions (user_id, amount, balance_after, transaction_type, description, game_id, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    user_id, winner_payout, new_balance, 'winning',
                    f'BINGO win #{winners_count} in game {game_id} (Pattern: {pattern_type}, Prize: {winner_payout:.2f} birr)',
                    game_id, datetime.now()
                ))
                
                return {'success': True}
                
            except Exception as e:
                logger.error(f"Error processing winner payment transaction: {e}")
                raise
    
    def _record_game_commission_transaction(self, game_id: str, round_number: int,user_id:int=None) -> dict:
        """Record game commission with initial balance deduction (backward compatible)"""
        with transaction() as cursor:
            try:
                INITIAL_DEPOSIT = getattr(self, "INITIAL_DEPOSIT", 10)  # fallback
                
                # ========== STEP 1: Get DISTINCT real user_ids ==========
                cursor.execute("""
                    SELECT DISTINCT user_id,is_fake
                    FROM player_cards 
                    WHERE game_id = ?  AND is_active = 1
                """, (game_id,))
                
                rows = cursor.fetchall()
                rows = rows if rows else []
                user_ids = [row['user_id'] for row in rows if row['is_fake'] == 0]
                real_players = len(user_ids)
                fake_players = len(rows) - real_players

                logger.info(f"Current real players for commission: {real_players}")

                # ========== STEP 2: Prevent duplicate commission ==========
                cursor.execute("""
                    SELECT COUNT(*) as count FROM commission_records WHERE game_id = ?
                """, (game_id,))
                
                if cursor.fetchone()['count'] > 0:
                    logger.info(f"Commission already recorded for game {game_id}")
                    return {'success': True, 'already_recorded': True}

                # ========== STEP 3: Check if column exists ==========
                cursor.execute("PRAGMA table_info(users)")
                columns = [col[1] for col in cursor.fetchall()]
                has_column = "used_initial_balance" in columns

                eligible_users = []
                eligible_count = 0

                # ========== STEP 4: Get eligible users (if column exists) ==========
                if has_column and user_ids:
                    placeholders = ",".join(["?"] * len(user_ids))
                    
                    cursor.execute(f"""
                        SELECT user_id
                        FROM users
                        WHERE user_id IN ({placeholders})
                        AND used_initial_balance = 0
                    """, user_ids)
                    
                    eligible_rows = cursor.fetchall()
                    eligible_users = [row['user_id'] for row in eligible_rows]
                    eligible_count = len(eligible_users)

                # ========== STEP 5: Determine deduction per user ==========
                if INITIAL_DEPOSIT == 10:
                    deduction_per_user = 2.0
                elif INITIAL_DEPOSIT == 5:
                    deduction_per_user = 1.0
                else:
                    deduction_per_user = 0.0  # fallback

                # ========== STEP 6: Calculate commission ==========
                base_commission = real_players * 2.0
                deduction = eligible_count * deduction_per_user
                commission = base_commission - deduction
                #payable amount (lossing amount)
                payable_amount = fake_players * 8
                if user_id in eligible_users:
                    payable_amount += (INITIAL_DEPOSIT-deduction_per_user)


                logger.info(
                    f"📊 COMMISSION CALCULATION:\n"
                    f"   Real Players: {real_players}\n"
                    f"   Eligible: {eligible_count}\n"
                    f"   Deduction per user: {deduction_per_user}\n"
                    f"   Total Deduction: {deduction}\n"
                    f"   Final Commission: {commission}"
                )

                # ========== STEP 7: Update users ==========
                if has_column and eligible_users:
                    placeholders = ",".join(["?"] * len(eligible_users))
                    
                    cursor.execute(f"""
                        UPDATE users
                        SET used_initial_balance = 1
                        WHERE user_id IN ({placeholders})
                    """, eligible_users)

                    logger.info(f"✅ Updated {len(eligible_users)} users: used_initial_balance = 1")

                # ========== STEP 8: Record commission ==========
                cursor.execute("""
                    INSERT INTO commission_records 
                    (game_id, round_number, real_players_count, commission_amount, recorded_at, status,payable_amount)
                    VALUES (?, ?, ?, ?, ?, ?,?)
                """, (
                    game_id, round_number, real_players, commission, datetime.now(), 'recorded',payable_amount
                ))

                # ========== STEP 9: Add to house balance ==========
                cursor.execute("""
                    INSERT INTO house_balance (amount, transaction_type, description, game_id, created_at)
                    VALUES (?, 'game_commission', ?, ?, ?)
                """, (
                    commission,
                    f'Commission from game {game_id} ({real_players} players, {eligible_count} used initial)',
                    game_id,
                    datetime.now()
                ))

                logger.info(f"✅ Commission recorded: {commission:.2f} for game {game_id}")

                return {'success': True, 'commission': commission}

            except Exception as e:
                logger.error(f"Error recording commission transaction: {e}", exc_info=True)
                raise
    
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
    
    # async def _monitor_winner_display_countdown(self, game_id: str, winner_display_end: datetime):
    #     """Monitor winner display countdown - backup for main loop"""
    #     try:
    #         logger.info(f"⏱️ Starting winner display monitor backup for game {game_id}")
            
    #         from database.db import Database
            
    #         # Calculate initial wait time
    #         current_time = datetime.now()
    #         if winner_display_end > current_time:
    #             wait_time = (winner_display_end - current_time).total_seconds()
    #             await asyncio.sleep(wait_time)
            
    #         # If game is still in winner_display after wait, log but don't force (main loop handles it)
    #         game = await Database.get_game(game_id)
    #         if game and game.get('status') == 'winner_display':
    #             logger.info(f"Winner display should be ending for game {game_id}")
            
    #     except asyncio.CancelledError:
    #         logger.info(f"Winner display monitor backup cancelled for game {game_id}")
    #     except Exception as e:
    #         logger.error(f"Error in winner display monitor backup for game {game_id}: {e}")
    #     finally:
    #         if game_id in self._winner_display_tasks:
    #             del self._winner_display_tasks[game_id]
    
    # ==================== FIXED: Record complete game details with correct commission - FIXED DATABASE ERROR ====================
    async def _record_complete_game_details(self, game_id: str, winners: List[Dict], prize_pool: float, 
                                               winner_payouts: List[float], called_numbers: list, 
                                               total_players: int, is_fake: bool = False):
        """
        Record complete game details for history and reporting - FIXED: Now only records game history,
        commission is handled separately in record_game_commission()
        CRITICAL FIX: Only records to DB if at least one real player participated.
        """
        try:            
            # ========== STEP 1: REAL PLAYER CHECK (The "Firewall") ==========
            # We check if there's at least one active, non-fake card in the game
            def check_real():
                with Database.get_cursor() as cursor:
                    cursor.execute("""
                        SELECT COUNT(*) as count 
                        FROM player_cards 
                        WHERE game_id = ? AND is_fake = 0 AND is_active = 1
                    """, (game_id,))
                    res = cursor.fetchone()
                    return res['count'] if res else 0

            real_card_count = await asyncio.to_thread(check_real)
            
            if real_card_count == 0:
                logger.info(f"📉 Bot-only game {game_id} - skipping detail recording to keep DB clean.")
                return True # Return True because the logic "finished" correctly by ignoring it
            
            # ========== STEP 2: DATA PREPARATION ==========
            # Get the game details
            game = await Database.get_game(game_id)
            if not game:
                logger.error(f"Could not find game {game_id} for recording details")
                return False
            
            # Get real players count (for logging/reference)
            real_players = await Database.count_game_players(game_id)
            
            # Calculate total sales using card price from games table
            card_price = float(game.get('card_price', 10.00))
            total_sales = real_card_count * card_price
            
            # Get fake card count
            fake_cards_sold = await Database.count_active_fake_cards(game_id)
            total_cards_sold = real_card_count + fake_cards_sold
            
            # Prepare winners data for storage
            winners_data = []
            for i, winner in enumerate(winners):
                # Ensure winner has card numbers (using your helper method)
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
            
            # ========== STEP 3: DATABASE INSERTION (Transaction) ==========
            with Database.get_cursor() as cursor:
                # Record in game_history table
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
                    'multiple_winners' if len(winners) > 1 else (winners[0].get('pattern_type', 'unknown') if winners else 'none'),
                    json.dumps(called_numbers),
                    total_players,
                    real_card_count,
                    fake_cards_sold,
                    total_cards_sold,
                    total_sales,
                    len(winners),
                    json.dumps(winners_data),
                    json.dumps(winner_payouts),
                    1 if is_fake else 0,
                    self.min_fake_players,
                    self.max_fake_players,
                    datetime.now().date(),
                    datetime.now()
                ))
                
                # Update the games table status
                cursor.execute("""
                    UPDATE games 
                    SET completed_at = ?,
                        real_cards_sold = ?,
                        total_sales = ?,
                        winners_count = ?
                    WHERE game_id = ?
                """, (
                    datetime.now(),
                    real_card_count,
                    total_sales,
                    len(winners),
                    game_id
                ))
                
                logger.info(f"📊 Game {game_id} recorded: {real_players} players, {real_card_count} cards, {total_sales:.2f} sales")
                return True
                
        except Exception as e:
            logger.error(f"Error recording complete game details for {game_id}: {e}")
            return False
    
    # ==================== FIXED: Record game commission in dedicated commission_records table ====================
    async def _record_game_commission(self, game_id: str):
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
                commission = await self.calculate_fake_winner_commission(game_id)
                logger.info(f"📊 FAKE WINNER COMMISSION: {real_players} real active players × (10) = {commission} birr")
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
    async def calculate_fake_winner_commission(self, game_id: str) -> float:
        """
        Calculate commission with initial balance logic.
        Backward compatible using PRAGMA check.
        """
        try:

            with Database.get_cursor() as cursor:

                # ========== STEP 1: Get DISTINCT real users ==========
                cursor.execute("""
                    SELECT DISTINCT user_id
                    FROM player_cards
                    WHERE game_id = ? AND is_fake = 0 AND is_active = 1
                """, (game_id,))
                
                rows = cursor.fetchall()
                player_ids = [row['user_id'] for row in rows] if rows else []
                real_players = len(player_ids)

                if real_players == 0:
                    return 0.0

                commission_per_user = 10.0

                # ========== STEP 2: Check if column exists ==========
                cursor.execute("PRAGMA table_info(users)")
                columns = [col[1] for col in cursor.fetchall()]
                has_column = "used_initial_balance" in columns

                eligible_users = []
                eligible_count = 0

                # ========== STEP 3: Get eligible users ==========
                if has_column and player_ids:
                    placeholders = ",".join(["?"] * len(player_ids))
                    
                    cursor.execute(f"""
                        SELECT user_id
                        FROM users
                        WHERE user_id IN ({placeholders})
                        AND used_initial_balance = 0
                    """, player_ids)
                    
                    eligible_rows = cursor.fetchall()
                    eligible_users = [row['user_id'] for row in eligible_rows]
                    eligible_count = len(eligible_users)

                # ========== STEP 4: Calculate commission ==========
                # ⚠️ Fixed bug: use eligible_count not eligible_users
                commission = (real_players * commission_per_user) - (
                    eligible_count * commission_per_user / 2
                )

                logger.info(
                    f"📊 COMMISSION CALCULATION:\n"
                    f"   Real Players: {real_players}\n"
                    f"   Eligible: {eligible_count}\n"
                    f"   Final Commission: {commission}"
                )

                # ========== STEP 5: Update users ==========
                if has_column and eligible_users:
                    placeholders = ",".join(["?"] * len(eligible_users))
                    
                    cursor.execute(f"""
                        UPDATE users
                        SET used_initial_balance = 1
                        WHERE user_id IN ({placeholders})
                    """, eligible_users)

                    logger.info(f"✅ Updated {len(eligible_users)} users")

                return commission

        except Exception as e:
            logger.error(f"❌ Error calculating commission: {e}", exc_info=True)
            return 0.0
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
        """Legacy method - kept for compatibility"""
        pass
    
    async def _schedule_next_round_after_winner_display(self, completed_game_id: str):
        """Legacy method - kept for compatibility"""
        pass
    
    async def start_new_round_game(self):
        """Start a new round game - FIXED: Strict duplicate prevention"""
        # This method is now handled by the continuous loop
        # Kept for API compatibility
        return await self._ensure_game_exists()
    
    # ==================== FIXED: Start game play with correct prize pool verification ====================
    async def start_game_play(self, game_id: str):
        """Start game play phase - This is now handled by the continuous loop"""
        # This method is now handled by the continuous loop
        # Kept for API compatibility
        logger.info(f"start_game_play called for {game_id} - this is now handled by continuous loop")
        return True
    
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
        # This is now handled by the continuous loop
        # Kept for API compatibility
        logger.info(f"end_game called for {game_id} - this is now handled by continuous loop")
        return True
    
    async def auto_transition_phase(self, game_id: str):
        """Legacy method - kept for compatibility"""
        pass
    
    def _generate_bingo_card_numbers(self):
        """Generate random Bingo card numbers - FALLBACK METHOD (rarely used now)"""
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
                    'game_loop_running': self._game_loop_task is not None and not self._game_loop_task.done(),
                    'stuck_game_checker_running': self._stuck_game_checker is not None and not self._stuck_game_checker.done(),
                    'auto_start_games': self.auto_start_games,
                    'cache_size': {
                        'called_numbers': len(self._called_numbers_cache),
                        'user_cards': len(self._user_cards_cache)
                    },
                    'recovery_in_progress': self._recovery_in_progress,
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
                self.active_game = await Database.get_active_round_game()
                
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
        # This is now handled by the continuous loop
        # Kept for API compatibility
        pass
    
    async def ensure_game_continuity(self):
        """Ensure game continues without interruption"""
        # This is now handled by the continuous loop
        # Kept for API compatibility
        pass

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
        # This is now handled by the continuous loop
        # Kept for API compatibility
        return {'success': False, 'message': 'Manual recovery not needed - continuous loop handles recovery'}

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
        # This is now handled by the continuous loop
        # Kept for API compatibility
        return {'success': False, 'message': 'Force complete not needed - continuous loop handles winner display'}

    async def force_complete_winner_display_immediately(self, game_id: str):
        """Force complete winner display immediately (for stuck games)"""
        # This is now handled by the continuous loop
        # Kept for API compatibility
        return {'success': False, 'message': 'Force complete not needed - continuous loop handles winner display'}

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
            await self._cleanup_game_caches(game_id)
            
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