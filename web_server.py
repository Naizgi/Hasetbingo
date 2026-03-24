# web_server.py - Fixed time synchronization logic
# FIXED COUNTDOWN SYNCHRONIZATION
# FIXED: Removed duplicate winner_confirmed message to prevent data conflict
# FIXED: Bingo claim race condition with 4 corners priority
# FIXED: HTML file serving from external files
# ADDED: Missing admin API endpoints for compatibility with admin.html
# ADDED: Complete state endpoint for reconnection sync
# FIXED: Weekly commission calculation to use real players count, not cards sold
# FIXED: Prize pool calculation to include fake players correctly
# FIXED: Player count display to show total (real + fake) players
# FIXED: All commission endpoints now use commission_records table
# FIXED: Total balance endpoint now shows only real user balances (no fake players)
# FIXED: Commission display in admin panel - now properly shows from commission_records
# ADDED: Force reset game endpoint to handle stuck games
# ADDED: Game state cleanup on startup
# FIXED: Start game endpoint to handle edge cases
# ADDED: User search API for admin panel - FIXED to work properly
# ADDED: Transaction filtering API for deposits and withdrawals

from aiohttp import web
import json
import logging
import asyncio
import os
import random
import decimal
from datetime import datetime, timedelta, date
from typing import Set, Dict, List
import time
import sys
import gzip
import shutil
import tempfile
import sqlite3

logger = logging.getLogger(__name__)

# Configuration
WEBSERVER_HOST = os.getenv('WEBSERVER_HOST', '0.0.0.0')
WEBSERVER_PORT = int(os.getenv('WEBSERVER_PORT', '8001'))
WEB_APP_URL = f"http://{WEBSERVER_HOST}:{WEBSERVER_PORT}"

# Fix for Windows socket issues
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    
# ==================== GLOBAL BOT REFERENCE ====================
# This will be set by bot.py when it starts
bot_instance = None

def set_bot_instance(bot):
    """Set the global bot instance for notifications"""
    global bot_instance
    bot_instance = bot
    logger.info("✅ Bot instance registered with web_server")
    
    
# ==================== THREAD-SAFE NOTIFICATION QUEUE ====================
import queue
import threading
from aiogram import Bot

class NotificationQueue:
    """Thread-safe queue for sending notifications from web server thread"""
    
    def __init__(self):
        self.queue = queue.Queue()
        self.bot = None
        self._loop = None
        self._running = False
        self._thread = None
        
    def set_bot(self, bot_instance, loop=None):
        """Set the bot instance and event loop"""
        self.bot = bot_instance
        if loop:
            self._loop = loop
        logger.info("✅ Notification queue: Bot and loop registered")
        
    def start(self, loop=None):
        """Start the notification processor"""
        if self._running:
            return
            
        if loop:
            self._loop = loop
            
        if not self._loop:
            logger.error("❌ Cannot start notification queue: No event loop provided")
            return
            
        self._running = True
        self._thread = threading.Thread(target=self._process_queue, daemon=True)
        self._thread.start()
        logger.info("✅ Notification queue processor started")
        
    def stop(self):
        """Stop the notification processor"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
            logger.info("✅ Notification queue processor stopped")
        
    def _process_queue(self):
        """Process notifications in a separate thread"""
        import asyncio
        
        logger.info("📨 Notification queue processor thread started")
        
        while self._running:
            try:
                # Get notification from queue with timeout
                notification = self.queue.get(timeout=1)
                user_id = notification['user_id']
                message = notification['message']
                
                logger.info(f"📤 Processing queued notification for user {user_id}")
                
                # Send message using the bot instance
                future = asyncio.run_coroutine_threadsafe(
                    self.bot.send_message(
                        chat_id=user_id,
                        text=message,
                        parse_mode="Markdown",
                        disable_web_page_preview=True
                    ),
                    self._loop
                )
                
                try:
                    # Wait for result with timeout
                    result = future.result(timeout=30)
                    logger.info(f"✅ Queued notification sent to user {user_id}")
                except TimeoutError:
                    logger.error(f"❌ Timeout sending queued notification to user {user_id}")
                except Exception as e:
                    logger.error(f"❌ Error sending queued notification: {e}")
                    
            except queue.Empty:
                # No notifications, just continue
                continue
            except Exception as e:
                logger.error(f"❌ Notification queue processor error: {e}")
                
    def add_notification(self, user_id: int, message: str) -> bool:
        """Add a notification to the queue"""
        try:
            self.queue.put_nowait({
                'user_id': user_id,
                'message': message,
                'timestamp': datetime.now().isoformat()
            })
            queue_size = self.queue.qsize()
            logger.info(f"📥 Added notification for user {user_id} to queue (size: {queue_size})")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to add notification to queue: {e}")
            return False

# Create global notification queue
notification_queue = NotificationQueue()
    
# ==================== SIMPLIFIED NOTIFICATION FUNCTION ====================
async def send_notification_to_user(user_id: int, message: str) -> bool:
    """Send a notification message to a user - USING QUEUE SYSTEM"""
    
    # Add to queue and return immediately
    return notification_queue.add_notification(user_id, message)
# ==================== SIMPLIFIED WEBSOCKET SERVER ====================

class ValidationWebSocketServer:
    def __init__(self):
        self.connections: Set[web.WebSocketResponse] = set()
        self.user_connections: Dict[str, web.WebSocketResponse] = {}
        self._shutting_down = False
        self._verification_lock = asyncio.Lock()  # Lock to prevent race conditions
        self._bingo_claim_lock = asyncio.Lock()  # NEW: Lock for bingo claims
        
    async def cleanup(self):
        """Cleanup resources on shutdown"""
        self._shutting_down = True
        
        # Close all connections gracefully
        for websocket in list(self.connections):
            try:
                await websocket.close(code=1000, reason="Server shutting down")
            except Exception as e:
                logger.debug(f"Error closing connection: {e}")
        
        self.connections.clear()
        self.user_connections.clear()
        logger.info("WebSocket server cleanup completed")
    
    async def handle_connection(self, ws: web.WebSocketResponse):
        """Handle new WebSocket connection"""
        self.connections.add(ws)
        connection_id = f"ws_{id(ws)}"
        
        logger.info(f"WebSocket connection established. Total connections: {len(self.connections)}")
        
        try:
            # Send welcome message
            await self._safe_send_async(ws, {
                'type': 'welcome',
                'message': 'Connected to Habesha Bingo Validation Server',
                'timestamp': datetime.now().isoformat(),
                'connection_id': connection_id
            })
            
            # FIX: Get active game info immediately
            try:
                from utils.game_manager import game_manager
                active_game = await game_manager.get_active_round_game()
                if active_game:
                    await self._safe_send_async(ws, {
                        'type': 'active_game_info',
                        'game_id': active_game.get('game_id'),
                        'status': active_game.get('status', 'card_purchase'),
                        'phase': active_game.get('current_phase', 'card_purchase'),
                        'round_number': active_game.get('round_number', 1),
                        'timestamp': datetime.now().isoformat()
                    })
            except Exception as e:
                logger.debug(f"Error sending active game info: {e}")
            
            # Main message handling loop
            async for msg in ws:
                if msg.type == web.WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        await self.handle_message(ws, data, connection_id)
                    except json.JSONDecodeError as e:
                        await self._safe_send_async(ws, {
                            'type': 'error',
                            'message': 'Invalid JSON format',
                            'details': str(e)
                        })
                    except Exception as e:
                        logger.error(f"Error processing message: {e}", exc_info=True)
                elif msg.type == web.WSMsgType.ERROR:
                    logger.error(f"WebSocket error: {ws.exception()}", exc_info=True)
                    break
                elif msg.type == web.WSMsgType.CLOSE:
                    logger.debug(f"WebSocket close received: {msg.extra}")
                    break
                    
        except asyncio.CancelledError:
            logger.debug(f"WebSocket connection {connection_id} cancelled")
        except ConnectionResetError:
            logger.debug(f"Connection reset for {connection_id}")
        except Exception as e:
            logger.error(f"WebSocket connection error: {e}", exc_info=True)
        finally:
            # Remove connection
            self.connections.discard(ws)
            
            # Remove from user connections
            for user_id, connection_ws in list(self.user_connections.items()):
                if connection_ws == ws:
                    del self.user_connections[user_id]
                    logger.info(f"User {user_id} disconnected from WebSocket")
                    break
            
            logger.info(f"WebSocket connection closed. Total connections: {len(self.connections)}")
    
    async def handle_message(self, ws: web.WebSocketResponse, data: dict, connection_id: str):
        """Handle incoming WebSocket messages"""
        msg_type = data.get('type')
        
        try:
            if msg_type == 'auth':
                await self._handle_auth(ws, data, connection_id)
            elif msg_type == 'player_bingo_claim':
                # FIXED: Use immediate bingo claim handler
                await self._handle_immediate_player_bingo_claim(data)
            elif msg_type == 'countdown_complete':
                await self._handle_countdown_complete(data)
            elif msg_type == 'phase_transition':
                await self._handle_phase_transition(data)
            elif msg_type == 'new_round_started':
                await self._handle_new_round_started(data)
            elif msg_type == 'ping':
                await self._handle_ping(ws)
            elif msg_type == 'request_sync':
                await self._handle_request_sync(data)
            elif msg_type == 'get_active_game':  # NEW: Request active game info
                await self._handle_get_active_game(ws)
            elif msg_type == 'client_sync':  # NEW: Client sync message with countdown
                await self._handle_client_sync(ws, data)
            elif msg_type == 'test_bingo':  # NEW: Test bingo verification
                await self._handle_test_bingo(data, connection_id)
            else:
                logger.warning(f"Unknown message type from {connection_id}: {msg_type}")
                
        except Exception as e:
            logger.error(f"Error handling message type {msg_type} from {connection_id}: {e}")
    
    
    # ==================== FIXED: PHASE CHANGE BROADCAST METHOD ====================
    
    
    # ==================== FIXED: PLAYER COUNT UPDATE METHOD ====================
    
    
    # ==================== FIXED: GAME READY METHOD ====================
    
    
    # ==================== FIXED: CARD REFUNDED METHOD ====================
    
    
    async def _handle_auth(self, ws: web.WebSocketResponse, data: dict, connection_id: str):
        """Handle authentication"""
        user_id = data.get('userId')
        if user_id:
            # Remove old connection for this user if exists
            old_ws = self.user_connections.get(str(user_id))
            if old_ws and old_ws != ws:
                try:
                    await old_ws.close(code=1000, reason="New login from different device")
                except:
                    pass
            
            self.user_connections[str(user_id)] = ws
            await self._safe_send_async(ws, {
                'type': 'auth_success',
                'message': f'Authenticated as user {user_id}',
                'user_id': user_id,
                'connection_id': connection_id
            })
            logger.info(f"User {user_id} authenticated via WebSocket from {connection_id}")
    
    async def _handle_client_sync(self, ws: web.WebSocketResponse, data: dict):
        """Handle client sync message with countdown"""
        try:
            user_id = data.get('user_id')
            game_id = data.get('game_id')
            client_countdown = data.get('countdown', 30)
            
            if not user_id or not game_id:
                return
            
            # Get server countdown
            server_countdown = await self.get_server_countdown_for_game(game_id)
            
            # Log any significant differences
            diff = abs(server_countdown - client_countdown)
            if diff > 2:  # If difference is more than 2 seconds
                logger.info(f"Countdown correction for game {game_id}: client {client_countdown}s, server {server_countdown}s")
            
            # Send correction if needed
            if diff > 5:  # If difference is more than 5 seconds
                await self.send_to_user(str(user_id), {
                    'type': 'countdown_correction',
                    'game_id': game_id,
                    'server_countdown': server_countdown,
                    'client_countdown': client_countdown,
                    'difference': diff,
                    'timestamp': datetime.now().isoformat()
                })
                
        except Exception as e:
            logger.error(f"Error handling client sync: {e}")
    
    # FIXED: New immediate bingo claim handler with 4 corners priority
    async def _handle_immediate_player_bingo_claim(self, data: dict):
        """Handle immediate bingo claim with priority for 4 corners"""
        game_id = data.get('game_id')
        user_id = data.get('user_id')
        
        if not game_id or not user_id:
            return
        
        # Use dedicated bingo claim lock to prevent race conditions
        async with self._bingo_claim_lock:
            try:
                from database.db import Database
                from utils.game_manager import game_manager
                
                logger.info(f"🚨 IMMEDIATE BINGO CLAIM from user {user_id} in game {game_id}")
                
                # Get game status immediately using game_manager
                game = await Database.get_game(game_id)
                if not game or game.get('status') != 'active':
                    logger.warning(f"Game {game_id} not active for bingo claim")
                    await self.send_to_user(str(user_id), {
                        'type': 'bingo_rejected',
                        'reason': 'Game not active',
                        'timestamp': datetime.now().isoformat()
                    })
                    return
                
                # Get user card
                user_card = await Database.get_user_card_in_game(int(user_id), game_id)
                if not user_card:
                    logger.warning(f"User {user_id} has no card in game {game_id}")
                    await self.send_to_user(str(user_id), {
                        'type': 'bingo_rejected',
                        'reason': 'No active card found',
                        'timestamp': datetime.now().isoformat()
                    })
                    return
                
                # Get called numbers
                called_numbers = await Database.get_drawn_numbers(game_id)
                
                # Use game_manager's fast verification with 4 corners priority
                has_bingo, winning_pattern, pattern_type = await game_manager._fast_verify_bingo_with_pattern(user_card, called_numbers)
                
                logger.info(f"⚡ BINGO VERIFICATION RESULT: User {user_id} - HasBingo: {has_bingo}, Pattern: {pattern_type}")
                
                if has_bingo:
                    logger.info(f"✅ IMMEDIATE BINGO VERIFIED: User {user_id}, Pattern: {pattern_type}")
                    
                    # Double-check game is still active
                    current_game = await Database.get_game(game_id)
                    if current_game and current_game.get('status') == 'active':
                        # Process winner through game_manager
                        winner_data = await game_manager.process_winner(game_id, int(user_id))
                        
                        if winner_data:
                            # Send confirmation to claimant
                            await self.send_to_user(str(user_id), {
                                'type': 'bingo_claim_verified',
                                'message': 'BINGO verified! You won!',
                                'prize_amount': winner_data.get('prize_amount', 0),
                                'pattern_type': pattern_type,
                                'winning_pattern': winning_pattern,
                                'timestamp': datetime.now().isoformat()
                            })
                            
                            # BROADCAST WINNER DISPLAY TO ALL PLAYERS
                            # Get full card data for broadcast
                            card_numbers = []
                            if user_card.get('card_numbers'):
                                card_data = user_card['card_numbers']
                                if isinstance(card_data, str):
                                    try:
                                        card_numbers = json.loads(card_data)
                                    except:
                                        card_numbers = []
                                elif isinstance(card_data, list):
                                    card_numbers = card_data
                            
                            # Add card numbers to winner data
                            winner_data['card_numbers'] = card_numbers
                            winner_data['winning_pattern'] = winning_pattern
                            winner_data['pattern_type'] = pattern_type
                            
                            # Broadcast to all clients
                            await self.broadcast_winner_display(game_id, winner_data)
                            
                            logger.info(f"🎉 BINGO WINNER PROCESSED: User {user_id} won with pattern {pattern_type}")
                        else:
                            logger.error(f"❌ Failed to process winner for user {user_id}")
                            await self.send_to_user(str(user_id), {
                                'type': 'bingo_rejected',
                                'reason': 'Failed to process winner',
                                'timestamp': datetime.now().isoformat()
                            })
                    else:
                        logger.warning(f"Game {game_id} no longer active during processing")
                        await self.send_to_user(str(user_id), {
                            'type': 'bingo_rejected',
                            'reason': 'Game no longer active',
                            'timestamp': datetime.now().isoformat()
                        })
                else:
                    logger.info(f"❌ No bingo found for user {user_id}")
                    await self.send_to_user(str(user_id), {
                        'type': 'bingo_rejected',
                        'reason': 'No valid bingo pattern found',
                        'timestamp': datetime.now().isoformat()
                    })
                        
            except Exception as e:
                logger.error(f"Error in immediate bingo claim: {e}", exc_info=True)
                await self.send_to_user(str(user_id), {
                    'type': 'bingo_rejected',
                    'reason': f'Server error: {str(e)[:100]}',
                    'timestamp': datetime.now().isoformat()
                })
    
    # FIXED: Updated original bingo claim handler to use immediate version
    async def _handle_player_bingo_claim(self, data: dict):
        """Validate bingo claim from frontend - uses immediate handler"""
        await self._handle_immediate_player_bingo_claim(data)
    
    async def _handle_countdown_complete(self, data: dict):
        """Handle countdown completion from frontend"""
        game_id = data.get('game_id')
        phase = data.get('phase')
        
        if not game_id or not phase:
            return
        
        try:
            from database.db import Database
            from utils.game_manager import game_manager
            
            # FIX: Use game_manager to get game state
            active_game = await game_manager.get_active_round_game()
            if not active_game or active_game.get('game_id') != game_id:
                return
            
            current_status = active_game.get('status', 'unknown')
            
            # Validate phase transition
            if phase == 'card_purchase' and current_status == 'card_purchase':
                # Start game play via game_manager
                await game_manager.start_game_play(game_id)
                
                logger.info(f"Game {game_id} transitioned to game_play phase via countdown completion")
                
            elif phase == 'winner_display':
                # FIX: Let game_manager handle scheduling new round
                # (Already handled in process_winner)
                pass
                
        except Exception as e:
            logger.error(f"Error handling countdown complete: {e}")
    
    async def _handle_phase_transition(self, data: dict):
        """Handle phase transition from frontend"""
        game_id = data.get('game_id')
        from_phase = data.get('from_phase')
        to_phase = data.get('to_phase')
        
        if not game_id or not from_phase or not to_phase:
            return
        
        try:
            from utils.game_manager import game_manager
            
            # FIX: Use game_manager to get active game
            active_game = await game_manager.get_active_round_game()
            if not active_game or active_game.get('game_id') != game_id:
                return
            
            current_status = active_game.get('status', 'unknown')
            
            # Validate transition
            valid_transitions = {
                'card_purchase': ['active'],
                'active': ['winner_display'],
                'winner_display': ['completed']
            }
            
            if (from_phase in valid_transitions and 
                to_phase in valid_transitions[from_phase]):
                
                # FIX: Use game_manager methods for transitions
                if to_phase == 'active':
                    await game_manager.start_game_play(game_id)
                elif to_phase == 'winner_display':
                    # Only game_manager should handle this via process_winner
                    pass
                elif to_phase == 'card_purchase':
                    # New round should be handled by game_manager._schedule_next_round
                    pass
                
                logger.info(f"Game {game_id} phase changed: {from_phase} -> {to_phase}")
            else:
                logger.warning(f"Invalid phase transition: {from_phase} -> {to_phase}")
                
        except Exception as e:
            logger.error(f"Error handling phase transition: {e}")
    
    async def _schedule_new_round(self, game_id: str):
        """Schedule new round after winner display - FIXED: Use game_manager"""
        try:
            # FIX: Let game_manager handle this internally
            # This method is kept for compatibility but should not be called directly
            logger.debug(f"New round scheduling for {game_id} should be handled by game_manager")
                
        except Exception as e:
            logger.error(f"Error scheduling new round: {e}")
    
    async def _handle_new_round_started(self, data: dict):
        """Handle new round started by frontend - FIXED: Use game_manager"""
        game_id = data.get('game_id')
        
        if not game_id:
            return
        
        try:
            from utils.game_manager import game_manager
            
            # FIX: Verify this is the active game
            active_game = await game_manager.get_active_round_game()
            if active_game and active_game.get('game_id') == game_id:
                # Game is already active, nothing to do
                return
            
            # If not active, start a new round
            await game_manager.start_new_round_game()
            
            logger.info(f"New round started for game {game_id}")
            
        except Exception as e:
            logger.error(f"Error handling new round: {e}")
    
    async def _handle_request_sync(self, data: dict):
        """Handle sync request from client"""
        game_id = data.get('game_id')
        user_id = data.get('user_id')
        
        if not game_id or not user_id:
            return
        
        try:
            from database.db import Database
            from utils.game_manager import game_manager
            
            # FIX: Get game from game_manager first
            active_game = await game_manager.get_active_round_game()
            
            if not active_game or active_game.get('game_id') != game_id:
                # Game not active, send sync response with no active game
                await self.send_to_user(str(user_id), {
                    'type': 'sync_response',
                    'game_id': game_id,
                    'server_state': None,
                    'message': 'Game not active',
                    'has_active_game': False
                })
                return
            
            # Calculate server countdown using game_manager - FIXED
            game_status = await game_manager.get_game_status(game_id)
            
            if not game_status.get('success'):
                await self.send_to_user(str(user_id), {
                    'type': 'sync_response',
                    'game_id': game_id,
                    'server_state': None,
                    'message': game_status.get('message', 'Error getting game status') 
                })
                return
            
            # FIX: Get correct countdown from game_status
            server_countdown = game_status.get('countdown_remaining', 30)
            
            server_called = await Database.get_drawn_numbers(game_id)
            server_player_count = await Database.count_game_players(game_id)
            server_prize_pool = float(active_game.get('prize_pool', 0))
            
            # Prepare sync response
            server_state = {
                'game_phase': game_status.get('phase', 'unknown'),
                'game_status': game_status.get('status', 'unknown'),
                'called_numbers': server_called,
                'player_count': server_player_count,
                'prize_pool': server_prize_pool,
                'game_active': game_status.get('status') == 'active',
                'countdown_remaining': server_countdown,  # FIXED: Use from game_status
                'total_cards': await Database.count_sold_cards(game_id),
                'current_number': active_game.get('current_number'),
                'round_number': active_game.get('round_number', 1),
                'card_price': float(active_game.get('card_price', 10.00)),
                'has_winner': game_status.get('status') == 'winner_display',
                'is_active_game': True
            }
            
            await self.send_to_user(str(user_id), {
                'type': 'sync_response',
                'game_id': game_id,
                'server_state': server_state,
                'timestamp': datetime.now().isoformat(),
                'has_active_game': True
            })
            
        except Exception as e:
            logger.error(f"Error handling sync request: {e}")
            await self.send_to_user(str(user_id), {
                'type': 'sync_response',
                'game_id': game_id,
                'server_state': None,
                'message': f'Sync error: {str(e)}'
            })
    
    async def _calculate_server_countdown(self, game: dict) -> int:
        """Calculate countdown based on game timestamps - FIXED"""
        try:
            from utils.game_manager import game_manager
            
            game_id = game.get('game_id')
            if not game_id:
                return 30  # Default
            
            # FIX: Use game_manager's get_game_status for consistent countdown
            game_status = await game_manager.get_game_status(game_id)
            if game_status.get('success'):
                return game_status.get('countdown_remaining', 30)
            
            # Fallback to old logic if game_manager fails
            status = game.get('status', 'unknown')
            
            if status == 'card_purchase':
                # Check purchase_end_time
                purchase_end = game.get('purchase_end_time')
                if purchase_end:
                    if isinstance(purchase_end, str):
                        try:
                            from dateutil.parser import parse
                            purchase_end = parse(purchase_end)
                        except:
                            return 30
                    
                    now = datetime.now()
                    remaining = (purchase_end - now).total_seconds()
                    return max(0, int(remaining))
                
                # Fallback to countdown_remaining
                countdown = game.get('countdown_remaining')
                if countdown is not None:
                    return max(0, countdown)
                
                return 30  # Default
            
            elif status == 'winner_display':
                # Winner display lasts 5 seconds
                winner_display_start = game.get('last_phase_change') or game.get('completed_at')
                if winner_display_start:
                    if isinstance(winner_display_start, str):
                        try:
                            from dateutil.parser import parse
                            winner_display_start = parse(winner_display_start)
                        except:
                            return 5
                    
                    now = datetime.now()
                    elapsed = (now - winner_display_start).total_seconds()
                    return max(0, 5 - int(elapsed))
                
                return 5  # Default
            
            elif status == 'active':
                # For active games, no countdown needed
                return 0
            
            else:
                return 30
        
        except Exception as e:
            logger.error(f"Error calculating countdown: {e}")
            return 30  # Default
    
    async def get_server_countdown_for_game(self, game_id: str) -> int:
        """Get server countdown for a specific game - FIXED"""
        try:
            from utils.game_manager import game_manager
            game_status = await game_manager.get_game_status(game_id)
            if game_status.get('success'):
                return game_status.get('countdown_remaining', 30)
            return 30
        except Exception as e:
            logger.error(f"Error getting server countdown: {e}")
            return 30
    
    async def _handle_ping(self, ws: web.WebSocketResponse):
        """Handle ping request"""
        await self._safe_send_async(ws, {
            'type': 'pong',
            'timestamp': datetime.now().isoformat()
        })
    
    async def _handle_get_active_game(self, ws: web.WebSocketResponse):
        """NEW: Handle request for active game info"""
        try:
            from utils.game_manager import game_manager
            active_game = await game_manager.get_active_round_game()
            
            if active_game:
                # Get countdown from game_manager for consistency
                game_status = await game_manager.get_game_status(active_game.get('game_id'))
                countdown = game_status.get('countdown_remaining', 30) if game_status.get('success') else 30
                
                await self._safe_send_async(ws, {
                    'type': 'active_game_info',
                    'game_id': active_game.get('game_id'),
                    'status': active_game.get('status', 'card_purchase'),
                    'phase': active_game.get('current_phase', 'card_purchase'),
                    'round_number': active_game.get('round_number', 1),
                    'prize_pool': float(active_game.get('prize_pool', 0)),
                    'countdown_remaining': countdown,  # Add countdown to response
                    'timestamp': datetime.now().isoformat()
                })
            else:
                await self._safe_send_async(ws, {
                    'type': 'no_active_game',
                    'message': 'No active game found',
                    'timestamp': datetime.now().isoformat()
                })
        except Exception as e:
            logger.error(f"Error handling get_active_game: {e}")
            await self._safe_send_async(ws, {
                'type': 'error',
                'message': f'Error getting active game: {str(e)}',
                'timestamp': datetime.now().isoformat()
            })
    
    # NEW: Test bingo verification endpoint
    async def _handle_test_bingo(self, data: dict, connection_id: str):
        """Test bingo verification for debugging"""
        try:
            from utils.game_manager import game_manager
            from database.db import Database
            
            game_id = data.get('game_id')
            user_id = data.get('user_id')
            
            if not game_id or not user_id:
                await self.send_to_user(connection_id, {
                    'type': 'test_bingo_result',
                    'error': 'Missing game_id or user_id'
                })
                return
            
            # Get user card
            user_card = await Database.get_user_card_in_game(int(user_id), game_id)
            if not user_card:
                await self.send_to_user(connection_id, {
                    'type': 'test_bingo_result',
                    'error': 'No card found'
                })
                return
            
            # Get called numbers
            called_numbers = await Database.get_drawn_numbers(game_id)
            
            # Test fast verification
            start_time = time.time()
            has_bingo, winning_pattern, pattern_type = await game_manager._fast_verify_bingo_with_pattern(user_card, called_numbers)
            verification_time = time.time() - start_time
            
            # Get card numbers
            card_numbers = []
            if user_card.get('card_numbers'):
                card_numbers_data = user_card['card_numbers']
                if isinstance(card_numbers_data, str):
                    try:
                        card_numbers = json.loads(card_numbers_data)
                    except:
                        pass
                elif isinstance(card_numbers_data, list):
                    card_numbers = card_numbers_data
            
            # Get corner numbers
            corner_numbers = []
            if len(card_numbers) >= 25:
                corner_indices = [0, 4, 20, 24]
                corner_numbers = [card_numbers[i] for i in corner_indices]
            
            await self.send_to_user(connection_id, {
                'type': 'test_bingo_result',
                'has_bingo': has_bingo,
                'pattern_type': pattern_type,
                'winning_pattern': winning_pattern,
                'verification_time_ms': verification_time * 1000,
                'card_numbers': card_numbers,
                'corner_numbers': corner_numbers,
                'called_numbers_count': len(called_numbers),
                'corner_indices': [0, 4, 20, 24],
                'message': f"Verification took {verification_time*1000:.1f}ms"
            })
            
        except Exception as e:
            logger.error(f"Error in test bingo: {e}")
            await self.send_to_user(connection_id, {
                'type': 'test_bingo_result',
                'error': str(e)
            })
    
    async def _check_bingo(self, user_card, called_numbers):
        """Check if user card has bingo - OPTIMIZED for LIGHTNING SPEED"""
        try:
            card_numbers = []
            
            # Debug logging
            logger.debug(f"Card data type: {type(user_card.get('card_data'))}")
            logger.debug(f"Card data: {user_card.get('card_data')}")
            logger.debug(f"Card numbers type: {type(user_card.get('card_numbers'))}")
            logger.debug(f"Card numbers: {user_card.get('card_numbers')}")
            
            # Try to parse card numbers from different formats
            if user_card.get('card_data'):
                card_data = user_card['card_data']
                if isinstance(card_data, str):
                    try:
                        card_data = json.loads(card_data)
                    except json.JSONDecodeError:
                        logger.error(f"Failed to parse card_data as JSON: {card_data}")
                
                # Handle parsed card_data
                if isinstance(card_data, list):
                    card_numbers = card_data
                elif isinstance(card_data, dict):
                    if 'numbers' in card_data:
                        card_numbers = card_data['numbers']
                    elif 'grid' in card_data:
                        # Flatten 5x5 grid
                        for row in card_data['grid']:
                            card_numbers.extend(row)
                    else:
                        logger.error(f"Unknown card_data dict format: {card_data}")
                else:
                    logger.error(f"Unexpected card_data type after parsing: {type(card_data)}")
            
            elif user_card.get('card_numbers'):
                card_numbers_data = user_card['card_numbers']
                if isinstance(card_numbers_data, str):
                    try:
                        card_numbers = json.loads(card_numbers_data)
                    except json.JSONDecodeError:
                        logger.error(f"Failed to parse card_numbers as JSON: {card_numbers_data}")
                elif isinstance(card_numbers_data, list):
                    card_numbers = card_numbers_data
                elif isinstance(card_numbers_data, dict):
                    if 'numbers' in card_numbers_data:
                        card_numbers = card_numbers_data['numbers']
                    elif 'grid' in card_numbers_data:
                        # Flatten 5x5 grid
                        for row in card_numbers_data['grid']:
                            card_numbers.extend(row)
                    else:
                        logger.error(f"Unknown card_numbers dict format: {card_numbers_data}")
                else:
                    logger.error(f"Unexpected card_numbers type: {type(card_numbers_data)}")
            
            # If still no card numbers, try to extract from the whole user_card
            if not card_numbers:
                logger.error(f"No card numbers found in user_card: {user_card}")
                return False
            
            # Ensure we have 25 numbers (5x5 grid)
            if len(card_numbers) != 25:
                logger.error(f"Invalid card length: {len(card_numbers)}. Expected 25.")
                logger.debug(f"Card numbers: {card_numbers}")
                return False
            
            # Convert to 5x5 grid
            grid = []
            for i in range(0, 25, 5):
                grid.append(card_numbers[i:i+5])
            
            # Create a set for O(1) lookups - LIGHTNING FAST
            called_set = set(called_numbers)
            
            # Check rows (including FREE space in center)
            for row in range(5):
                complete = True
                for col in range(5):
                    num = grid[row][col]
                    # Center is FREE (index 12 in 1D, [2][2] in 2D)
                    if row == 2 and col == 2:
                        continue  # FREE space is always considered marked
                    if num is None or num == 0 or num not in called_set:
                        complete = False
                        break
                if complete:
                    logger.info(f"BINGO found in row {row}")
                    return True
            
            # Check columns
            for col in range(5):
                complete = True
                for row in range(5):
                    num = grid[row][col]
                    if row == 2 and col == 2:
                        continue  # FREE space
                    if num is None or num == 0 or num not in called_set:
                        complete = False
                        break
                if complete:
                    logger.info(f"BINGO found in column {col}")
                    return True
            
            # Check main diagonal (top-left to bottom-right)
            diag1_complete = True
            for i in range(5):
                if i == 2:
                    continue  # Center FREE space
                num = grid[i][i]
                if num is None or num == 0 or num not in called_set:
                    diag1_complete = False
                    break
            if diag1_complete:
                logger.info("BINGO found in main diagonal")
                return True
            
            # Check anti-diagonal (top-right to bottom-left)
            diag2_complete = True
            for i in range(5):
                if i == 2:
                    continue  # Center FREE space
                num = grid[i][4-i]
                if num is None or num == 0 or num not in called_set:
                    diag2_complete = False
                    break
            if diag2_complete:
                logger.info("BINGO found in anti-diagonal")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error checking bingo: {e}", exc_info=True)
            return False
    
    async def _check_bingo_with_pattern(self, user_card, called_numbers):
        """Check if user card has bingo and return winning pattern"""
        try:
            card_numbers = []
            
            # Parse card numbers from different formats
            if user_card.get('card_data'):
                card_data = user_card['card_data']
                if isinstance(card_data, str):
                    try:
                        card_data = json.loads(card_data)
                    except json.JSONDecodeError:
                        logger.error(f"Failed to parse card_data as JSON: {card_data}")
                
                # Handle parsed card_data
                if isinstance(card_data, list):
                    card_numbers = card_data
                elif isinstance(card_data, dict):
                    if 'numbers' in card_data:
                        card_numbers = card_data['numbers']
                    elif 'grid' in card_data:
                        # Flatten 5x5 grid
                        for row in card_data['grid']:
                            card_numbers.extend(row)
                    else:
                        logger.error(f"Unknown card_data dict format: {card_data}")
                else:
                    logger.error(f"Unexpected card_data type after parsing: {type(card_data)}")
            
            elif user_card.get('card_numbers'):
                card_numbers_data = user_card['card_numbers']
                if isinstance(card_numbers_data, str):
                    try:
                        card_numbers = json.loads(card_numbers_data)
                    except json.JSONDecodeError:
                        logger.error(f"Failed to parse card_numbers as JSON: {card_numbers_data}")
                elif isinstance(card_numbers_data, list):
                    card_numbers = card_numbers_data
                elif isinstance(card_numbers_data, dict):
                    if 'numbers' in card_numbers_data:
                        card_numbers = card_numbers_data['numbers']
                    elif 'grid' in card_numbers_data:
                        # Flatten 5x5 grid
                        for row in card_numbers_data['grid']:
                            card_numbers.extend(row)
                    else:
                        logger.error(f"Unknown card_numbers dict format: {card_numbers_data}")
                else:
                    logger.error(f"Unexpected card_numbers type: {type(card_numbers_data)}")
            
            # If still no card numbers, try to extract from the whole user_card
            if not card_numbers:
                logger.error(f"No card numbers found in user_card: {user_card}")
                return False, []
            
            # Ensure we have 25 numbers (5x5 grid)
            if len(card_numbers) != 25:
                logger.error(f"Invalid card length: {len(card_numbers)}. Expected 25.")
                return False, []
            
            # Convert to 5x5 grid
            grid = []
            for i in range(0, 25, 5):
                grid.append(card_numbers[i:i+5])
            
            # Create a set for O(1) lookups
            called_set = set(called_numbers)
            
            # Check rows (including FREE space in center)
            for row in range(5):
                complete = True
                winning_numbers = []
                for col in range(5):
                    num = grid[row][col]
                    # Center is FREE (index 12 in 1D, [2][2] in 2D)
                    if row == 2 and col == 2:
                        winning_numbers.append(0)  # Include FREE in winning pattern
                        continue  # FREE space is always considered marked
                    if num is None or num == 0 or num not in called_set:
                        complete = False
                        break
                    winning_numbers.append(num)
                if complete:
                    logger.info(f"BINGO found in row {row}: {winning_numbers}")
                    return True, winning_numbers
            
            # Check columns
            for col in range(5):
                complete = True
                winning_numbers = []
                for row in range(5):
                    num = grid[row][col]
                    if row == 2 and col == 2:
                        winning_numbers.append(0)  # Include FREE in winning pattern
                        continue  # FREE space
                    if num is None or num == 0 or num not in called_set:
                        complete = False
                        break
                    winning_numbers.append(num)
                if complete:
                    logger.info(f"BINGO found in column {col}: {winning_numbers}")
                    return True, winning_numbers
            
            # Check main diagonal (top-left to bottom-right)
            diag1_complete = True
            winning_numbers = []
            for i in range(5):
                if i == 2:
                    winning_numbers.append(0)  # Include FREE in winning pattern
                    continue  # Center FREE space
                num = grid[i][i]
                if num is None or num == 0 or num not in called_set:
                    diag1_complete = False
                    break
                winning_numbers.append(num)
            if diag1_complete:
                logger.info(f"BINGO found in main diagonal: {winning_numbers}")
                return True, winning_numbers
            
            # Check anti-diagonal (top-right to bottom-left)
            diag2_complete = True
            winning_numbers = []
            for i in range(5):
                if i == 2:
                    winning_numbers.append(0)  # Include FREE in winning pattern
                    continue  # Center FREE space
                num = grid[i][4-i]
                if num is None or num == 0 or num not in called_set:
                    diag2_complete = False
                    break
                winning_numbers.append(num)
            if diag2_complete:
                logger.info(f"BINGO found in anti-diagonal: {winning_numbers}")
                return True, winning_numbers
            
            return False, []
            
        except Exception as e:
            logger.error(f"Error checking bingo: {e}", exc_info=True)
            return False, []
    
    async def _safe_send_async(self, ws: web.WebSocketResponse, message: dict) -> bool:
        """Safely send message"""
        try:
            if ws.closed:
                return False
            
            message_json = json.dumps(self.convert_to_json_serializable(message), cls=CustomJSONEncoder)
            
            await ws.send_str(message_json)
            return True
                
        except Exception as e:
            logger.debug(f"Error sending message: {e}")
            return False
    
    async def broadcast_with_retry(self, message: dict, max_retries: int = 3):
        """
        Broadcast message to all connections simultaneously using gather.
        FIXED: Replaced sequential loop with concurrent tasks.
        """
        if not self.connections:
            return True
    
        try:
        # Serialize once to save CPU cycles during the broadcast
            message_json = json.dumps(
                self.convert_to_json_serializable(message), 
                cls=CustomJSONEncoder
            )
        except Exception as e:
            logger.error(f"Error converting message to JSON: {e}")
            return False
    
    # Define a helper to handle individual sends so we can catch 
    # errors per-user without stopping the whole broadcast
        async def send_to_one(ws):
            try:
                if not ws.closed:
                    await ws.send_str(message_json)
                    return None # Success
                return ws # Mark for removal
            except Exception as e:
                logger.debug(f"Individual send error: {e}")
                return ws # Mark for removal

    # 1. Create a task for every active connection
        tasks = [send_to_one(ws) for ws in list(self.connections)]
    
    # 2. Execute ALL sends at once
    # return_exceptions=True prevents one crash from stopping other broadcasts
        results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # 3. Clean up disconnected sockets (those that returned themselves)
        disconnected = {res for res in results if isinstance(res, (type(None).__class__, object)) and res is not None}
    
        if disconnected:
            for ws in disconnected:
            # Check if it's actually a websocket object before discarding
                if hasattr(ws, 'closed'):
                    self.connections.discard(ws)
                # Cleanup user mapping
                    for user_id, connection_ws in list(self.user_connections.items()):
                        if connection_ws == ws:
                            del self.user_connections[user_id]
                            break
    
        return True
    
    async def send_to_user(self, user_id: str, message: dict) -> bool:
        """Send message to specific user"""
        try:
            ws = self.user_connections.get(str(user_id))
            if ws:
                return await self._safe_send_async(ws, message)
            return False
        except Exception as e:
            logger.error(f"Error sending to user {user_id}: {e}")
            return False
    
    def convert_to_json_serializable(self, obj):
        """Convert objects to JSON-serializable format"""
        if isinstance(obj, dict):
            return {k: self.convert_to_json_serializable(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self.convert_to_json_serializable(v) for v in obj]
        elif isinstance(obj, (datetime, date)):
            return obj.isoformat()
        elif isinstance(obj, decimal.Decimal):
            return float(obj)
        elif hasattr(obj, '__dict__'):
            return self.convert_to_json_serializable(obj.__dict__)
        else:
            return obj

# Create global WebSocket server instance
websocket_server = ValidationWebSocketServer()

# ==================== CUSTOM JSON ENCODER ====================
class CustomJSONEncoder(json.JSONEncoder):
    """Custom JSON encoder that handles Decimal and Datetime objects"""
    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        if isinstance(obj, decimal.Decimal):
            return float(obj)
        return super(CustomJSONEncoder, self).default(obj)

# ==================== HELPER FUNCTIONS ====================
def convert_to_json_serializable(obj):
    """Recursively convert objects to JSON-serializable format"""
    if isinstance(obj, dict):
        return {k: convert_to_json_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_to_json_serializable(v) for v in obj]
    elif isinstance(obj, (datetime, date)):
        return obj.isoformat()
    elif isinstance(obj, decimal.Decimal):
        return float(obj)
    elif hasattr(obj, '__dict__'):
        return convert_to_json_serializable(obj.__dict__)
    else:
        return obj

def parse_user_id(user_id_str):
    """Parse user ID from string"""
    try:
        if isinstance(user_id_str, (int, float)):
            return int(user_id_str)
        
        if isinstance(user_id_str, str):
            if user_id_str.startswith('telegram_'):
                return int(user_id_str.replace('telegram_', ''))
            elif user_id_str.startswith('user_'):
                try:
                    return int(user_id_str.replace('user_', ''))
                except:
                    return random.randint(1000000, 9999999)
            else:
                return int(user_id_str)
        
        return random.randint(1000000, 9999999)
    except (ValueError, AttributeError, TypeError):
        return random.randint(1000000, 9999999)

# ==================== CORS MIDDLEWARE ====================
@web.middleware
async def cors_middleware(request, handler):
    """CORS middleware to allow cross-origin requests"""
    if request.method == 'OPTIONS':
        response = web.Response()
    else:
        response = await handler(request)
    
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, *'
    response.headers['Access-Control-Allow-Credentials'] = 'true'
    response.headers['Access-Control-Max-Age'] = '86400'
    
    return response

# Create routes
routes = web.RouteTableDef()

# ==================== DATABASE INITIALIZATION ====================
async def init_commission_table():
    """Initialize commission_records table if it doesn't exist"""
    try:
        from database.db import Database
        with Database.get_cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS commission_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    game_id TEXT NOT NULL,
                    commission_amount REAL NOT NULL,
                    real_players_count INTEGER NOT NULL,
                    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status TEXT DEFAULT 'recorded',
                    FOREIGN KEY (game_id) REFERENCES games(game_id)
                )
            """)
            logger.info("✅ commission_records table initialized")
    except Exception as e:
            logger.error(f"Error initializing commission_records table: {e}")

# ==================== FIXED ADMIN API ENDPOINTS ====================

@routes.get('/api/admin/totalbalance')
async def admin_total_balance(request):
    """Get total balance of all real users only (excluding fake players) - FIXED"""
    try:
        from database.db import Database
        
        with Database.get_cursor() as cursor:
            # First, try to exclude using fake_players table
            try:
                cursor.execute("""
                    SELECT COALESCE(SUM(balance), 0) as total_balance 
                    FROM users 
                    WHERE balance > 0 
                    AND deleted_at IS NULL
                    AND user_id NOT IN (
                        SELECT user_id FROM fake_players
                    )
                """)
                row = cursor.fetchone()
                total_balance = float(row[0] or 0) if row else 0
                
                # Get count of real users
                cursor.execute("""
                    SELECT COUNT(*) as real_user_count
                    FROM users 
                    WHERE deleted_at IS NULL
                    AND user_id NOT IN (
                        SELECT user_id FROM fake_players
                    )
                """)
                count_row = cursor.fetchone()
                real_user_count = count_row[0] if count_row else 0
                
                logger.info(f"💰 Total balance (using fake_players table): {total_balance} birr (from {real_user_count} real users)")
                
            except Exception as e:
                logger.warning(f"fake_players table not found, using fallback: {e}")
                # Fallback if fake_players table doesn't exist
                # Since there's no is_fake column, we need another way to identify fake users
                # Fake users typically have very high user_ids (>= 1000000) or usernames starting with "fake_"
                cursor.execute("""
                    SELECT COALESCE(SUM(balance), 0) as total_balance 
                    FROM users 
                    WHERE balance > 0 
                    AND deleted_at IS NULL
                    AND user_id < 1000000
                    AND (username NOT LIKE 'fake_%' OR username IS NULL)
                """)
                row = cursor.fetchone()
                total_balance = float(row[0] or 0) if row else 0
                
                # Get count of real users
                cursor.execute("""
                    SELECT COUNT(*) as real_user_count
                    FROM users 
                    WHERE deleted_at IS NULL
                    AND user_id < 1000000
                    AND (username NOT LIKE 'fake_%' OR username IS NULL)
                """)
                count_row = cursor.fetchone()
                real_user_count = count_row[0] if count_row else 0
                
                logger.info(f"💰 Total balance (using fallback): {total_balance} birr (from {real_user_count} real users)")
            
            return web.json_response({
                'success': True,
                'total_balance': total_balance,
                'currency': 'birr',
                'real_user_count': real_user_count,
                'timestamp': datetime.now().isoformat()
            })
            
    except Exception as e:
        logger.error(f"Error getting total balance: {e}")
        return web.json_response({
            'success': False,
            'message': str(e)
        }, status=500)


# ==================== FIXED ADMIN WEEKLY REVENUE ENDPOINT ====================
@routes.get('/api/admin/weeklyrevenue')
async def admin_weekly_revenue(request):
    """Get weekly revenue data with 20% commission - FIXED: Uses commission_records table"""
    try:
        from database.db import Database
        
        with Database.get_cursor() as cursor:
            # Get weekly commission data from commission_records table
            cursor.execute("""
                SELECT 
                    strftime('%Y-%W', recorded_at) as week_number,
                    MIN(recorded_at) as start_date,
                    MAX(recorded_at) as end_date,
                    COUNT(*) as games_count,
                    SUM(real_players_count) as total_real_players,
                    SUM(commission_amount) as commission
                FROM commission_records 
                GROUP BY strftime('%Y-%W', recorded_at)
                ORDER BY week_number DESC
                LIMIT 10
            """)
            rows = cursor.fetchall()
            
            weekly_data = []
            total_commission_from_query = 0
            
            for row in rows:
                week_data = {
                    'week': row[0],
                    'start_date': row[1],
                    'end_date': row[2],
                    'games_count': row[3] or 0,
                    'total_real_players': row[4] or 0,
                    'commission': float(row[5] or 0)
                }
                weekly_data.append(week_data)
                total_commission_from_query += week_data['commission']
            
            # Calculate summary stats
            this_week_commission = weekly_data[0]['commission'] if weekly_data else 0
            last_week_commission = weekly_data[1]['commission'] if len(weekly_data) > 1 else 0
            
            # This month - calculate separately
            current_year_month = datetime.now().strftime('%Y-%m')
            cursor.execute("""
                SELECT COALESCE(SUM(commission_amount), 0) as month_commission
                FROM commission_records 
                WHERE strftime('%Y-%m', recorded_at) = ?
            """, (current_year_month,))
            month_row = cursor.fetchone()
            this_month_commission = float(month_row[0] or 0) if month_row else 0
            
            # Get total commission from commission_records
            cursor.execute("""
                SELECT COALESCE(SUM(commission_amount), 0) as total_commission
                FROM commission_records
            """)
            total_row = cursor.fetchone()
            total_commission = float(total_row[0] or 0) if total_row else 0
            
            # Also get from house_balance table for verification
            cursor.execute("""
                SELECT COALESCE(SUM(amount), 0) as house_commission
                FROM house_balance 
                WHERE transaction_type = 'game_commission'
            """)
            house_row = cursor.fetchone()
            house_commission = float(house_row[0] or 0) if house_row else 0
            
            logger.info(f"📊 Commission verification: Commission_records: {total_commission} birr, House balance: {house_commission} birr")
            
            return web.json_response({
                'success': True,
                'weekly_data': weekly_data,
                'this_week_commission': this_week_commission,
                'last_week_commission': last_week_commission,
                'this_month_commission': this_month_commission,
                'total_commission': total_commission,
                'house_balance_commission': house_commission,
                'summary': {
                    'this_week_revenue': this_week_commission,
                    'last_week_revenue': last_week_commission,
                    'this_month_revenue': this_month_commission,
                    'total_commission': total_commission
                },
                'calculation_method': 'real_players × 2 (from commission_records table)',
                'timestamp': datetime.now().isoformat()
            })
            
    except Exception as e:
        logger.error(f"Error getting weekly revenue: {e}")
        return web.json_response({
            'success': False,
            'message': str(e),
            'weekly_data': [],
            'this_week_commission': 0,
            'last_week_commission': 0,
            'this_month_commission': 0,
            'total_commission': 0
        })


@routes.get('/api/admin/weeklycommission')
async def admin_weekly_commission(request):
    """Get weekly commission data - ALIAS for weeklyrevenue with correct calculation"""
    return await admin_weekly_revenue(request)


# ==================== FIXED ADMIN STATS ENDPOINT ====================
@routes.get('/api/admin/stats')
async def admin_stats(request):
    """Get admin statistics - FIXED to use commission_records table"""
    try:
        from database.db import Database
        from utils.game_manager import game_manager
        
        # Get total games
        total_games = await Database.get_total_games()
        
        # Get active games
        try:
            active_game = await game_manager.get_active_round_game()
            active_games_count = 1 if active_game else 0
        except Exception as e:
            logger.warning(f"Error getting active games: {e}")
            active_games_count = 0
        
        # Get total users
        total_users = await Database.get_total_users()
        
        # FIXED: Get today's commission from commission_records
        today_revenue = 0
        try:
            with Database.get_cursor() as cursor:
                cursor.execute("""
                    SELECT COALESCE(SUM(commission_amount), 0) as today_commission
                    FROM commission_records 
                    WHERE date(recorded_at) = date('now', 'localtime')
                """)
                row = cursor.fetchone()
                today_revenue = float(row[0] or 0) if row else 0
        except Exception as e:
            logger.warning(f"Error getting today's revenue: {e}")
        
        # FIXED: Get total revenue from commission_records
        total_revenue = 0
        try:
            with Database.get_cursor() as cursor:
                cursor.execute("""
                    SELECT COALESCE(SUM(commission_amount), 0) as total_commission
                    FROM commission_records
                """)
                row = cursor.fetchone()
                total_revenue = float(row[0] or 0) if row else 0
        except Exception as e:
            logger.warning(f"Error getting total revenue: {e}")
        
        # FIXED: Get this week's commission
        this_week_commission = 0
        try:
            with Database.get_cursor() as cursor:
                cursor.execute("""
                    SELECT COALESCE(SUM(commission_amount), 0) as week_commission
                    FROM commission_records 
                    WHERE recorded_at >= datetime('now', '-7 days')
                """)
                row = cursor.fetchone()
                this_week_commission = float(row[0] or 0) if row else 0
        except Exception as e:
            logger.warning(f"Error getting week commission: {e}")
        
        # Get total users balance - FIXED: Only real users with fallback
        total_balance = 0
        try:
            with Database.get_cursor() as cursor:
                # Try with fake_players table first
                try:
                    cursor.execute("""
                        SELECT COALESCE(SUM(balance), 0) as total_balance 
                        FROM users 
                        WHERE balance > 0 
                        AND user_id NOT IN (SELECT user_id FROM fake_players)
                        AND user_id < 1000000
                    """)
                    row = cursor.fetchone()
                    total_balance = float(row[0] or 0) if row else 0
                except:
                    # Fallback to all users if fake_players table doesn't exist
                    cursor.execute("""
                        SELECT COALESCE(SUM(balance), 0) as total_balance 
                        FROM users 
                        WHERE balance > 0 AND user_id < 1000000
                    """)
                    row = cursor.fetchone()
                    total_balance = float(row[0] or 0) if row else 0
        except Exception as e:
            logger.warning(f"Error getting total balance: {e}")
        
        # ========== FIXED: Calculate correct prize pool for active game ==========
        correct_prize_pool = 0
        if active_game:
            real_players = await Database.count_game_players(active_game.get('game_id'))
            fake_players = len(game_manager.fake_user_manager.game_fake_cards.get(active_game.get('game_id'), {}))
            total_players = real_players + fake_players
            correct_prize_pool = total_players * 8  # 8 birr per player
            logger.info(f"💰 Correct prize pool calculation: {total_players} players × 8 = {correct_prize_pool}")
        
        # Get recent transactions
        recent_transactions = await Database.get_recent_transactions(10)
        
        # Get system status
        system_status = await game_manager.get_system_status() if hasattr(game_manager, 'get_system_status') else {}
        
        stats = {
            'success': True,
            'stats': {
                'total_games': total_games,
                'active_games': active_games_count,
                'total_users': total_users,
                'today_revenue': float(today_revenue or 0),
                'total_revenue': float(total_revenue or 0),
                'total_balance': total_balance,
                'this_week_commission': this_week_commission,
                'online_players': len(websocket_server.user_connections),
                'has_active_game': active_game is not None,
                'current_prize_pool': correct_prize_pool,
                'correct_prize_pool': correct_prize_pool,
                'commission_source': 'commission_records'
            },
            'recent_transactions': recent_transactions,
            'system_status': system_status,
            'timestamp': datetime.now().isoformat()
        }
        
        return web.json_response(
            convert_to_json_serializable(stats),
            dumps=lambda obj: json.dumps(obj, cls=CustomJSONEncoder)
        )
        
    except Exception as e:
        logger.error(f"Error getting admin stats: {e}")
        return web.json_response({
            'success': False,
            'message': str(e)
        }, status=500)


@routes.post('/api/admin/suspenduser')
async def admin_suspend_user(request):
    """Admin: Suspend/unsuspend a user"""
    try:
        data = await request.json()
        user_id = data.get('user_id')
        action = data.get('action', 'suspend')  # 'suspend' or 'unsuspend'
        
        if not user_id:
            return web.json_response({
                'success': False,
                'message': 'user_id is required'
            }, status=400)
        
        from database.db import Database
        
        # Parse user ID
        parsed_user_id = parse_user_id(str(user_id))
        
        # Get user
        user = await Database.get_user(parsed_user_id)
        if not user:
            return web.json_response({
                'success': False,
                'message': 'User not found'
            }, status=404)
        
        # Update user status
        new_status = 'suspended' if action == 'suspend' else 'active'
        
        with Database.get_cursor() as cursor:
            cursor.execute("""
                UPDATE users 
                SET status = ?, updated_at = ?
                WHERE user_id = ?
            """, (new_status, datetime.now(), parsed_user_id))
        
        # Record admin transaction
        await Database.record_admin_transaction(
            admin_id=data.get('admin_id', 'system'),
            action=f'{action}_user',
            target_type='user',
            target_id=str(parsed_user_id),
            details={
                'previous_status': user.get('status', 'active'),
                'new_status': new_status,
                'username': user.get('username'),
                'reason': data.get('reason', '')
            }
        )
        
        return web.json_response({
            'success': True,
            'message': f'User {parsed_user_id} {action}ed successfully',
            'user_id': parsed_user_id,
            'action': action,
            'new_status': new_status
        })
        
    except Exception as e:
        logger.error(f"Error {action}ing user: {e}")
        return web.json_response({
            'success': False,
            'message': str(e)
        }, status=500)

@routes.post('/api/admin/deleteuser')
async def admin_delete_user(request):
    """Admin: Delete a user (soft delete)"""
    try:
        data = await request.json()
        user_id = data.get('user_id')
        
        if not user_id:
            return web.json_response({
                'success': False,
                'message': 'user_id is required'
            }, status=400)
        
        from database.db import Database
        
        # Parse user ID
        parsed_user_id = parse_user_id(str(user_id))
        
        # Get user
        user = await Database.get_user(parsed_user_id)
        if not user:
            return web.json_response({
                'success': False,
                'message': 'User not found'
            }, status=404)
        
        # Soft delete user (mark as deleted)
        with Database.get_cursor() as cursor:
            cursor.execute("""
                UPDATE users 
                SET status = 'deleted', 
                    deleted_at = ?,
                    updated_at = ?
                WHERE user_id = ?
            """, (datetime.now(), datetime.now(), parsed_user_id))
        
        # Record admin transaction
        await Database.record_admin_transaction(
            admin_id=data.get('admin_id', 'system'),
            action='delete_user',
            target_type='user',
            target_id=str(parsed_user_id),
            details={
                'username': user.get('username'),
                'email': user.get('email'),
                'balance': float(user.get('balance', 0)),
                'reason': data.get('reason', '')
            }
        )
        
        return web.json_response({
            'success': True,
            'message': f'User {parsed_user_id} deleted successfully',
            'user_id': parsed_user_id
        })
        
    except Exception as e:
        logger.error(f"Error deleting user: {e}")
        return web.json_response({
            'success': False,
            'message': str(e)
        }, status=500)

@routes.get('/api/admin/user/{user_id}')
async def admin_get_user_details(request):
    """Get detailed user information"""
    try:
        user_id_str = request.match_info['user_id']
        user_id = parse_user_id(user_id_str)
        
        from database.db import Database
        
        with Database.get_cursor() as cursor:
            # Get user details
            cursor.execute("""
                SELECT u.*, 
                       COUNT(DISTINCT uc.game_id) as total_games_played,
                       COUNT(uc.id) as total_cards_purchased,
                       SUM(CASE WHEN g.winner_id = u.user_id THEN 1 ELSE 0 END) as total_wins,
                       SUM(CASE WHEN g.winner_id = u.user_id THEN g.prize_pool ELSE 0 END) as total_winnings
                FROM users u
                LEFT JOIN player_cards uc ON u.user_id = uc.user_id
                LEFT JOIN games g ON uc.game_id = g.game_id AND g.winner_id = u.user_id
                WHERE u.user_id = ?
                GROUP BY u.user_id
            """, (user_id,))
            
            row = cursor.fetchone()
            
            if row:
                user_data = dict(row)
                user_data['balance'] = float(user_data.get('balance', 0))
                user_data['total_winnings'] = float(user_data.get('total_winnings', 0))
                
                # Get recent transactions
                cursor.execute("""
                    SELECT * FROM transactions 
                    WHERE user_id = ? 
                    ORDER BY created_at DESC 
                    LIMIT 10
                """, (user_id,))
                
                transactions = []
                for tx_row in cursor.fetchall():
                    tx_data = dict(tx_row)
                    tx_data['amount'] = float(tx_data['amount'])
                    transactions.append(tx_data)
                
                user_data['recent_transactions'] = transactions
                
                # Get payment history
                cursor.execute("""
                    SELECT * FROM payments 
                    WHERE user_id = ? 
                    ORDER BY created_at DESC 
                    LIMIT 10
                """, (user_id,))
                
                payments = []
                for p_row in cursor.fetchall():
                    p_data = dict(p_row)
                    p_data['amount'] = float(p_data['amount'])
                    payments.append(p_data)
                
                user_data['payment_history'] = payments
                
                # Get withdrawal history
                cursor.execute("""
                    SELECT * FROM withdrawal_requests 
                    WHERE user_id = ? 
                    ORDER BY requested_at DESC 
                    LIMIT 10
                """, (user_id,))
                
                withdrawals = []
                for w_row in cursor.fetchall():
                    w_data = dict(w_row)
                    w_data['amount'] = float(w_data['amount'])
                    withdrawals.append(w_data)
                
                user_data['withdrawal_history'] = withdrawals
                
                return web.json_response({
                    'success': True,
                    'user': user_data,
                    'timestamp': datetime.now().isoformat()
                }, dumps=lambda obj: json.dumps(obj, cls=CustomJSONEncoder))
            
            return web.json_response({
                'success': False,
                'message': 'User not found'
            }, status=404)
            
    except Exception as e:
        logger.error(f"Error getting user details: {e}")
        return web.json_response({
            'success': False,
            'message': str(e)
        }, status=500)

@routes.post('/api/admin/rejectpayment')
async def admin_reject_payment(request):
    """Admin: Reject a payment request"""
    try:
        data = await request.json()
        payment_id = data.get('payment_id')
        admin_id = data.get('admin_id', 'system')
        reason = data.get('reason', '')
        
        if not payment_id:
            return web.json_response({
                'success': False,
                'message': 'payment_id is required'
            }, status=400)
        
        from database.db import Database
        
        with Database.get_cursor() as cursor:
            # Get payment request
            cursor.execute("""
                SELECT * FROM payments 
                WHERE id = ? AND status = 'pending'
            """, (payment_id,))
            
            row = cursor.fetchone()
            if not row:
                return web.json_response({
                    'success': False,
                    'message': 'Payment not found or already processed'
                }, status=404)
            
            payment = dict(row)
            
            # Update payment status
            cursor.execute("""
                UPDATE payments 
                SET status = 'rejected',
                    processed_at = ?,
                    processed_by = ?,
                    admin_notes = ?
                WHERE id = ?
            """, (datetime.now(), admin_id, f'Rejected: {reason}', payment_id))
            
            # Record admin transaction
            await Database.record_admin_transaction(
                admin_id=admin_id,
                action='reject_payment',
                target_type='payment',
                target_id=str(payment_id),
                details={
                    'user_id': payment['user_id'],
                    'amount': float(payment['amount']),
                    'method': payment.get('payment_method'),
                    'reason': reason
                }
            )
            
            return web.json_response({
                'success': True,
                'message': f'Payment {payment_id} rejected',
                'payment_id': payment_id
            })
            
    except Exception as e:
        logger.error(f"Error rejecting payment: {e}")
        return web.json_response({
            'success': False,
            'message': str(e)
        }, status=500)

@routes.post('/api/admin/rejectwithdrawal')
async def admin_reject_withdrawal(request):
    """Admin: Reject a withdrawal request"""
    try:
        data = await request.json()
        withdrawal_id = data.get('withdrawal_id')
        admin_id = data.get('admin_id', 'system')
        reason = data.get('reason', '')
        
        if not withdrawal_id:
            return web.json_response({
                'success': False,
                'message': 'withdrawal_id is required'
            }, status=400)
        
        from database.db import Database
        
        with Database.get_cursor() as cursor:
            # Get withdrawal request
            cursor.execute("""
                SELECT * FROM withdrawal_requests 
                WHERE id = ? AND status = 'pending'
            """, (withdrawal_id,))
            
            row = cursor.fetchone()
            if not row:
                return web.json_response({
                    'success': False,
                    'message': 'Withdrawal not found or already processed'
                }, status=404)
            
            withdrawal = dict(row)
            user_id = withdrawal['user_id']
            amount = float(withdrawal['amount'])
            
            # Update withdrawal status
            cursor.execute("""
                UPDATE withdrawal_requests 
                SET status = 'rejected',
                    processed_at = ?,
                    processed_by = ?,
                    admin_notes = ?
                WHERE id = ?
            """, (datetime.now(), admin_id, f'Rejected: {reason}', withdrawal_id))
            
            # Refund the amount to user balance
            new_balance = await Database.add_user_balance(
                user_id=user_id,
                amount=amount,
                transaction_type='withdrawal_refund',
                notes=f'Withdrawal {withdrawal_id} rejected: {reason}'
            )
            
            # Record admin transaction
            await Database.record_admin_transaction(
                admin_id=admin_id,
                action='reject_withdrawal',
                target_type='withdrawal',
                target_id=str(withdrawal_id),
                details={
                    'user_id': user_id,
                    'amount': amount,
                    'reason': reason,
                    'refunded_balance': new_balance
                }
            )
            
            return web.json_response({
                'success': True,
                'message': f'Withdrawal {withdrawal_id} rejected and refunded',
                'withdrawal_id': withdrawal_id,
                'refunded_amount': amount,
                'new_balance': new_balance
            })
            
    except Exception as e:
        logger.error(f"Error rejecting withdrawal: {e}")
        return web.json_response({
            'success': False,
            'message': str(e)
        }, status=500)

# ==================== FIXED: Add endpoint to get commission details from commission_records ====================
@routes.get('/api/admin/commission-details')
async def admin_commission_details(request):
    """Get detailed commission breakdown by game - FIXED: Uses commission_records table with proper data"""
    try:
        from database.db import Database
        
        # Get page and limit parameters (optional)
        page = int(request.query.get('page', 1))
        limit = int(request.query.get('limit', 50))
        offset = (page - 1) * limit
        
        with Database.get_cursor() as cursor:
            # Get games with commission data - FIXED: Use correct column names
            cursor.execute("""
                SELECT 
                    cr.game_id,
                    cr.round_number,
                    cr.recorded_at as game_date,
                    cr.real_players_count as real_players,
                    cr.commission_amount as commission,
                    cr.status as commission_status,
                    g.total_cards_sold,
                    g.prize_pool,
                    g.card_price,
                    (SELECT COUNT(*) FROM player_cards WHERE game_id = cr.game_id AND is_fake = 0 AND is_active = 1) as real_cards_sold,
                    (SELECT COUNT(*) FROM player_cards WHERE game_id = cr.game_id AND is_fake = 1 AND is_active = 1) as fake_cards_sold
                FROM commission_records cr
                LEFT JOIN games g ON cr.game_id = g.game_id
                ORDER BY cr.recorded_at DESC
                LIMIT ? OFFSET ?
            """, (limit, offset))
            
            rows = cursor.fetchall()
            commission_games = []
            
            for row in rows:
                # Convert row to dictionary with proper column access
                game_data = {
                    'game_id': row[0],
                    'round_number': row[1] or 1,
                    'game_date': row[2].isoformat() if row[2] else None,
                    'real_players': row[3] or 0,
                    'commission': float(row[4] or 0),
                    'commission_status': row[5] or 'recorded',
                    'total_cards_sold': row[6] or 0,
                    'prize_pool': float(row[7] or 0),
                    'card_price': float(row[8] or 10.00),
                    'real_cards_sold': row[9] or 0,
                    'fake_cards_sold': row[10] or 0,
                    'total_sales': (row[9] or 0) * float(row[8] or 10.00)  # real_cards_sold * card_price
                }
                commission_games.append(game_data)
            
            # Get daily summary
            cursor.execute("""
                SELECT 
                    date(recorded_at) as day,
                    COUNT(*) as games_count,
                    SUM(real_players_count) as total_players,
                    SUM(commission_amount) as total_commission,
                    SUM(g.total_cards_sold) as total_cards_sold,
                    SUM(g.total_cards_sold * g.card_price) as total_sales
                FROM commission_records cr
                LEFT JOIN games g ON cr.game_id = g.game_id
                GROUP BY date(recorded_at)
                ORDER BY day DESC
                LIMIT 30
            """)
            daily_rows = cursor.fetchall()
            daily_data = []
            for row in daily_rows:
                daily_data.append({
                    'date': row[0],
                    'games_count': row[1] or 0,
                    'real_players': row[2] or 0,
                    'total_commission': float(row[3] or 0),
                    'total_cards_sold': row[4] or 0,
                    'total_sales': float(row[5] or 0)
                })
            
            # Get monthly summary
            cursor.execute("""
                SELECT 
                    strftime('%Y-%m', recorded_at) as month,
                    COUNT(*) as games_count,
                    SUM(real_players_count) as total_players,
                    SUM(commission_amount) as total_commission,
                    SUM(g.total_cards_sold) as total_cards_sold,
                    SUM(g.total_cards_sold * g.card_price) as total_sales
                FROM commission_records cr
                LEFT JOIN games g ON cr.game_id = g.game_id
                GROUP BY strftime('%Y-%m', recorded_at)
                ORDER BY month DESC
                LIMIT 12
            """)
            monthly_rows = cursor.fetchall()
            monthly_data = []
            for row in monthly_rows:
                monthly_data.append({
                    'month': row[0],
                    'games_count': row[1] or 0,
                    'real_players': row[2] or 0,
                    'total_commission': float(row[3] or 0),
                    'total_cards_sold': row[4] or 0,
                    'total_sales': float(row[5] or 0)
                })
            
            # Get total count for pagination
            cursor.execute("SELECT COUNT(*) as total FROM commission_records")
            total_row = cursor.fetchone()
            total = total_row[0] if total_row else 0
            
            return web.json_response({
                'success': True,
                'games': commission_games,
                'daily': daily_data,
                'monthly': monthly_data,
                'pagination': {
                    'page': page,
                    'limit': limit,
                    'total': total,
                    'pages': (total + limit - 1) // limit if total > 0 else 0
                },
                'calculation_method': 'real_players × 2 (from commission_records table)',
                'timestamp': datetime.now().isoformat()
            })
            
    except Exception as e:
        logger.error(f"❌ Error getting commission details: {e}", exc_info=True)
        return web.json_response({
            'success': False,
            'message': str(e),
            'games': [],
            'daily': [],
            'monthly': []
        }, status=500)
        
        
        
        # ==================== ADMIN AUTHENTICATION ENDPOINTS ====================

@routes.post('/api/admin/login')
async def admin_login(request):
    """Admin login endpoint"""
    try:
        data = await request.json()
        username = data.get('username')
        password = data.get('password')
        login_type = data.get('login_type', 'username')  # 'username' or 'phone'
        
        if not username or not password:
            return web.json_response({
                'success': False,
                'message': 'Username and password are required'
            }, status=400)
        
        from database.db import Database
        
        # Verify credentials
        if login_type == 'phone':
            admin = await Database.verify_admin_login_by_phone(username, password)
        else:
            admin = await Database.verify_admin_login(username, password)
        
        if admin:
            # Create session token (simple for now - in production use JWT)
            import hashlib
            import uuid
            token = hashlib.sha256(f"{admin['id']}:{uuid.uuid4().hex}".encode()).hexdigest()
            
            # Store session (you might want to add a sessions table)
            # For now, we'll just return the token
            
            response_data = {
                'success': True,
                'message': 'Login successful',
                'admin': admin,
                'token': token,
                'redirect': '/admin.html?auth=true'
            }
            
            logger.info(f"✅ Admin login successful: {admin.get('username')}")
            return web.json_response(response_data)
        else:
            logger.warning(f"❌ Failed admin login attempt for: {username}")
            return web.json_response({
                'success': False,
                'message': 'Invalid credentials'
            }, status=401)
            
    except Exception as e:
        logger.error(f"Error in admin login: {e}")
        return web.json_response({
            'success': False,
            'message': 'Server error'
        }, status=500)

@routes.post('/api/admin/change-password')
async def admin_change_password(request):
    """Change admin password"""
    try:
        data = await request.json()
        admin_id = data.get('admin_id')
        old_password = data.get('old_password')
        new_password = data.get('new_password')
        
        if not admin_id or not old_password or not new_password:
            return web.json_response({
                'success': False,
                'message': 'Missing required fields'
            }, status=400)
        
        from database.db import Database
        
        success = await Database.update_admin_password(admin_id, old_password, new_password)
        
        if success:
            logger.info(f"✅ Password changed for admin ID: {admin_id}")
            return web.json_response({
                'success': True,
                'message': 'Password changed successfully'
            })
        else:
            return web.json_response({
                'success': False,
                'message': 'Current password is incorrect'
            }, status=401)
            
    except Exception as e:
        logger.error(f"Error changing password: {e}")
        return web.json_response({
            'success': False,
            'message': 'Server error'
        }, status=500)

@routes.post('/api/admin/update-profile')
async def admin_update_profile(request):
    """Update admin profile"""
    try:
        data = await request.json()
        admin_id = data.get('admin_id')
        
        if not admin_id:
            return web.json_response({
                'success': False,
                'message': 'admin_id is required'
            }, status=400)
        
        from database.db import Database
        
        # Extract updatable fields
        update_data = {}
        if 'phone' in data:
            update_data['phone'] = data['phone']
        if 'full_name' in data:
            update_data['full_name'] = data['full_name']
        if 'email' in data:
            update_data['email'] = data['email']
        
        success = await Database.update_admin_profile(admin_id, **update_data)
        
        if success:
            # Get updated admin data
            admin = await Database.get_admin_by_id(admin_id)
            logger.info(f"✅ Profile updated for admin ID: {admin_id}")
            return web.json_response({
                'success': True,
                'message': 'Profile updated successfully',
                'admin': admin
            })
        else:
            return web.json_response({
                'success': False,
                'message': 'Failed to update profile'
            }, status=400)
            
    except Exception as e:
        logger.error(f"Error updating profile: {e}")
        return web.json_response({
            'success': False,
            'message': 'Server error'
        }, status=500)
        
        
 # ==================== FAKE PLAYER SETTINGS ENDPOINTS ====================

@routes.get('/api/admin/fake-users-status')
async def admin_fake_users_status(request):
    """Get current fake users status and configuration"""
    try:
        from utils.game_manager import game_manager
        
        # Get fake users status from game manager
        status = await game_manager.get_fake_users_status()
        
        return web.json_response({
            'success': True,
            'fake_users_enabled': game_manager.fake_users_enabled,
            'min_fake_players': game_manager.min_fake_players,
            'max_fake_players': game_manager.max_fake_players,
            'total_fake_users': len(game_manager.fake_user_manager.fake_users) if hasattr(game_manager, 'fake_user_manager') else 0,
            'current_game_fake': len(game_manager.fake_user_manager.game_fake_cards.get(game_manager.active_game.get('game_id') if game_manager.active_game else '', {})) if hasattr(game_manager, 'fake_user_manager') else 0,
            'message': 'Fake users status retrieved successfully',
            'timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Error getting fake users status: {e}")
        return web.json_response({
            'success': False,
            'message': str(e)
        }, status=500)


@routes.post('/api/admin/set_fake_player_range')
async def admin_set_fake_player_range(request):
    """Set minimum and maximum fake players per game"""
    try:
        data = await request.json()
        min_fake = data.get('min_fake')
        max_fake = data.get('max_fake')
        admin_id = data.get('admin_id')
        
        if not min_fake or not max_fake or not admin_id:
            return web.json_response({
                'success': False,
                'message': 'min_fake, max_fake, and admin_id are required'
            }, status=400)
        
        # Validate inputs
        if min_fake < 2:
            return web.json_response({
                'success': False,
                'message': 'Minimum fake players must be at least 2'
            }, status=400)
        
        if max_fake < min_fake:
            return web.json_response({
                'success': False,
                'message': 'Maximum fake players must be greater than or equal to minimum'
            }, status=400)
        
        if max_fake > 400:
            return web.json_response({
                'success': False,
                'message': 'Maximum fake players cannot exceed 400'
            }, status=400)
        
        from utils.game_manager import game_manager
        
        # Call the game manager method to set the range
        old_min = game_manager.min_fake_players
        old_max = game_manager.max_fake_players
        
        game_manager.min_fake_players = min_fake
        game_manager.max_fake_players = max_fake
        
        logger.info(f"Admin {admin_id} set fake player range from {old_min}-{old_max} to {min_fake}-{max_fake}")
        
        # Record admin transaction
        try:
            from database.db import Database
            await Database.record_admin_transaction(
                admin_id=admin_id,
                action='set_fake_player_range',
                target_type='config',
                target_id='fake_players',
                details={
                    'old_min': old_min,
                    'old_max': old_max,
                    'new_min': min_fake,
                    'new_max': max_fake
                }
            )
        except Exception as tx_error:
            logger.warning(f"Could not record admin transaction: {tx_error}")
        
        return web.json_response({
            'success': True,
            'message': f'Fake player range set to {min_fake} - {max_fake}',
            'old_min_fake_players': old_min,
            'old_max_fake_players': old_max,
            'min_fake_players': min_fake,
            'max_fake_players': max_fake
        })
        
    except Exception as e:
        logger.error(f"Error setting fake player range: {e}", exc_info=True)
        return web.json_response({
            'success': False,
            'message': str(e)
        }, status=500)
 
# ==================== USER TRANSACTIONS WITH PAGINATION ====================

@routes.get('/api/admin/user/{user_id}/transactions')
async def admin_user_transactions(request):
    """Get paginated transactions for a specific user"""
    try:
        user_id_str = request.match_info['user_id']
        user_id = parse_user_id(user_id_str)
        
        # Get pagination parameters
        page = int(request.query.get('page', 1))
        limit = int(request.query.get('limit', 10))
        offset = (page - 1) * limit
        
        from database.db import Database
        
        with Database.get_cursor() as cursor:
            # Get total count for pagination
            cursor.execute("""
                SELECT COUNT(*) as total 
                FROM transactions 
                WHERE user_id = ?
            """, (user_id,))
            total_row = cursor.fetchone()
            total = total_row[0] if total_row else 0
            
            # Get paginated transactions
            cursor.execute("""
                SELECT id, user_id, amount, balance_after, transaction_type, 
                       description, game_id, created_at
                FROM transactions 
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
            """, (user_id, limit, offset))
            
            rows = cursor.fetchall()
            transactions = []
            
            for row in rows:
                tx = {
                    'id': row[0],
                    'user_id': row[1],
                    'amount': float(row[2]) if row[2] else 0,
                    'balance_after': float(row[3]) if row[3] else None,
                    'transaction_type': row[4],
                    'description': row[5],
                    'game_id': row[6],
                    'created_at': row[7].isoformat() if row[7] else None
                }
                transactions.append(tx)
            
            # Get username for reference
            cursor.execute("SELECT username FROM users WHERE user_id = ?", (user_id,))
            user_row = cursor.fetchone()
            username = user_row[0] if user_row else None
            
            # Add username to each transaction
            for tx in transactions:
                tx['username'] = username
            
            total_pages = (total + limit - 1) // limit if total > 0 else 0
            
            return web.json_response({
                'success': True,
                'transactions': transactions,
                'pagination': {
                    'page': page,
                    'limit': limit,
                    'total': total,
                    'pages': total_pages
                },
                'timestamp': datetime.now().isoformat()
            }, dumps=lambda obj: json.dumps(obj, cls=CustomJSONEncoder))
            
    except Exception as e:
        logger.error(f"Error getting user transactions: {e}", exc_info=True)
        return web.json_response({
            'success': False,
            'message': str(e)
        }, status=500)        
               
        

@routes.get('/api/admin/profile/{admin_id}')
async def admin_get_profile(request):
    """Get admin profile"""
    try:
        admin_id = int(request.match_info['admin_id'])
        
        from database.db import Database
        
        admin = await Database.get_admin_by_id(admin_id)
        
        if admin:
            return web.json_response({
                'success': True,
                'admin': admin
            })
        else:
            return web.json_response({
                'success': False,
                'message': 'Admin not found'
            }, status=404)
            
    except Exception as e:
        logger.error(f"Error getting admin profile: {e}")
        return web.json_response({
            'success': False,
            'message': 'Server error'
        }, status=500)

@routes.get('/api/admin/check-session')
async def admin_check_session(request):
    """Check if session is valid"""
    # This is a placeholder - implement proper session validation
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    
    if token:
        # Validate token (implement your token validation logic)
        return web.json_response({
            'success': True,
            'valid': True
        })
    else:
        return web.json_response({
            'success': False,
            'valid': False
        })





@routes.get('/login.html')
async def login_html(request):
    """Serve the login page"""
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        
        possible_paths = [
            os.path.join(current_dir, 'login.html'),
            os.path.join(current_dir, 'templates', 'login.html'),
            os.path.join(current_dir, 'static', 'login.html'),
            os.path.join(current_dir, 'html', 'login.html'),
            'login.html',
            './login.html'
        ]
        
        html_content = None
        
        for path in possible_paths:
            try:
                if os.path.exists(path):
                    with open(path, 'r', encoding='utf-8') as f:
                        html_content = f.read()
                    logger.info(f"Successfully served login.html from: {path}")
                    break
            except Exception as e:
                logger.debug(f"Failed to read {path}: {e}")
                continue
        
        if html_content is None:
            # Return embedded login page
            html_content = """
            <!DOCTYPE html>
            <html>
            <head><title>Login - Haset Bingo Admin</title></head>
            <body><h1>Login page not found</h1></body>
            </html>
            """
        
        return web.Response(
            text=html_content,
            content_type='text/html',
            headers={
                'Cache-Control': 'no-cache, no-store, must-revalidate',
                'Pragma': 'no-cache',
                'Expires': '0'
            }
        )
    except Exception as e:
        logger.error(f"Error serving login.html: {e}")
        return web.Response(text="Error loading login page", status=500)
# ==================== TEST COMMISSION ENDPOINT ====================
@routes.post('/api/admin/test-commission')
async def admin_test_commission(request):
    """Test endpoint to manually record commission for a game"""
    try:
        data = await request.json()
        game_id = data.get('game_id')
        
        if not game_id:
            return web.json_response({
                'success': False,
                'message': 'game_id is required'
            })
        
        from utils.game_manager import game_manager
        
        # Try to record commission
        success = await game_manager.record_game_commission(game_id)
        
        if success:
            return web.json_response({
                'success': True,
                'message': f'Commission recorded for game {game_id}'
            })
        else:
            return web.json_response({
                'success': False,
                'message': f'Failed to record commission for game {game_id}'
            })
            
    except Exception as e:
        logger.error(f"Error in test commission: {e}")
        return web.json_response({
            'success': False,
            'message': str(e)
        }, status=500)


@routes.get('/api/admin/gamedetails/{game_id}')
async def admin_game_details(request):
    """Get detailed game information including commission"""
    try:
        game_id = request.match_info['game_id']
        
        from database.db import Database
        
        with Database.get_cursor() as cursor:
            # Get commission from commission_records table
            cursor.execute("""
                SELECT 
                    g.*, 
                    c.commission_amount as actual_commission,
                    c.real_players_count,
                    COUNT(DISTINCT pc.user_id) as player_count,
                    COUNT(pc.id) as cards_sold,
                    g.total_cards_sold * g.card_price as total_sales,
                    g.total_cards_sold * g.card_price * 0.8 as prize_pool_calculated,
                    u.username as winner_username
                FROM games g
                LEFT JOIN commission_records c ON g.game_id = c.game_id
                LEFT JOIN player_cards pc ON g.game_id = pc.game_id AND pc.is_active = 1
                LEFT JOIN users u ON g.winner_id = u.user_id
                WHERE g.game_id = ?
                GROUP BY g.game_id
            """, (game_id,))
            
            row = cursor.fetchone()
            
            if row:
                game_data = dict(row)
                # Convert Decimal to float
                game_data['total_sales'] = float(game_data['total_sales'] or 0)
                game_data['commission'] = float(game_data['actual_commission'] or game_data['commission'] or 0)
                game_data['prize_pool_calculated'] = float(game_data['prize_pool_calculated'] or 0)
                game_data['card_price'] = float(game_data['card_price'] or 10)
                game_data['prize_pool'] = float(game_data['prize_pool'] or 0)
                game_data['real_players_count'] = int(game_data['real_players_count'] or 0)
                
                # Get called numbers
                cursor.execute("""
                    SELECT number 
                    FROM called_numbers 
                    WHERE game_id = ?
                    ORDER BY called_at
                """, (game_id,))
                called_numbers = [row[0] for row in cursor.fetchall()]
                game_data['called_numbers'] = called_numbers
                
                # Get card purchase details
                cursor.execute("""
                    SELECT pc.*, u.username, u.balance
                    FROM player_cards pc
                    LEFT JOIN users u ON pc.user_id = u.user_id
                    WHERE pc.game_id = ? AND pc.is_active = 1
                    ORDER BY pc.purchase_time
                """, (game_id,))
                cards = []
                for card_row in cursor.fetchall():
                    card_data = dict(card_row)
                    card_data['balance'] = float(card_data['balance'] or 0)
                    cards.append(card_data)
                game_data['cards'] = cards
                
                return web.json_response({
                    'success': True,
                    'game': game_data,
                    'timestamp': datetime.now().isoformat()
                }, dumps=lambda obj: json.dumps(obj, cls=CustomJSONEncoder))
            
            return web.json_response({
                'success': False,
                'message': 'Game not found'
            }, status=404)
            
    except Exception as e:
        logger.error(f"Error getting game details: {e}")
        return web.json_response({
            'success': False,
            'message': str(e)
        }, status=500)


@routes.get('/api/admin/games')
async def admin_games(request):
    """Get all games for admin"""
    try:
        from database.db import Database
        
        # Get page and limit parameters
        page = int(request.query.get('page', 1))
        limit = int(request.query.get('limit', 20))
        offset = (page - 1) * limit
        
        games = await Database.get_admin_games(limit, offset)
        total_games = await Database.get_total_games()
        
        result = {
            'success': True,
            'games': games,
            'pagination': {
                'page': page,
                'limit': limit,
                'total': total_games,
                'pages': (total_games + limit - 1) // limit
            }
        }
        
        return web.json_response(
            convert_to_json_serializable(result),
            dumps=lambda obj: json.dumps(obj, cls=CustomJSONEncoder)
        )
        
    except Exception as e:
        logger.error(f"Error getting admin games: {e}")
        return web.json_response({
            'success': False,
            'message': str(e)
        }, status=500)


@routes.get('/api/admin/users')
async def admin_users(request):
    """Get all users for admin"""
    try:
        from database.db import Database
        
        # Get page and limit parameters
        page = int(request.query.get('page', 1))
        limit = int(request.query.get('limit', 20))
        offset = (page - 1) * limit
        
        users = await Database.get_admin_users(limit, offset)
        total_users = await Database.get_total_users()
        
        result = {
            'success': True,
            'users': users,
            'pagination': {
                'page': page,
                'limit': limit,
                'total': total_users,
                'pages': (total_users + limit - 1) // limit
            }
        }
        
        return web.json_response(
            convert_to_json_serializable(result),
            dumps=lambda obj: json.dumps(obj, cls=CustomJSONEncoder)
        )
        
    except Exception as e:
        logger.error(f"Error getting admin users: {e}")
        return web.json_response({
            'success': False,
            'message': str(e)
        }, status=500)

@routes.get('/api/admin/payments')
async def admin_payments(request):
    """Get all payments for admin"""
    try:
        from database.db import Database
        
        # Get page and limit parameters
        page = int(request.query.get('page', 1))
        limit = int(request.query.get('limit', 20))
        offset = (page - 1) * limit
        status_filter = request.query.get('status', 'all')
        
        payments = await Database.get_admin_payments(limit, offset, status_filter)
        total_payments = await Database.get_total_payments(status_filter)
        
        result = {
            'success': True,
            'payments': payments,
            'pagination': {
                'page': page,
                'limit': limit,
                'total': total_payments,
                'pages': (total_payments + limit - 1) // limit
            },
            'filters': {
                'status': status_filter
            }
        }
        
        return web.json_response(
            convert_to_json_serializable(result),
            dumps=lambda obj: json.dumps(obj, cls=CustomJSONEncoder)
        )
        
    except Exception as e:
        logger.error(f"Error getting admin payments: {e}")
        return web.json_response({
            'success': False,
            'message': str(e)
        }, status=500)

@routes.get('/api/admin/withdrawals')
async def admin_get_withdrawals(request):
    """Get withdrawal requests"""
    try:
        status = request.query.get('status', 'pending')
        
        from database.db import Database
        
        with Database.get_cursor() as cursor:
            if status == 'all':
                cursor.execute("""
                    SELECT wr.*, u.username, u.full_name 
                    FROM withdrawal_requests wr
                    LEFT JOIN users u ON wr.user_id = u.user_id
                    ORDER BY wr.requested_at DESC
                """)
            else:
                cursor.execute("""
                    SELECT wr.*, u.username, u.full_name 
                    FROM withdrawal_requests wr
                    LEFT JOIN users u ON wr.user_id = u.user_id
                    WHERE wr.status = ?
                    ORDER BY wr.requested_at DESC
                """, (status,))
            rows = cursor.fetchall()
            
            withdrawals = []
            for row in rows:
                withdrawal_dict = dict(row)
                # Convert Decimal to float for JSON serialization
                withdrawal_dict['amount'] = float(withdrawal_dict['amount'])
                withdrawals.append(withdrawal_dict)
            
            total_withdrawals = len(withdrawals)
            
            return web.json_response({
                'success': True,
                'withdrawals': withdrawals,
                'total': total_withdrawals,
                'status_filter': status
            }, dumps=lambda obj: json.dumps(obj, cls=CustomJSONEncoder))
            
    except Exception as e:
        logger.error(f"Error getting withdrawals: {e}")
        return web.json_response({
            'success': False,
            'message': str(e)
        }, status=500)


# ==================== FIXED: TRANSACTIONS API WITH FILTERING ====================
@routes.get('/api/admin/transactions')
async def admin_transactions(request):
    """Get all transactions for admin with filtering for deposits and withdrawals"""
    try:
        from database.db import Database
        
        # Get page and limit parameters
        page = int(request.query.get('page', 1))
        limit = int(request.query.get('limit', 20))
        offset = (page - 1) * limit
        type_filter = request.query.get('type', 'all')
        
        # Map filter to actual transaction types
        transaction_types = []
        if type_filter == 'all':
            transaction_types = []  # All types
        elif type_filter == 'deposit':
            transaction_types = ['deposit']  # Only deposits
        elif type_filter == 'withdrawal':
            transaction_types = ['withdrawal_approved', 'withdrawal_rejected', 'withdrawal_requested', 'withdrawal_refund']  # Withdrawal related
        elif type_filter == 'game':
            transaction_types = ['card_purchase', 'winning', 'card_refund', 'bingo_win']  # Game related
        elif type_filter == 'admin':
            transaction_types = ['admin_add', 'admin_deduct', 'system_refund']  # Admin actions
        else:
            transaction_types = [type_filter]  # Specific type
        
        # Log the filtering
        logger.info(f"📊 Transaction filter: '{type_filter}' -> types: {transaction_types if transaction_types else 'ALL'}")
        
        # Get filtered transactions
        transactions = await Database.get_admin_transactions_filtered(limit, offset, transaction_types if transaction_types else None)
        
        # Get total count for pagination
        total_transactions = await Database.get_total_transactions_filtered(transaction_types if transaction_types else None)
        
        # Calculate total pages
        total_pages = (total_transactions + limit - 1) // limit if total_transactions > 0 else 0
        
        result = {
            'success': True,
            'transactions': transactions,
            'pagination': {
                'page': page,
                'limit': limit,
                'total': total_transactions,
                'pages': total_pages
            },
            'filters': {
                'type': type_filter,
                'applied_types': transaction_types if transaction_types else 'all'
            }
        }
        
        return web.json_response(
            convert_to_json_serializable(result),
            dumps=lambda obj: json.dumps(obj, cls=CustomJSONEncoder)
        )
        
    except Exception as e:
        logger.error(f"Error getting admin transactions: {e}", exc_info=True)
        return web.json_response({
            'success': False,
            'message': str(e)
        }, status=500)

@routes.post('/api/admin/startgame')
async def admin_start_game(request):
    """Admin: Start a game - FIXED: Better error handling and game state checks"""
    try:
        data = await request.json()
        admin_id = data.get('admin_id', 'system')
        force = data.get('force', False)  # Force start even if game exists
        
        from database.db import Database
        from utils.game_manager import game_manager
        
        # Check if there's already an active game
        active_game = await game_manager.get_active_round_game()
        
        if active_game and not force:
            # Check if the existing game is stuck
            game_id = active_game.get('game_id')
            game_status = active_game.get('status')
            
            # If game is in winner_display for too long, allow force start
            if game_status == 'winner_display':
                # Check how long it's been in winner_display
                game = await Database.get_game(game_id)
                if game and game.get('completed_at'):
                    completed_time = game.get('completed_at')
                    if isinstance(completed_time, str):
                        try:
                            completed_time = datetime.fromisoformat(completed_time)
                        except:
                            completed_time = None
                    
                    if completed_time:
                        time_diff = datetime.now() - completed_time
                        if time_diff.total_seconds() > 30:  # More than 30 seconds in winner display
                            logger.info(f"Game {game_id} appears stuck in winner_display, allowing force start")
                            # Allow force start
                            pass
                        else:
                            return web.json_response({
                                'success': False,
                                'message': 'A game is already active. Use force parameter to override.'
                            }, status=400)
                    else:
                        return web.json_response({
                            'success': False,
                            'message': 'A game is already active. Use force parameter to override.'
                        }, status=400)
                else:
                    return web.json_response({
                        'success': False,
                        'message': 'A game is already active. Use force parameter to override.'
                    }, status=400)
            else:
                return web.json_response({
                    'success': False,
                    'message': 'A game is already active. Stop it first or use force parameter.'
                }, status=400)
        
        # Stop any existing number calling
        if active_game:
            from utils.number_caller import number_caller
            await number_caller.stop_number_calling_for_game(active_game.get('game_id'))
            logger.info(f"Stopped number calling for existing game {active_game.get('game_id')}")
        
        # Start new game
        logger.info(f"Admin {admin_id} starting new game (force={force})")
        result = await game_manager.start_new_round_game()
        
        if result.get('success'):
            # Get the new game
            new_game = await game_manager.get_active_round_game()
            game_id = new_game.get('game_id') if new_game else None
            
            # Broadcast to all connected clients
            await websocket_server.broadcast_with_retry({
                'type': 'admin_game_started',
                'game_id': game_id,
                'admin_action': 'start_game',
                'force': force,
                'timestamp': datetime.now().isoformat()
            })
            
            return web.json_response({
                'success': True,
                'message': 'New game started successfully',
                'game_id': game_id
            })
        else:
            return web.json_response({
                'success': False,
                'message': result.get('message', 'Failed to start game')
            }, status=500)
        
    except Exception as e:
        logger.error(f"Error starting game: {e}", exc_info=True)
        return web.json_response({
            'success': False,
            'message': str(e)
        }, status=500)


@routes.post('/api/admin/stopgame')
async def admin_stop_game(request):
    """Admin: Stop a game - FIXED: Better error handling and cleanup"""
    try:
        data = await request.json()
        game_id = data.get('game_id')
        admin_id = data.get('admin_id', 'system')
        
        if not game_id:
            return web.json_response({
                'success': False,
                'message': 'game_id is required'
            }, status=400)
        
        from database.db import Database
        from utils.number_caller import number_caller
        from utils.game_manager import game_manager
        
        # Get game
        game = await Database.get_game(game_id)
        if not game:
            return web.json_response({
                'success': False,
                'message': 'Game not found'
            }, status=404)
        
        # Check if game can be stopped
        if game.get('status') == 'completed':
            return web.json_response({
                'success': False,
                'message': 'Game is already completed'
            }, status=400)
        
        # Stop number calling
        await number_caller.stop_number_calling_for_game(game_id)
        logger.info(f"Stopped number calling for game {game_id}")
        
        # Update game status
        await Database.update_game_status(game_id, 'winner_display')
        
        # Also update the game_manager state
        try:
            # Force the game_manager to update its state
            await game_manager.force_game_completion(game_id)
        except Exception as e:
            logger.warning(f"Error updating game_manager state: {e}")
        
        # Broadcast to all connected clients
        await websocket_server.broadcast_with_retry({
            'type': 'admin_game_stopped',
            'game_id': game_id,
            'admin_action': 'stop_game',
            'timestamp': datetime.now().isoformat(),
            'message': 'Game stopped by admin'
        })
        
        logger.info(f"Admin {admin_id} stopped game {game_id}")
        
        return web.json_response({
            'success': True,
            'message': f'Game {game_id} stopped successfully',
            'game_id': game_id
        })
        
    except Exception as e:
        logger.error(f"Error stopping game: {e}", exc_info=True)
        return web.json_response({
            'success': False,
            'message': str(e)
        }, status=500)


@routes.post('/api/admin/reset-game')
async def admin_reset_game(request):
    """Admin: Force reset the current game - NEW: Complete game reset"""
    try:
        data = await request.json()
        admin_id = data.get('admin_id', 'system')
        
        from database.db import Database
        from utils.game_manager import game_manager
        from utils.number_caller import number_caller
        
        logger.info(f"🔄 Admin {admin_id} initiating force game reset")
        
        # Get current active game
        active_game = await game_manager.get_active_round_game()
        
        if active_game:
            game_id = active_game.get('game_id')
            
            # Stop number calling
            await number_caller.stop_number_calling_for_game(game_id)
            logger.info(f"Stopped number calling for game {game_id}")
            
            # Update game status to completed
            await Database.update_game_status(game_id, 'completed')
            
            # Clear any fake players for this game
            if hasattr(game_manager, 'fake_user_manager'):
                if game_id in game_manager.fake_user_manager.game_fake_cards:
                    del game_manager.fake_user_manager.game_fake_cards[game_id]
                    logger.info(f"Cleared fake cards for game {game_id}")
            
            # Clear any pending winners
            if hasattr(game_manager, '_winners'):
                if game_id in game_manager._winners:
                    del game_manager._winners[game_id]
            
            logger.info(f"Reset game {game_id}")
        
        # Start a new game immediately
        result = await game_manager.start_new_round_game()
        
        if result.get('success'):
            new_game = await game_manager.get_active_round_game()
            new_game_id = new_game.get('game_id') if new_game else None
            
            await websocket_server.broadcast_with_retry({
                'type': 'game_reset',
                'message': 'Game was force reset by admin',
                'new_game_id': new_game_id,
                'timestamp': datetime.now().isoformat()
            })
            
            return web.json_response({
                'success': True,
                'message': 'Game reset successfully and new game started',
                'new_game_id': new_game_id
            })
        else:
            return web.json_response({
                'success': False,
                'message': 'Failed to start new game after reset'
            }, status=500)
        
    except Exception as e:
        logger.error(f"Error resetting game: {e}", exc_info=True)
        return web.json_response({
            'success': False,
            'message': str(e)
        }, status=500)


@routes.post('/api/admin/callnumber')
async def admin_call_number(request):
    """Admin: Call a number manually"""
    try:
        data = await request.json()
        game_id = data.get('game_id')
        number = data.get('number')
        
        if not game_id or not number:
            return web.json_response({
                'success': False,
                'message': 'game_id and number are required'
            }, status=400)
        
        from database.db import Database
        from utils.number_caller import number_caller
        
        game = await Database.get_game(game_id)
        if not game:
            return web.json_response({
                'success': False,
                'message': 'Game not found'
            }, status=404)
        
        if game.get('status') != 'active':
            return web.json_response({
                'success': False,
                'message': 'Game is not active'
            }, status=400)
        
        # Check if number is already called
        called_numbers = await Database.get_drawn_numbers(game_id)
        if number in called_numbers:
            return web.json_response({
                'success': False,
                'message': f'Number {number} already called'
            }, status=400)
        
        # Call the number
        await number_caller.force_call_number(game_id, number)
        
        # Broadcast to all connected clients
        await websocket_server.broadcast_with_retry({
            'type': 'admin_number_called',
            'game_id': game_id,
            'number': number,
            'admin_action': 'call_number',
            'timestamp': datetime.now().isoformat()
        })
        
        return web.json_response({
            'success': True,
            'message': f'Number {number} called successfully in game {game_id}',
            'game_id': game_id,
            'number': number
        })
        
    except Exception as e:
        logger.error(f"Error calling number: {e}")
        return web.json_response({
            'success': False,
            'message': str(e)
        }, status=500)

@routes.post('/api/admin/addbalance')
async def admin_add_balance(request):
    """Admin: Add balance to user"""
    try:
        data = await request.json()
        user_id = data.get('user_id')
        amount = data.get('amount')
        notes = data.get('notes', '')
        
        if not user_id or not amount:
            return web.json_response({
                'success': False,
                'message': 'user_id and amount are required'
            }, status=400)
        
        from database.db import Database
        
        # Parse user ID
        parsed_user_id = parse_user_id(str(user_id))
        
        # Get user
        user = await Database.get_user(parsed_user_id)
        if not user:
            return web.json_response({
                'success': False,
                'message': 'User not found'
            }, status=404)
        
        # Add balance
        new_balance = await Database.add_user_balance(
            user_id=parsed_user_id,
            amount=float(amount),
            transaction_type='admin_add',
            notes=notes
        )
        
        # Record admin transaction
        await Database.record_admin_transaction(
            admin_id=data.get('admin_id', 'system'),
            action='add_balance',
            target_type='user',
            target_id=str(parsed_user_id),
            details={
                'amount': float(amount),
                'previous_balance': float(user.get('balance', 0)),
                'new_balance': float(new_balance),
                'notes': notes
            }
        )
        
        return web.json_response({
            'success': True,
            'message': f'Added {amount} to user {parsed_user_id}',
            'user_id': parsed_user_id,
            'amount': float(amount),
            'new_balance': float(new_balance)
        })
        
    except Exception as e:
        logger.error(f"Error adding balance: {e}")
        return web.json_response({
            'success': False,
            'message': str(e)
        }, status=500)

@routes.post('/api/admin/approvepayment')
async def admin_approve_payment(request):
    """Admin: Approve a payment"""
    try:
        data = await request.json()
        payment_id = data.get('payment_id')
        
        if not payment_id:
            return web.json_response({
                'success': False,
                'message': 'payment_id is required'
            }, status=400)
        
        from database.db import Database
        
        # Get payment
        payment = await Database.get_payment(payment_id)
        if not payment:
            return web.json_response({
                'success': False,
                'message': 'Payment not found'
            }, status=404)
        
        if payment.get('status') != 'pending':
            return web.json_response({
                'success': False,
                'message': f'Payment is already {payment.get("status")}'
            }, status=400)
        
        # Approve payment
        await Database.approve_payment(
            payment_id=payment_id,
            admin_id=data.get('admin_id', 'system')
        )
        
        # Record admin transaction
        await Database.record_admin_transaction(
            admin_id=data.get('admin_id', 'system'),
            action='approve_payment',
            target_type='payment',
            target_id=payment_id,
            details={
                'user_id': payment.get('user_id'),
                'amount': float(payment.get('amount', 0)),
                'method': payment.get('payment_method')
            }
        )
        
        return web.json_response({
            'success': True,
            'message': f'Payment {payment_id} approved successfully',
            'payment_id': payment_id
        })
        
    except Exception as e:
        logger.error(f"Error approving payment: {e}")
        return web.json_response({
            'success': False,
            'message': str(e)
        }, status=500)

@routes.post('/api/admin/notification')
async def admin_send_notification(request):
    """Admin: Send notification to users"""
    try:
        data = await request.json()
        title = data.get('title')
        message = data.get('message')
        target = data.get('target', 'all')  # all, active, specific
        target_ids = data.get('target_ids', [])
        
        if not title or not message:
            return web.json_response({
                'success': False,
                'message': 'title and message are required'
            }, status=400)
        
        from database.db import Database
        
        # Record notification
        notification_id = await Database.record_notification(
            user_id=None,
            notification_type="admin",
            title=title,
            message=message
        )
        
        # Send to WebSocket connections
        notification_data = {
            'type': 'admin_notification',
            'notification': {
                'id': notification_id,
                'title': title,
                'message': message,
                'timestamp': datetime.now().isoformat()
            }
        }
        
        if target == 'all':
            # Send to all connected users
            for user_id, ws in list(websocket_server.user_connections.items()):
                await websocket_server._safe_send_async(ws, notification_data)
        elif target == 'active':
            # Send to all active WebSocket connections
            for ws in list(websocket_server.connections):
                await websocket_server._safe_send_async(ws, notification_data)
        elif target == 'specific':
            # Send to specific users
            for user_id in target_ids:
                await websocket_server.send_to_user(str(user_id), notification_data)
        
        # Record admin transaction
        await Database.record_admin_transaction(
            admin_id=data.get('admin_id', 'system'),
            action='send_notification',
            target_type='notification',
            target_id=notification_id,
            details={
                'title': title,
                'message': message,
                'target': target,
                'target_count': len(target_ids) if target == 'specific' else 'all'
            }
        )
        
        return web.json_response({
            'success': True,
            'message': 'Notification sent successfully',
            'notification_id': notification_id,
            'sent_to': len(websocket_server.user_connections) if target == 'all' else len(target_ids) if target == 'specific' else 'all'
        })
        
    except Exception as e:
        logger.error(f"Error sending notification: {e}")
        return web.json_response({
            'success': False,
            'message': str(e)
        }, status=500)


# ==================== PAYMENT & WITHDRAWAL ADMIN ENDPOINTS ====================
@routes.get('/api/admin/payment/{payment_id}')
async def admin_get_payment_details(request):
    """Get payment (deposit) details"""
    try:
        payment_id = int(request.match_info['payment_id'])
        
        from database.db import Database
        
        with Database.get_cursor() as cursor:
            cursor.execute("""
                SELECT p.*, u.username, u.full_name 
                FROM payments p
                LEFT JOIN users u ON p.user_id = u.user_id
                WHERE p.id = ?
            """, (payment_id,))
            row = cursor.fetchone()
            
            if row:
                payment_dict = dict(row)
                payment_dict['amount'] = float(payment_dict['amount'])
                
                return web.json_response({
                    'success': True,
                    'payment': payment_dict
                }, dumps=lambda obj: json.dumps(obj, cls=CustomJSONEncoder))
            
            return web.json_response({
                'success': False,
                'message': 'Payment not found'
            }, status=404)
            
    except Exception as e:
        logger.error(f"Error getting payment details: {e}")
        return web.json_response({
            'success': False,
            'message': str(e)
        }, status=500)


@routes.get('/api/admin/withdrawal/{withdrawal_id}')
async def admin_get_withdrawal_details(request):
    """Get withdrawal details"""
    try:
        withdrawal_id = int(request.match_info['withdrawal_id'])
        
        from database.db import Database
        
        with Database.get_cursor() as cursor:
            cursor.execute("""
                SELECT wr.*, u.username, u.full_name 
                FROM withdrawal_requests wr
                LEFT JOIN users u ON wr.user_id = u.user_id
                WHERE wr.id = ?
            """, (withdrawal_id,))
            row = cursor.fetchone()
            
            if row:
                withdrawal_dict = dict(row)
                withdrawal_dict['amount'] = float(withdrawal_dict['amount'])
                
                return web.json_response({
                    'success': True,
                    'withdrawal': withdrawal_dict
                }, dumps=lambda obj: json.dumps(obj, cls=CustomJSONEncoder))
            
            return web.json_response({
                'success': False,
                'message': 'Withdrawal not found'
            }, status=404)
            
    except Exception as e:
        logger.error(f"Error getting withdrawal details: {e}")
        return web.json_response({
            'success': False,
            'message': str(e)
        }, status=500)


@routes.post('/api/admin/approvepayment')
async def admin_approve_payment_endpoint(request):
    """Approve a payment (deposit) request"""
    try:
        data = await request.json()
        
        payment_id = data.get('payment_id')
        admin_id = data.get('admin_id')
        notes = data.get('notes', '')
        
        if not payment_id or not admin_id:
            return web.json_response({
                'success': False,
                'message': 'payment_id and admin_id are required'
            }, status=400)
        
        from database.db import Database
        
        with Database.get_cursor() as cursor:
            # Get payment request
            cursor.execute("""
                SELECT p.* FROM payments p
                WHERE p.id = ? AND p.status = 'pending'
            """, (payment_id,))
            row = cursor.fetchone()
            
            if not row:
                return web.json_response({
                    'success': False,
                    'message': 'Payment not found or already processed'
                }, status=404)
            
            payment = dict(row)
            user_id = payment['user_id']
            amount = float(payment['amount'])
            
            # Mark payment as approved
            cursor.execute("""
                UPDATE payments 
                SET status = 'approved', 
                    processed_at = ?,
                    processed_by = ?,
                    admin_notes = ?
                WHERE id = ?
            """, (datetime.now(), admin_id, f'Approved by admin {admin_id}: {notes}', payment_id))
            
            # Add balance to user
            new_balance = await Database.add_user_balance(
                user_id=user_id,
                amount=amount,
                transaction_type='deposit',
                notes=f'Payment {payment_id} approved by admin {admin_id}'
            )
            
            # Record admin transaction
            await Database.record_admin_transaction(
                admin_id=admin_id,
                action='approve_payment',
                target_type='payment',
                target_id=str(payment_id),
                details={
                    'user_id': user_id,
                    'amount': amount,
                    'notes': notes
                }
            )
            
            return web.json_response({
                'success': True,
                'message': f'Payment {payment_id} approved successfully',
                'payment_id': payment_id,
                'user_id': user_id,
                'amount': amount
            })
            
    except Exception as e:
        logger.error(f"Error approving payment: {e}")
        return web.json_response({
            'success': False,
            'message': str(e)
        }, status=500)


@routes.post('/api/admin/approvewithdrawal')
async def admin_approve_withdrawal_endpoint(request):
    """Approve a withdrawal request - WITH USER NOTIFICATION"""
    try:
        data = await request.json()
        
        withdrawal_id = data.get('withdrawal_id')
        admin_id = data.get('admin_id')
        notes = data.get('notes', '')
        
        if not withdrawal_id or not admin_id:
            return web.json_response({
                'success': False,
                'message': 'withdrawal_id and admin_id are required'
            }, status=400)
        
        from database.db import Database
        
        # Get withdrawal details BEFORE processing
        with Database.get_cursor() as cursor:
            cursor.execute("""
                SELECT wr.*, u.username, u.full_name as user_full_name
                FROM withdrawal_requests wr
                LEFT JOIN users u ON wr.user_id = u.user_id
                WHERE wr.id = ? AND wr.status = 'pending'
            """, (withdrawal_id,))
            row = cursor.fetchone()
            
            if not row:
                return web.json_response({
                    'success': False,
                    'message': 'Withdrawal not found or already processed'
                }, status=404)
            
            withdrawal = dict(row)
            user_id = withdrawal['user_id']
            amount = float(withdrawal['amount'])
            payment_method = withdrawal.get('payment_method', withdrawal.get('method', 'Unknown'))
            phone_number = withdrawal.get('phone_number', 'N/A')
            full_name = withdrawal.get('full_name', withdrawal.get('user_full_name', 'N/A'))
            requested_at = withdrawal.get('requested_at', withdrawal.get('created_at', datetime.now()))
            
            # Mark withdrawal as approved
            cursor.execute("""
                UPDATE withdrawal_requests 
                SET status = 'approved', 
                    processed_at = ?,
                    processed_by = ?,
                    admin_notes = ?
                WHERE id = ? AND status = 'pending'
            """, (datetime.now(), admin_id, f'Approved by admin {admin_id}: {notes}', withdrawal_id))
            
            if cursor.rowcount == 0:
                return web.json_response({
                    'success': False,
                    'message': 'Failed to approve withdrawal - no rows updated'
                }, status=500)
            
            # Record transaction for approved withdrawal
            try:
                await Database.add_transaction(
                    user_id,
                    'withdrawal_approved',
                    -amount,
                    f"Withdrawal approved via {payment_method} to {phone_number}"
                )
            except Exception as tx_error:
                logger.error(f"Failed to record transaction: {tx_error}")
        
        # ============ ADD THIS NOTIFICATION CODE ============
        # Format time for notification
        time_str = ""
        try:
            if isinstance(requested_at, str):
                time_str = requested_at[:16] if len(requested_at) >= 16 else requested_at
            else:
                time_str = requested_at.strftime('%Y-%m-%d %H:%M')
        except:
            time_str = "Unknown"
        
        # Get currency from config
        currency = "birr"
        try:
            from config import GAME_CONFIG
            currency = GAME_CONFIG.get('currency', 'birr')
        except:
            pass
        
        # SEND APPROVAL NOTIFICATION TO USER
        approval_message = (
            f"✅ *የገንዘብ ማውጣት ተሳክቷል!*\n\n"
            f"💰 *መጠን:* {amount:.2f} {currency}\n"
            f"🏦 *ዘዴ:* {payment_method}\n"
            f"👤 *ሙሉ ስም:* {full_name}\n"
            f"📱 *ስልክ:* {phone_number}\n"
            f"⏰ *የተጠየቀበት ጊዜ:* {time_str}\n\n"
            f"💳 ገንዘብዎ ወደ {phone_number} ተልኳል።\n"
            f"🎮 መጫወት ለመቀጠል: /play\n"
            f"💰 ቀሪ ሒሳብ ለማየት: /balance"
        )
        
        # Send notification and log result
        from web_server import send_notification_to_user
        notification_sent = await send_notification_to_user(user_id, approval_message)
        if notification_sent:
            logger.info(f"✅ Approval notification sent to user {user_id} for withdrawal {withdrawal_id}")
        else:
            logger.error(f"❌ Failed to send approval notification to user {user_id}")
        
        return web.json_response({
            'success': True,
            'message': f'Withdrawal {withdrawal_id} approved successfully',
            'withdrawal_id': withdrawal_id,
            'user_id': user_id,
            'amount': amount,
            'notification_sent': notification_sent
        })
            
    except Exception as e:
        logger.error(f"❌ Error approving withdrawal: {e}", exc_info=True)
        return web.json_response({
            'success': False,
            'message': str(e)
        }, status=500)


@routes.post('/api/admin/rejectwithdrawal')
async def admin_reject_withdrawal_endpoint(request):
    """Reject a withdrawal request - WITH USER NOTIFICATION"""
    try:
        data = await request.json()
        
        withdrawal_id = data.get('withdrawal_id')
        admin_id = data.get('admin_id')
        reason = data.get('reason', '')
        
        if not withdrawal_id or not admin_id:
            return web.json_response({
                'success': False,
                'message': 'withdrawal_id and admin_id are required'
            }, status=400)
        
        from database.db import Database
        
        # Get withdrawal details BEFORE processing
        with Database.get_cursor() as cursor:
            cursor.execute("""
                SELECT wr.*, u.username, u.full_name as user_full_name
                FROM withdrawal_requests wr
                LEFT JOIN users u ON wr.user_id = u.user_id
                WHERE wr.id = ? AND wr.status = 'pending'
            """, (withdrawal_id,))
            row = cursor.fetchone()
            
            if not row:
                return web.json_response({
                    'success': False,
                    'message': 'Withdrawal not found or already processed'
                }, status=404)
            
            withdrawal = dict(row)
            user_id = withdrawal['user_id']
            amount = float(withdrawal['amount'])
            payment_method = withdrawal.get('payment_method', withdrawal.get('method', 'Unknown'))
            phone_number = withdrawal.get('phone_number', 'N/A')
            full_name = withdrawal.get('full_name', withdrawal.get('user_full_name', 'N/A'))
            requested_at = withdrawal.get('requested_at', withdrawal.get('created_at', datetime.now()))
            
            # Mark withdrawal as rejected
            cursor.execute("""
                UPDATE withdrawal_requests 
                SET status = 'rejected', 
                    processed_at = ?,
                    processed_by = ?,
                    admin_notes = ?
                WHERE id = ? AND status = 'pending'
            """, (datetime.now(), admin_id, f'Rejected by admin {admin_id}: {reason}', withdrawal_id))
            
            if cursor.rowcount == 0:
                return web.json_response({
                    'success': False,
                    'message': 'Failed to reject withdrawal - no rows updated'
                }, status=500)
            
            # Refund the amount to user balance
            try:
                await Database.add_user_balance(
                    user_id=user_id,
                    amount=amount,
                    transaction_type='withdrawal_refund',
                    notes=f'Withdrawal {withdrawal_id} rejected and refunded: {reason}'
                )
                logger.info(f"✅ Refunded {amount} to user {user_id}")
            except Exception as refund_error:
                logger.error(f"❌ Failed to refund user: {refund_error}")
        
        # Get updated balance for notification
        try:
            user = await Database.get_user(user_id)
            new_balance = user.get('balance', 0.00) if user else 0.00
        except:
            new_balance = 0.00
        
        # ============ ADD THIS NOTIFICATION CODE ============
        # Format time for notification
        time_str = ""
        try:
            if isinstance(requested_at, str):
                time_str = requested_at[:16] if len(requested_at) >= 16 else requested_at
            else:
                time_str = requested_at.strftime('%Y-%m-%d %H:%M')
        except:
            time_str = "Unknown"
        
        # Get currency from config
        currency = "birr"
        try:
            from config import GAME_CONFIG
            currency = GAME_CONFIG.get('currency', 'birr')
        except:
            pass
        
        # Get support user
        support_user = "@Habeshabingoo"
        try:
            from config import SUPPORT_TELEGRAM_USER
            support_user = SUPPORT_TELEGRAM_USER
        except:
            pass
        
        # SEND REJECTION NOTIFICATION TO USER
        rejection_reason = reason or "በአስተዳዳሪ ውድቅ ተደርጓል"
        
        rejection_message = (
            f"❌ *የገንዘብ ማውጣት ተቋርጧል!*\n\n"
            f"💰 *መጠን:* {amount:.2f} {currency}\n"
            f"🏦 *ዘዴ:* {payment_method}\n"
            f"👤 *ሙሉ ስም:* {full_name}\n"
            f"📱 *ስልክ:* {phone_number}\n"
            f"⏰ *የተጠየቀበት ጊዜ:* {time_str}\n\n"
            f"📝 *ምክንያት:* {rejection_reason}\n\n"
            f"💰 *የተመለሰ መጠን:* {amount:.2f} {currency}\n"
            f"🏦 *አዲስ ቀሪ ሒሳብ:* {new_balance:.2f} {currency}\n\n"
            f"🔄 እባክዎ አዲስ የገንዘብ ማውጣት ጥያቄ ይጀምሩ /withdraw\n\n"
            f"❓ ጥያቄ ካለዎት ድጋፍ ያግኙ: {support_user}"
        )
        
        # Send notification and log result
        from web_server import send_notification_to_user
        notification_sent = await send_notification_to_user(user_id, rejection_message)
        if notification_sent:
            logger.info(f"✅ Rejection notification sent to user {user_id} for withdrawal {withdrawal_id}")
        else:
            logger.error(f"❌ Failed to send rejection notification to user {user_id}")
        
        return web.json_response({
            'success': True,
            'message': f'Withdrawal {withdrawal_id} rejected and refunded',
            'withdrawal_id': withdrawal_id,
            'user_id': user_id,
            'amount': amount,
            'new_balance': new_balance,
            'notification_sent': notification_sent
        })
            
    except Exception as e:
        logger.error(f"❌ Error rejecting withdrawal: {e}", exc_info=True)
        return web.json_response({
            'success': False,
            'message': str(e)
        }, status=500)

# ==================== ADD THESE MISSING ADMIN API ENDPOINTS ====================

@routes.get('/api/admin/database-info')
async def admin_database_info(request):
    """Get database information - size, last modified, record counts"""
    try:
        from database.db import Database
        import os
        import sqlite3
        
        # Get database file path
        db_path = Database._db_path
        
        if not os.path.exists(db_path):
            return web.json_response({
                'success': False,
                'message': 'Database file not found'
            }, status=404)
        
        # Get file stats
        file_stats = os.stat(db_path)
        file_size_mb = file_stats.st_size / (1024 * 1024)
        last_modified = datetime.fromtimestamp(file_stats.st_mtime)
        
        # Get record counts from all tables using Database methods
        record_counts = {}
        
        # Count users
        total_users = await Database.get_total_users()
        record_counts['users'] = total_users
        
        # Count games
        total_games = await Database.get_total_games()
        record_counts['games'] = total_games
        
        # Count transactions
        with Database.get_cursor() as cursor:
            cursor.execute("SELECT COUNT(*) as count FROM transactions")
            row = cursor.fetchone()
            record_counts['transactions'] = row[0] if row and row[0] else 0
        
        # Count payments
        with Database.get_cursor() as cursor:
            cursor.execute("SELECT COUNT(*) as count FROM payments")
            row = cursor.fetchone()
            record_counts['payments'] = row[0] if row and row[0] else 0
        
        # Count withdrawals
        with Database.get_cursor() as cursor:
            cursor.execute("SELECT COUNT(*) as count FROM withdrawal_requests")
            row = cursor.fetchone()
            record_counts['withdrawal_requests'] = row[0] if row and row[0] else 0
        
        # Count player cards
        with Database.get_cursor() as cursor:
            cursor.execute("SELECT COUNT(*) as count FROM player_cards WHERE is_active = 1")
            row = cursor.fetchone()
            record_counts['active_cards'] = row[0] if row and row[0] else 0
        
        # Count called numbers
        with Database.get_cursor() as cursor:
            cursor.execute("SELECT COUNT(*) as count FROM called_numbers")
            row = cursor.fetchone()
            record_counts['called_numbers'] = row[0] if row and row[0] else 0
        
        # Count commission records
        with Database.get_cursor() as cursor:
            cursor.execute("SELECT COUNT(*) as count FROM commission_records")
            row = cursor.fetchone()
            record_counts['commission_records'] = row[0] if row and row[0] else 0
        
        # Count fake players
        with Database.get_cursor() as cursor:
            cursor.execute("SELECT COUNT(*) as count FROM fake_players")
            row = cursor.fetchone()
            record_counts['fake_players'] = row[0] if row and row[0] else 0
        
        return web.json_response({
            'success': True,
            'database': {
                'path': db_path,
                'size_mb': round(file_size_mb, 2),
                'modified_time': last_modified.isoformat(),
                'record_counts': record_counts
            },
            'timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Error getting database info: {e}")
        return web.json_response({
            'success': False,
            'message': str(e)
        }, status=500)


@routes.get('/api/admin/download-database')
async def admin_download_database(request):
    """Download database file with optional ZIP or GZIP compression"""
    try:
        compress = request.query.get('compress', 'true').lower() == 'true'
        compression_format = request.query.get('format', 'zip').lower()  # default zip

        from database.db import Database
        import os
        import gzip
        import zipfile
        import shutil
        import tempfile
        from aiohttp.web import FileResponse
        from datetime import datetime

        db_path = Database._db_path

        if not os.path.exists(db_path):
            return web.json_response({
                'success': False,
                'message': 'Database file not found'
            }, status=404)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        # =============================
        # ZIP COMPRESSION (DEFAULT)
        # =============================
        if compress and compression_format == 'zip':
            temp_dir = tempfile.mkdtemp()
            zip_filename = f"habesha_bingo_backup_{timestamp}.zip"
            zip_path = os.path.join(temp_dir, zip_filename)

            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                zipf.write(
                    db_path,
                    arcname=f"habesha_bingo_backup_{timestamp}.db"
                )

            file_size = os.path.getsize(zip_path)

            response = FileResponse(
                zip_path,
                headers={
                    'Content-Disposition': f'attachment; filename="{zip_filename}"',
                    'Content-Type': 'application/zip',
                    'Content-Length': str(file_size)
                }
            )

            async def cleanup():
                try:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                except:
                    pass

            response.cleanup = cleanup
            return response

        # =============================
        # GZIP COMPRESSION
        # =============================
        if compress and compression_format == 'gz':
            temp_dir = tempfile.mkdtemp()
            gz_path = os.path.join(
                temp_dir,
                f"habesha_bingo_backup_{timestamp}.db.gz"
            )

            with open(db_path, 'rb') as f_in:
                with gzip.open(gz_path, 'wb', compresslevel=9) as f_out:
                    shutil.copyfileobj(f_in, f_out)

            file_size = os.path.getsize(gz_path)

            response = FileResponse(
                gz_path,
                headers={
                    'Content-Disposition': f'attachment; filename="{os.path.basename(gz_path)}"',
                    'Content-Type': 'application/gzip',
                    'Content-Length': str(file_size)
                }
            )

            async def cleanup():
                try:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                except:
                    pass

            response.cleanup = cleanup
            return response

        # =============================
        # RAW DATABASE
        # =============================
        file_size = os.path.getsize(db_path)
        filename = f"habesha_bingo_backup_{timestamp}.db"

        return FileResponse(
            db_path,
            headers={
                'Content-Disposition': f'attachment; filename="{filename}"',
                'Content-Type': 'application/x-sqlite3',
                'Content-Length': str(file_size)
            }
        )

    except Exception as e:
        return web.json_response({
            'success': False,
            'message': str(e)
        }, status=500)
        
        
        
@routes.post('/api/admin/restore-database')
async def admin_restore_database(request):
    """
    Restore database from .db, .gz, or .zip safely.
    Includes WAL cleanup and forced application restart.
    """
    try:
        reader = await request.multipart()

        field = await reader.next()
        if not field or field.name != 'database':
            return web.json_response({
                'success': False,
                'message': 'No database file uploaded'
            }, status=400)

        from database.db import Database
        import os
        import shutil
        import gzip
        import zipfile
        import tempfile
        import sqlite3
        import asyncio
        from datetime import datetime

        db_path = Database._db_path
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        # =============================
        # CREATE BACKUP
        # =============================
        backup_path = f"{db_path}.backup_{timestamp}"
        if os.path.exists(db_path):
            shutil.copy2(db_path, backup_path)
            logger.info(f"✅ Created pre-restore backup at {backup_path}")

        # =============================
        # SAVE UPLOADED FILE
        # =============================
        temp_fd, temp_path = tempfile.mkstemp()
        os.close(temp_fd)

        size = 0
        with open(temp_path, 'wb') as f:
            while True:
                chunk = await field.read_chunk()
                if not chunk:
                    break
                size += len(chunk)
                f.write(chunk)

        if size == 0:
            os.unlink(temp_path)
            return web.json_response({
                'success': False,
                'message': 'Uploaded file is empty'
            }, status=400)

        if size > 10000 * 1024 * 1024:
            os.unlink(temp_path)
            return web.json_response({
                'success': False,
                'message': 'File too large (max 10000MB)'
            }, status=400)

        # =============================
        # DETECT COMPRESSION BY SIGNATURE
        # =============================
        compression_type = None
        final_db_path = temp_path

        if zipfile.is_zipfile(temp_path):
            compression_type = 'zip'
            logger.info("📦 Detected ZIP archive")
        else:
            with open(temp_path, 'rb') as f:
                if f.read(2) == b'\x1f\x8b':
                    compression_type = 'gzip'
                    logger.info("🔒 Detected GZIP compressed file")

        # =============================
        # HANDLE ZIP
        # =============================
        if compression_type == 'zip':
            try:
                extract_dir = tempfile.mkdtemp()

                with zipfile.ZipFile(temp_path, 'r') as zipf:
                    db_files = [
                        f for f in zipf.namelist()
                        if f.endswith(('.db', '.sqlite', '.sqlite3'))
                    ]

                    if not db_files:
                        raise ValueError("ZIP does not contain a valid database file")

                    logger.info(f"📦 Found database file in ZIP: {db_files[0]}")
                    zipf.extract(db_files[0], extract_dir)

                    final_db_path = os.path.join(
                        extract_dir,
                        os.path.basename(db_files[0])
                    )

                os.unlink(temp_path)

            except Exception as e:
                logger.error(f"❌ ZIP extraction failed: {e}")
                os.unlink(temp_path)
                shutil.rmtree(extract_dir, ignore_errors=True)
                return web.json_response({
                    'success': False,
                    'message': f'Invalid ZIP file: {str(e)}'
                }, status=400)

        # =============================
        # HANDLE GZIP
        # =============================
        elif compression_type == 'gzip':
            try:
                decompressed_path = temp_path + '.db'
                with gzip.open(temp_path, 'rb') as f_in:
                    with open(decompressed_path, 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)

                os.unlink(temp_path)
                final_db_path = decompressed_path
                logger.info("🔓 GZIP decompression complete")

            except Exception as e:
                logger.error(f"❌ GZIP decompression failed: {e}")
                os.unlink(temp_path)
                return web.json_response({
                    'success': False,
                    'message': f'Invalid GZIP file: {str(e)}'
                }, status=400)

        # =============================
        # VALIDATE SQLITE DATABASE
        # =============================
        try:
            logger.info("🔍 Validating database file...")
            conn = sqlite3.connect(final_db_path)
            cursor = conn.cursor()

            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]

            required_tables = ['users', 'games', 'transactions']
            for table in required_tables:
                if table not in tables:
                    raise ValueError(f"Missing required table: {table}")

            # Get record counts for logging
            cursor.execute("SELECT COUNT(*) FROM users")
            user_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM games")
            game_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM transactions")
            transaction_count = cursor.fetchone()[0]
            
            conn.close()
            
            logger.info(f"✅ Database validation passed - Users: {user_count}, Games: {game_count}, Transactions: {transaction_count}")

        except Exception as e:
            logger.error(f"❌ Database validation failed: {e}")
            if os.path.exists(final_db_path):
                os.unlink(final_db_path)
            
            # Restore from backup
            if os.path.exists(backup_path):
                shutil.copy2(backup_path, db_path)
                logger.info("📦 Restored from backup after validation failure")
            
            return web.json_response({
                'success': False,
                'message': f'Invalid database: {str(e)}'
            }, status=400)

        # =============================
        # CLOSE ALL DATABASE CONNECTIONS
        # =============================
        logger.info("🔌 Closing database connections...")
        if hasattr(Database, 'close_connection'):
            await Database.close_connection()

        # Force close any lingering connections
        if hasattr(Database, '_connection'):
            Database._connection = None
        if hasattr(Database, '_db'):
            Database._db = None

        await asyncio.sleep(1)

        # =============================
        # REMOVE WAL & SHM FILES
        # =============================
        wal_path = db_path + "-wal"
        shm_path = db_path + "-shm"
        
        for extra_file in [wal_path, shm_path]:
            if os.path.exists(extra_file):
                try:
                    os.remove(extra_file)
                    logger.info(f"🧹 Removed leftover file: {extra_file}")
                except Exception as e:
                    logger.warning(f"⚠️ Could not remove {extra_file}: {e}")

        # =============================
        # REPLACE DATABASE FILE
        # =============================
        try:
            logger.info(f"💾 Replacing database file...")
            shutil.move(final_db_path, db_path)
            logger.info(f"✅ Database file replaced successfully")
            
            # Clean up extraction directory if it exists
            if compression_type == 'zip' and 'extract_dir' in locals():
                shutil.rmtree(extract_dir, ignore_errors=True)

            # =============================
            # SUCCESS RESPONSE + RESTART
            # =============================
            response = web.json_response({
                'success': True,
                'message': 'Database restored successfully. Server restarting...',
                'restart_in': 2,
                'backup_path': backup_path if os.path.exists(backup_path) else None,
                'stats': {
                    'users': user_count,
                    'games': game_count,
                    'transactions': transaction_count
                },
                'compression_type': compression_type or 'none'
            })

            # Schedule server restart
            async def restart_server():
                await asyncio.sleep(2)  # Give time for response to be sent
                logger.info("🔄 Force restarting server after database restore...")
                os._exit(1)  # Force exit - Docker/Railway will restart

            asyncio.create_task(restart_server())
            logger.info("⏰ Server restart scheduled in 2 seconds")

            return response

        except Exception as e:
            logger.error(f"❌ Error during database replace: {e}")
            
            # Restore from backup
            if os.path.exists(backup_path):
                shutil.copy2(backup_path, db_path)
                logger.info("📦 Restored from backup after replace failure")
            
            return web.json_response({
                'success': False,
                'message': f'Restore failed: {str(e)}'
            }, status=500)

    except Exception as e:
        logger.error(f"❌ Error in restore database endpoint: {e}", exc_info=True)
        return web.json_response({
            'success': False,
            'message': str(e)
        }, status=500)


@routes.post('/api/admin/force-reset-game')
async def admin_force_reset_game(request):
    """Admin: Force reset the current game - complete reset"""
    try:
        data = await request.json()
        admin_id = data.get('admin_id', 'system')
        game_id = data.get('game_id')
        
        from database.db import Database
        from utils.game_manager import game_manager
        from utils.number_caller import number_caller
        
        logger.info(f"🔄 Admin {admin_id} initiating force game reset for {game_id or 'current game'}")
        
        # If no game_id provided, get current active game
        if not game_id:
            active_game = await game_manager.get_active_round_game()
            if active_game:
                game_id = active_game.get('game_id')
        
        if game_id:
            # Stop number calling
            await number_caller.stop_number_calling_for_game(game_id)
            logger.info(f"Stopped number calling for game {game_id}")
            
            # Update game status to completed
            await Database.update_game_status(game_id, 'completed')
            
            # Clear any fake players for this game
            if hasattr(game_manager, 'fake_user_manager'):
                if game_id in game_manager.fake_user_manager.game_fake_cards:
                    del game_manager.fake_user_manager.game_fake_cards[game_id]
                    logger.info(f"Cleared fake cards for game {game_id}")
            
            # Clear any pending winners
            if hasattr(game_manager, '_winners'):
                if game_id in game_manager._winners:
                    del game_manager._winners[game_id]
            
            logger.info(f"Reset game {game_id}")
        else:
            logger.info("No active game to reset")
        
        # Start a new game immediately
        result = await game_manager.start_new_round_game()
        
        if result.get('success'):
            new_game = await game_manager.get_active_round_game()
            new_game_id = new_game.get('game_id') if new_game else None
            
            # Broadcast to all connected clients
            await websocket_server.broadcast_with_retry({
                'type': 'game_reset',
                'message': 'Game was force reset by admin',
                'new_game_id': new_game_id,
                'timestamp': datetime.now().isoformat()
            })
            
            # Record admin transaction
            try:
                await Database.record_admin_transaction(
                    admin_id=admin_id,
                    action='force_reset_game',
                    target_type='game',
                    target_id=game_id or 'none',
                    details={
                        'new_game_id': new_game_id
                    }
                )
            except:
                logger.warning("Could not record admin transaction")
            
            return web.json_response({
                'success': True,
                'message': 'Game reset successfully and new game started',
                'new_game_id': new_game_id
            })
        else:
            return web.json_response({
                'success': False,
                'message': result.get('message', 'Failed to start new game after reset')
            }, status=500)
        
    except Exception as e:
        logger.error(f"Error force resetting game: {e}", exc_info=True)
        return web.json_response({
            'success': False,
            'message': str(e)
        }, status=500)


@routes.get('/api/admin/health')
async def admin_health_check(request):
    """Admin health check endpoint with detailed status"""
    try:
        from database.db import Database
        from utils.game_manager import game_manager
        
        # Check database connection
        db_status = "ok"
        db_error = None
        try:
            with Database.get_cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
        except Exception as e:
            db_status = "error"
            db_error = str(e)
        
        # Get system status
        system_status = await game_manager.get_system_status() if hasattr(game_manager, 'get_system_status') else {}
        
        # Get websocket status
        ws_status = {
            'connections': len(websocket_server.connections),
            'authenticated_users': len(websocket_server.user_connections)
        }
        
        return web.json_response({
            'success': True,
            'status': 'healthy' if db_status == 'ok' else 'degraded',
            'timestamp': datetime.now().isoformat(),
            'database': {
                'status': db_status,
                'error': db_error
            },
            'websocket': ws_status,
            'game_manager': system_status,
            'version': '1.0.0'
        })
        
    except Exception as e:
        logger.error(f"Error in health check: {e}")
        return web.json_response({
            'success': False,
            'status': 'unhealthy',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }, status=500)


# ==================== USER SEARCH API FOR ADMIN PANEL - FIXED ====================

@routes.get('/api/admin/users/search')
@routes.get('/api/admin/users/search/')
async def admin_search_users(request):
    """Search users by ID, username, or full name - for admin panel - FIXED"""
    try:
        query = request.query.get('q', '').strip()
        search_type = request.query.get('type', 'all')  # all, id, username, name
        limit = int(request.query.get('limit', 50))
        
        logger.info(f"🔍 User search request - query: '{query}', type: {search_type}, limit: {limit}")
        
        if not query or len(query) < 2:
            return web.json_response({
                'success': True,
                'users': [],
                'total': 0,
                'message': 'Please enter at least 2 characters to search'
            })
        
        from database.db import Database
        
        with Database.get_cursor() as cursor:
            # Build search query based on type
            if search_type == 'id':
                # Search by user_id (exact or partial match)
                try:
                    # Try to parse as integer for exact match
                    user_id = int(query)
                    cursor.execute("""
                        SELECT 
                            user_id, username, full_name, balance, 
                            created_at, status,
                            (SELECT COUNT(*) FROM player_cards WHERE user_id = users.user_id AND is_active = 1) as games_played,
                            (SELECT COUNT(*) FROM games WHERE winner_id = users.user_id) as wins,
                            (SELECT COALESCE(SUM(prize_pool), 0) FROM games WHERE winner_id = users.user_id) as total_winnings
                        FROM users 
                        WHERE user_id = ?
                        LIMIT ?
                    """, (user_id, limit))
                except ValueError:
                    # If not an integer, search as string
                    cursor.execute("""
                        SELECT 
                            user_id, username, full_name, balance, 
                            created_at, status,
                            (SELECT COUNT(*) FROM player_cards WHERE user_id = users.user_id AND is_active = 1) as games_played,
                            (SELECT COUNT(*) FROM games WHERE winner_id = users.user_id) as wins,
                            (SELECT COALESCE(SUM(prize_pool), 0) FROM games WHERE winner_id = users.user_id) as total_winnings
                        FROM users 
                        WHERE CAST(user_id AS TEXT) LIKE ?
                        LIMIT ?
                    """, (f'%{query}%', limit))
            
            elif search_type == 'username':
                cursor.execute("""
                    SELECT 
                        user_id, username, full_name, balance, 
                        created_at, status,
                        (SELECT COUNT(*) FROM player_cards WHERE user_id = users.user_id AND is_active = 1) as games_played,
                        (SELECT COUNT(*) FROM games WHERE winner_id = users.user_id) as wins,
                        (SELECT COALESCE(SUM(prize_pool), 0) FROM games WHERE winner_id = users.user_id) as total_winnings
                    FROM users 
                    WHERE username LIKE ? OR username LIKE ?
                    LIMIT ?
                """, (f'%{query}%', f'{query}%', limit))
            
            elif search_type == 'name':
                cursor.execute("""
                    SELECT 
                        user_id, username, full_name, balance, 
                        created_at, status,
                        (SELECT COUNT(*) FROM player_cards WHERE user_id = users.user_id AND is_active = 1) as games_played,
                        (SELECT COUNT(*) FROM games WHERE winner_id = users.user_id) as wins,
                        (SELECT COALESCE(SUM(prize_pool), 0) FROM games WHERE winner_id = users.user_id) as total_winnings
                    FROM users 
                    WHERE full_name LIKE ? OR full_name LIKE ?
                    LIMIT ?
                """, (f'%{query}%', f'{query}%', limit))
            
            else:  # 'all' - search across all fields
                cursor.execute("""
                    SELECT 
                        user_id, username, full_name, balance, 
                        created_at, status,
                        (SELECT COUNT(*) FROM player_cards WHERE user_id = users.user_id AND is_active = 1) as games_played,
                        (SELECT COUNT(*) FROM games WHERE winner_id = users.user_id) as wins,
                        (SELECT COALESCE(SUM(prize_pool), 0) FROM games WHERE winner_id = users.user_id) as total_winnings
                    FROM users 
                    WHERE 
                        CAST(user_id AS TEXT) LIKE ? OR
                        username LIKE ? OR
                        full_name LIKE ?
                    ORDER BY 
                        CASE 
                            WHEN CAST(user_id AS TEXT) = ? THEN 1
                            WHEN username = ? THEN 2
                            WHEN full_name = ? THEN 3
                            ELSE 4
                        END,
                        created_at DESC
                    LIMIT ?
                """, (f'%{query}%', f'%{query}%', f'%{query}%', 
                      query, query, query, limit))
            
            rows = cursor.fetchall()
            users = []
            
            for row in rows:
                user = {
                    'user_id': row[0],
                    'username': row[1],
                    'full_name': row[2],
                    'balance': float(row[3] or 0),
                    'created_at': row[4].isoformat() if row[4] else None,
                    'status': row[5] or 'active',
                    'games_played': row[6] or 0,
                    'wins': row[7] or 0,
                    'total_winnings': float(row[8] or 0)
                }
                users.append(user)
            
            logger.info(f"🔍 User search: '{query}' - found {len(users)} users")
            
            return web.json_response({
                'success': True,
                'users': users,
                'total': len(users),
                'query': query,
                'search_type': search_type,
                'timestamp': datetime.now().isoformat()
            }, dumps=lambda obj: json.dumps(obj, cls=CustomJSONEncoder))
            
    except Exception as e:
        logger.error(f"Error searching users: {e}")
        return web.json_response({
            'success': False,
            'message': str(e)
        }, status=500)


# ==================== GET SINGLE USER DETAILS (already exists but improved) ====================
@routes.get('/api/admin/user/{user_id}')
async def admin_get_user_details(request):
    """Get detailed user information - improved with more stats"""
    try:
        user_id_str = request.match_info['user_id']
        user_id = parse_user_id(user_id_str)
        
        from database.db import Database
        
        with Database.get_cursor() as cursor:
            # Get user details with aggregated stats
            cursor.execute("""
                SELECT 
                    u.*, 
                    COUNT(DISTINCT pc.game_id) as total_games_played,
                    COUNT(pc.id) as total_cards_purchased,
                    SUM(CASE WHEN g.winner_id = u.user_id THEN 1 ELSE 0 END) as total_wins,
                    SUM(CASE WHEN g.winner_id = u.user_id THEN g.prize_pool ELSE 0 END) as total_winnings,
                    SUM(CASE WHEN pc.is_fake = 0 AND pc.is_active = 1 THEN 1 ELSE 0 END) as active_cards,
                    (SELECT COUNT(*) FROM transactions WHERE user_id = u.user_id) as total_transactions,
                    (SELECT SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END) FROM transactions WHERE user_id = u.user_id) as total_deposits,
                    (SELECT SUM(CASE WHEN amount < 0 THEN ABS(amount) ELSE 0 END) FROM transactions WHERE user_id = u.user_id) as total_withdrawals
                FROM users u
                LEFT JOIN player_cards pc ON u.user_id = pc.user_id
                LEFT JOIN games g ON pc.game_id = g.game_id AND g.winner_id = u.user_id
                WHERE u.user_id = ?
                GROUP BY u.user_id
            """, (user_id,))
            
            row = cursor.fetchone()
            
            if row:
                user_data = dict(row)
                # Convert Decimal to float
                for key, value in user_data.items():
                    if isinstance(value, decimal.Decimal):
                        user_data[key] = float(value)
                
                # Get recent transactions
                cursor.execute("""
                    SELECT * FROM transactions 
                    WHERE user_id = ? 
                    ORDER BY created_at DESC 
                    LIMIT 20
                """, (user_id,))
                
                transactions = []
                for tx_row in cursor.fetchall():
                    tx_data = dict(tx_row)
                    if isinstance(tx_data.get('amount'), decimal.Decimal):
                        tx_data['amount'] = float(tx_data['amount'])
                    transactions.append(tx_data)
                
                user_data['recent_transactions'] = transactions
                
                # Get game history
                cursor.execute("""
                    SELECT 
                        g.game_id,
                        g.round_number,
                        g.status,
                        g.created_at as game_date,
                        g.prize_pool,
                        pc.card_index,
                        pc.is_active,
                        CASE WHEN g.winner_id = u.user_id THEN 1 ELSE 0 END as is_winner
                    FROM games g
                    JOIN player_cards pc ON g.game_id = pc.game_id
                    WHERE pc.user_id = ? AND pc.is_active = 1
                    ORDER BY g.created_at DESC
                    LIMIT 10
                """, (user_id,))
                
                game_history = []
                for game_row in cursor.fetchall():
                    game_data = dict(game_row)
                    if isinstance(game_data.get('prize_pool'), decimal.Decimal):
                        game_data['prize_pool'] = float(game_data['prize_pool'])
                    game_history.append(game_data)
                
                user_data['game_history'] = game_history
                
                return web.json_response({
                    'success': True,
                    'user': user_data,
                    'timestamp': datetime.now().isoformat()
                }, dumps=lambda obj: json.dumps(obj, cls=CustomJSONEncoder))
            
            return web.json_response({
                'success': False,
                'message': 'User not found'
            }, status=404)
            
    except Exception as e:
        logger.error(f"Error getting user details: {e}")
        return web.json_response({
            'success': False,
            'message': str(e)
        }, status=500)


# ==================== DEBUG ENDPOINT ====================
@routes.get('/api/debug/card/{user_id}/{game_id}')
async def debug_user_card(request):
    """Debug endpoint to check user card data"""
    try:
        user_id = int(request.match_info['user_id'])
        game_id = request.match_info['game_id']
        
        from database.db import Database
        
        user_card = await Database.get_user_card_in_game(user_id, game_id)
        
        if not user_card:
            return web.json_response({
                'success': False,
                'message': 'No card found'
            })
        
        # Parse card data
        card_data = None
        if user_card.get('card_data'):
            try:
                card_data = json.loads(user_card['card_data'])
            except:
                card_data = user_card['card_data']
        
        return web.json_response({
            'success': True,
            'card_id': user_card.get('id'),
            'card_index': user_card.get('card_index'),
            'card_data': card_data,
            'raw_card_data': user_card.get('card_data'),
            'user_id': user_id,
            'game_id': game_id
        })
        
    except Exception as e:
        logger.error(f"Debug error: {e}")
        return web.json_response({
            'success': False,
            'message': str(e)
        }, status=500)


# ==================== SYNC API ENDPOINT ====================
@routes.post('/api/game/{game_id}/sync')
async def sync_game_state(request):
    """Sync frontend state with server (source of truth) - FIXED COUNTDOWN"""
    try:
        game_id = request.match_info['game_id']
        data = await request.json()
        
        from database.db import Database
        from utils.game_manager import game_manager
        
        # Get server state via game_manager
        active_game = await game_manager.get_active_round_game()
        
        if not active_game or active_game.get('game_id') != game_id:
            return web.json_response({
                'corrected': False,
                'message': 'Game not active',
                'has_active_game': False
            })
        
        server_status = active_game.get('status', 'unknown')
        
        # Calculate server countdown via game_manager - FIXED
        game_status = await game_manager.get_game_status(game_id)
        if not game_status.get('success'):
            return web.json_response({
                'corrected': False,
                'message': game_status.get('message', 'Error getting game status')
            })
        
        # FIX: Get countdown from game_status, not from separate calculation
        server_countdown = game_status.get('countdown_remaining', 30)
        
        server_called = await Database.get_drawn_numbers(game_id)
        server_player_count = await Database.count_game_players(game_id)
        server_prize_pool = float(active_game.get('prize_pool', 0))
        
        # Get client state
        client_phase = data.get('game_phase', 'unknown')
        client_called = data.get('called_numbers', [])
        client_countdown = data.get('countdown', 30)
        
        corrected = False
        
        # Check for significant differences
        if server_status != client_phase:
            # Phase mismatch
            corrected = True
            logger.info(f"Phase correction for game {game_id}: {client_phase} -> {server_status}")
        
        # Check countdown - if difference is more than 5 seconds, correct
        if abs(server_countdown - client_countdown) > 5:
            corrected = True
            logger.info(f"Countdown correction for game {game_id}: client {client_countdown}s, server {server_countdown}s")
        
        # Check called numbers
        if len(server_called) > len(client_called) + 2:
            # Client missing more than 2 numbers
            corrected = True
            logger.info(f"Called numbers correction for game {game_id}: client has {len(client_called)}, server has {len(server_called)}")
        
        # Prepare response
        response_data = {
            'corrected': corrected,
            'has_active_game': True,
            'server_state': {
                'game_phase': server_status,
                'game_status': server_status,
                'called_numbers': server_called,
                'player_count': server_player_count,
                'prize_pool': server_prize_pool,
                'game_active': server_status == 'active',
                'countdown_remaining': server_countdown,  # FIXED: Use consistent countdown
                'total_cards': await Database.count_sold_cards(game_id),
                'current_number': active_game.get('current_number'),
                'round_number': active_game.get('round_number', 1),
                'card_price': float(active_game.get('card_price', 10.00)),
                'has_winner': server_status == 'winner_display'
            }
        }
        
        return web.json_response(
            convert_to_json_serializable(response_data), 
            dumps=lambda obj: json.dumps(obj, cls=CustomJSONEncoder)
        )
        
    except Exception as e:
        logger.error(f"Sync error: {e}", exc_info=True)
        return web.json_response({
            'corrected': False,
            'message': 'Sync error',
            'has_active_game': False
        }, status=500)


# ==================== FIXED COMPLETE STATE ENDPOINT ====================
@routes.get('/api/game/{game_id}/complete-state/{user_id}')
async def get_complete_game_state(request):
    """Get complete game state for a client (for reconnection) - FIXED: Shows correct prize pool"""
    try:
        game_id = request.match_info['game_id']
        user_id_str = request.match_info['user_id']
        user_id = parse_user_id(user_id_str)
        
        from database.db import Database
        from utils.game_manager import game_manager
        
        logger.info(f"📡 Complete state requested for game {game_id}, user {user_id}")
        
        # Get game via game_manager
        game = await Database.get_game(game_id)
        if not game:
            logger.warning(f"Game {game_id} not found for complete state")
            return web.json_response({
                'success': False,
                'message': 'Game not found'
            }, status=404)
        
        # Get user's card if exists
        user_card = None
        if user_id:
            user_card = await Database.get_user_card_in_game(user_id, game_id)
        
        # Get all called numbers
        called_numbers = await Database.get_drawn_numbers(game_id)
        
        # ========== FIXED: Get BOTH real and fake player counts ==========
        real_players = await Database.count_game_players(game_id)
        
        # Get fake players count from game_manager
        fake_players = 0
        if hasattr(game_manager, 'fake_user_manager'):
            fake_players = len(game_manager.fake_user_manager.game_fake_cards.get(game_id, {}))
        
        total_players = real_players + fake_players
        
        # ========== FIXED: Calculate correct prize pool ==========
        correct_prize_pool = total_players * 8
        
        # Get winners from game_manager
        winners = []
        winners_count = 0
        max_winners = 2
        
        if hasattr(game_manager, 'get_winners'):
            winners = await game_manager.get_winners(game_id)
            winners_count = await game_manager.get_winners_count(game_id)
            max_winners = getattr(game_manager, 'max_winners', 2)
        
        # Calculate countdown
        countdown = 0
        if game.get('current_phase') == 'card_purchase':
            purchase_end = game.get('purchase_end_time')
            if purchase_end:
                if isinstance(purchase_end, str):
                    try:
                        purchase_end = datetime.fromisoformat(purchase_end.replace('Z', '+00:00'))
                    except:
                        purchase_end = datetime.fromisoformat(purchase_end)
                if purchase_end > datetime.now():
                    countdown = (purchase_end - datetime.now()).total_seconds()
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
        
        # Format user card data
        user_card_data = None
        if user_card:
            # Parse card numbers
            card_numbers = []
            if user_card.get('card_numbers'):
                card_numbers_data = user_card['card_numbers']
                if isinstance(card_numbers_data, str):
                    try:
                        card_numbers = json.loads(card_numbers_data)
                    except:
                        card_numbers = []
                elif isinstance(card_numbers_data, list):
                    card_numbers = card_numbers_data
            
            user_card_data = {
                'card_id': user_card.get('id'),
                'card_index': user_card.get('card_index'),
                'card_numbers': card_numbers,
                'game_id': user_card.get('game_id'),
                'user_id': user_card.get('user_id')
            }
        
        # Format winners with payouts
        formatted_winners = []
        if winners and hasattr(game_manager, 'calculate_winner_payouts'):
            payouts = await game_manager.calculate_winner_payouts(game_id, correct_prize_pool)
            
            for i, winner in enumerate(winners):
                formatted_winner = {
                    'user_id': winner.get('user_id'),
                    'username': winner.get('username', f"User_{winner.get('user_id')}"),
                    'full_name': winner.get('full_name', ''),
                    'pattern_type': winner.get('pattern_type', 'unknown'),
                    'winning_pattern': winner.get('winning_pattern', []),
                    'card_index': winner.get('card_index'),
                    'prize_amount': payouts[i] if i < len(payouts) else 0,
                    'is_fake': winner.get('is_fake', False),
                    'timestamp': winner.get('timestamp', datetime.now().isoformat())
                }
                formatted_winners.append(formatted_winner)
        
        logger.info(f"📊 Complete state - Game {game_id}: Real: {real_players}, Fake: {fake_players}, Total: {total_players}, Prize: {correct_prize_pool}")
        
        # Prepare complete response
        response_data = {
            'success': True,
            'game_id': game_id,
            'round_number': game.get('round_number', 1),
            'game_phase': game.get('current_phase', 'card_purchase'),
            'game_status': game.get('status', 'card_purchase'),
            'countdown_remaining': max(0, int(countdown)),
            'prize_pool': correct_prize_pool,  # FIXED: Use correct prize pool
            'called_numbers': called_numbers,
            'real_players': real_players,
            'fake_players': fake_players,
            'total_players': total_players,  # FIXED: Show total players
            'user_has_card': user_card is not None,
            'user_card': user_card_data,
            'winners': formatted_winners,
            'winners_count': winners_count,
            'max_winners': max_winners,
            'min_fake_players': getattr(game_manager, 'min_fake_players', 10),
            'max_fake_players': getattr(game_manager, 'max_fake_players', 40),
            'fake_users_enabled': getattr(game_manager, 'fake_users_enabled', True),
            'timestamp': datetime.now().isoformat()
        }
        
        logger.info(f"✅ Complete state sent for game {game_id}, user {user_id}")
        return web.json_response(
            convert_to_json_serializable(response_data),
            dumps=lambda obj: json.dumps(obj, cls=CustomJSONEncoder)
        )
        
    except Exception as e:
        logger.error(f"❌ Error in complete game state: {e}", exc_info=True)
        return web.json_response({
            'success': False,
            'message': str(e)
        }, status=500)


async def calculate_server_countdown(game: dict) -> int:
    """Calculate countdown based on game timestamps - FIXED"""
    try:
        from utils.game_manager import game_manager
        
        game_id = game.get('game_id')
        if not game_id:
            return 30  # Default
        
        # FIX: Use game_manager's get_game_status for consistent countdown
        game_status = await game_manager.get_game_status(game_id)
        if game_status.get('success'):
            return game_status.get('countdown_remaining', 30)
        
        # Fallback to old logic if game_manager fails
        status = game.get('status', 'unknown')
        
        if status == 'card_purchase':
            # Check purchase_end_time
            purchase_end = game.get('purchase_end_time')
            if purchase_end:
                if isinstance(purchase_end, str):
                    try:
                        from dateutil.parser import parse
                        purchase_end = parse(purchase_end)
                    except:
                        return 30
                    
                    now = datetime.now()
                    remaining = (purchase_end - now).total_seconds()
                    return max(0, int(remaining))
            
            # Fallback to countdown_remaining
            countdown = game.get('countdown_remaining')
            if countdown is not None:
                return max(0, countdown)
            
            return 30  # Default
        
        elif status == 'winner_display':
            # Winner display lasts 5 seconds
            winner_display_start = game.get('last_phase_change') or game.get('completed_at')
            if winner_display_start:
                if isinstance(winner_display_start, str):
                    try:
                        from dateutil.parser import parse
                        winner_display_start = parse(winner_display_start)
                    except:
                        return 5
                    
                    now = datetime.now()
                    elapsed = (now - winner_display_start).total_seconds()
                    return max(0, 5 - int(elapsed))
            
            return 5  # Default
        
        elif status == 'active':
            # For active games, no countdown needed
            return 0
        
        else:
            return 30
            
    except Exception as e:
        logger.error(f"Error calculating countdown: {e}")
        return 30  # Default


# ==================== REAL BALANCE API ====================
@routes.get('/api/user/balance/{user_id}')
async def get_user_balance(request):
    """Get user balance"""
    try:
        user_id_str = request.match_info['user_id']
        
        from database.db import Database
        
        user_id = parse_user_id(user_id_str)
        
        # Get or create user
        user = await Database.get_user(user_id)
        
        if not user:
            await Database.create_user(
                user_id=user_id,
                username=f"User_{user_id}",
                full_name=f"User {user_id}"
            )
            user = await Database.get_user(user_id)
        
        if user:
            # FIX: Use the correct balance from database (10.00 for new users)
            balance = float(user.get('balance', 10.00))
            
            return web.json_response({
                'success': True,
                'balance': balance,
                'currency': 'birr',
                'user_id': user_id,
                'username': user.get('username', f'User {user_id}')
            }, dumps=lambda obj: json.dumps(obj, cls=CustomJSONEncoder))
        else:
            return web.json_response({
                'success': False,
                'message': 'User not found',
                'balance': 10.00,  # FIX: Default to 10.00, not 1000.00
                'currency': 'birr'
            })
                
    except Exception as e:
        logger.error(f"Error getting balance: {e}")
        import traceback
        traceback.print_exc()
        
        return web.json_response({
            'success': True,
            'balance': 10.00,  # FIX: Default to 10.00 for testing
            'currency': 'birr',
            'user_id': 0,
            'username': 'Test User',
            'message': 'Using default balance for testing'
        })


# ==================== FIXED GAME API ENDPOINTS ====================
@routes.get('/api/game/active')
async def get_active_game(request):
    """Get active game - FIXED: Shows correct total players and prize pool"""
    try:
        from utils.game_manager import game_manager
        
        # Get active game from game_manager
        active_game = await game_manager.get_active_round_game()
        
        if not active_game:
            # No active game, create one via game_manager
            result = await game_manager.start_new_round_game()
            if not result.get('success'):
                return web.json_response({
                    'success': False,
                    'message': 'No active game found and failed to create new one',
                    'game_type': 'round_based'
                }, status=404)
            
            # Get the newly created game
            active_game = await game_manager.get_active_round_game()
            if not active_game:
                return web.json_response({
                    'success': False,
                    'message': 'Failed to get newly created game'
                }, status=404)
        
        game_id = active_game.get('game_id')
        
        from database.db import Database
        from utils.game_manager import game_manager
        
        numbers_called = await Database.get_drawn_numbers(game_id) or []
        
        # ========== FIXED: Get BOTH real and fake player counts ==========
        real_players = await Database.count_game_players(game_id)
        
        # Get fake players count from game_manager
        fake_players = 0
        if hasattr(game_manager, 'fake_user_manager'):
            fake_players = len(game_manager.fake_user_manager.game_fake_cards.get(game_id, {}))
        
        total_players = real_players + fake_players
        sold_cards = await Database.count_sold_cards(game_id)
        
        # ========== FIXED: Calculate correct prize pool based on ALL players ==========
        # Prize pool = total players × 8 birr (80% of 10 birr card price)
        correct_prize_pool = total_players * 8
        
        # Get game status via game_manager for consistent countdown
        game_status = await game_manager.get_game_status(game_id)
        
        # Get countdown
        if game_status.get('success'):
            countdown = game_status.get('countdown_remaining', 30)
        else:
            countdown = await calculate_server_countdown(active_game)
        
        # FIX: Handle created_at properly
        created_at = active_game.get('created_at')
        if created_at:
            if isinstance(created_at, str):
                created_at_str = created_at
            elif hasattr(created_at, 'isoformat'):
                created_at_str = created_at.isoformat()
            else:
                created_at_str = None
        else:
            created_at_str = None
            
        # Handle started_at similarly
        started_at = active_game.get('started_at')
        if started_at:
            if isinstance(started_at, str):
                started_at_str = started_at
            elif hasattr(started_at, 'isoformat'):
                started_at_str = started_at.isoformat()
            else:
                started_at_str = None
        else:
            started_at_str = None
        
        logger.info(f"📊 Game {game_id} stats: Real: {real_players}, Fake: {fake_players}, Total: {total_players}, Prize: {correct_prize_pool}")
        
        response_data = {
            'success': True,
            'game_id': game_id,
            'status': active_game.get('status', 'unknown'),
            'game_type': active_game.get('game_type', 'round_based'),
            'card_price': float(active_game.get('card_price', 10.0)),
            'prize_pool': correct_prize_pool,  # FIXED: Use correct prize pool
            'total_players': total_players,  # FIXED: Show total players (real + fake)
            'real_players': real_players,  # ADDED: Show real players separately
            'fake_players': fake_players,  # ADDED: Show fake players separately
            'total_cards_sold': sold_cards,
            'numbers_called': numbers_called,
            'current_number': active_game.get('current_number'),
            'round_number': active_game.get('round_number', 1),
            'countdown_remaining': countdown,
            'has_winner': active_game.get('status') == 'winner_display',
            'created_at': created_at_str,
            'started_at': started_at_str,
            'can_buy': active_game.get('status') == 'card_purchase',
            'phase': active_game.get('current_phase', 'card_purchase'),
            'message': f'Game is {active_game.get("status", "unknown")}'
        }
        
        return web.json_response(
            convert_to_json_serializable(response_data), 
            dumps=lambda obj: json.dumps(obj, cls=CustomJSONEncoder)
        )
        
    except Exception as e:
        logger.error(f"Error getting active game: {e}", exc_info=True)
        return web.json_response({
            'success': False,
            'message': f'Error getting active game: {str(e)}'
        }, status=500)
        

# ==================== FIXED USER GAME STATE ENDPOINT ====================
@routes.get('/api/game/{game_id}/user-state/{user_id}')
async def get_user_game_state(request):
    """Get user's state in game - FIXED: Shows correct total players and prize pool"""
    try:
        game_id = request.match_info['game_id']
        user_id_str = request.match_info['user_id']
        user_id = parse_user_id(user_id_str)
        
        from database.db import Database
        from utils.game_manager import game_manager
        
        # Get user balance
        user_data = await Database.get_user_with_balance(user_id)
        if not user_data:
            await Database.create_user(
                user_id=user_id,
                username=f"User_{user_id}",
                full_name=f"User {user_id}"
            )
            user_data = await Database.get_user_with_balance(user_id)
        
        # FIX: Use correct balance (10.00 for new users)
        balance = float(user_data.get('balance', 10.00)) if user_data else 10.00
        
        # Get user card
        user_card = await Database.get_user_card_in_game(user_id, game_id)
        
        # Get game status via game_manager
        game_status = await game_manager.get_game_status(game_id)
        
        if not game_status.get('success'):
            return web.json_response({
                'success': False,
                'message': game_status.get('message', 'Game not found')
            }, status=404)
        
        # ========== FIXED: Get BOTH real and fake player counts ==========
        real_players = await Database.count_game_players(game_id)
        
        # Get fake players count from game_manager
        fake_players = 0
        if hasattr(game_manager, 'fake_user_manager'):
            fake_players = len(game_manager.fake_user_manager.game_fake_cards.get(game_id, {}))
        
        total_players = real_players + fake_players
        
        # ========== FIXED: Calculate correct prize pool ==========
        correct_prize_pool = total_players * 8  # 80% of 10 birr card price
        
        # Get called numbers
        numbers_called = await Database.get_drawn_numbers(game_id)
        
        # Build response
        response_data = {
            'success': True,
            'has_card': user_card is not None,
            'game_status': game_status.get('status', 'unknown'),
            'game_type': 'round_based',
            'phase': game_status.get('phase', 'unknown'),
            'balance': balance,
            'current_number': None,
            'numbers_called': numbers_called,
            'prize_pool': correct_prize_pool,  # FIXED: Use correct prize pool
            'total_players': total_players,  # FIXED: Show total players
            'real_players': real_players,  # ADDED: Show real players
            'fake_players': fake_players,  # ADDED: Show fake players
            'current_round': game_status.get('round_number', 1),
            'countdown_remaining': game_status.get('countdown_remaining', 0),
            'has_winner': game_status.get('status') == 'winner_display',
            'card_price': 10.00
        }
        
        # Add user_card data if exists
        if user_card:
            response_data['user_card'] = {
                'card_id': user_card.get('id'),
                'card_index': user_card.get('card_index'),
                'card_data': user_card.get('card_data'),
                'game_id': user_card.get('game_id'),
                'user_id': user_card.get('user_id')
            }
        
        # Get active game for current_number
        active_game = await game_manager.get_active_round_game()
        if active_game and active_game.get('game_id') == game_id:
            response_data['current_number'] = active_game.get('current_number')
        
        response_data = convert_to_json_serializable(response_data)
        
        return web.json_response(response_data, dumps=lambda obj: json.dumps(obj, cls=CustomJSONEncoder))
            
    except Exception as e:
        logger.error(f"Error getting user game state: {e}", exc_info=True)
        return web.json_response({
            'success': False,
            'message': f'Error getting user game state: {str(e)}'
        }, status=500)


# ==================== CARD PURCHASE API ====================
@routes.post('/api/game/{game_id}/toggle-card')
async def toggle_card_purchase(request):
    """Toggle card purchase/refund"""
    try:
        game_id = request.match_info['game_id']
        data = await request.json()
        
        user_id_str = data.get('user_id')
        card_index = data.get('card_index')
        action = data.get('action', 'buy')
        
        if not user_id_str or not card_index:
            return web.json_response({
                'success': False, 
                'message': 'Missing parameters'
            })
        
        user_id = parse_user_id(user_id_str)
        
        from utils.game_manager import game_manager
        
        result = await game_manager.toggle_card_purchase(
            game_id, 
            int(user_id), 
            int(card_index), 
            action
        )
        
        # Broadcast update if successful
        if result.get('success'):
            await websocket_server.broadcast_with_retry({
                'type': 'card_purchased',
                'game_id': game_id,
                'user_id': user_id,
                'card_index': card_index,
                'prize_pool': result.get('prize_pool', 0),
                'timestamp': datetime.now().isoformat()
            })
            
            # Also broadcast player count update
            from database.db import Database
            real_players = await Database.count_game_players(game_id)
            fake_players = len(game_manager.fake_user_manager.game_fake_cards.get(game_id, {})) if hasattr(game_manager, 'fake_user_manager') else 0
            await websocket_server.broadcast_player_count(game_id, real_players, fake_players)
        
        return web.json_response(result, dumps=lambda obj: json.dumps(obj, cls=CustomJSONEncoder))
        
    except Exception as e:
        logger.error(f"Error in toggle_card_purchase: {e}", exc_info=True)
        return web.json_response({
            'success': False, 
            'message': 'Server error'
        }, status=500)


# Add this to web_server.py - replace the existing get_sold_cards endpoint

@routes.get('/api/game/{game_id}/sold-cards')
async def get_sold_cards(request):
    """Get all sold cards for a game"""
    try:
        game_id = request.match_info['game_id']
        
        from database.db import Database
        
        # DEBUG: Check if game exists
        game = await Database.get_game(game_id)
        if not game:
            logger.warning(f"Game {game_id} not found for sold-cards request")
            return web.json_response({
                'success': False,
                'message': 'Game not found'
            }, status=404)
        
        # Get all active cards for this game
        cards = await Database.get_game_cards(game_id)
        
        # Extract card indices
        sold_cards = []
        for card in cards:
            card_index = card.get('card_index')
            if card_index:
                sold_cards.append(card_index)
        
        # DEBUG: Log what we found
        logger.info(f"📊 Game {game_id} sold cards: Found {len(cards)} active cards, {len(sold_cards)} indices")
        
        # Log breakdown of real vs fake
        real_cards = sum(1 for card in cards if not card.get('is_fake', 0))
        fake_cards = sum(1 for card in cards if card.get('is_fake', 1))
        
        logger.info(f"   Real cards: {real_cards}, Fake cards: {fake_cards}")
        
        # If no cards found, check if game has any players at all
        if len(cards) == 0:
            # Check if there are any records at all (even inactive)
            with Database.get_cursor() as cursor:
                cursor.execute("""
                    SELECT COUNT(*) as count, 
                           SUM(CASE WHEN is_fake = 1 THEN 1 ELSE 0 END) as fake_count
                    FROM player_cards 
                    WHERE game_id = ?
                """, (game_id,))
                row = cursor.fetchone()
                if row:
                    total = row[0] or 0
                    fake_total = row[1] or 0
                    real_total = total - fake_total
                    logger.info(f"   TOTAL records (including inactive): {total} (Real: {real_total}, Fake: {fake_total})")
        
        return web.json_response({
            'success': True,
            'sold_cards': sold_cards,
            'total_cards': len(cards),
            'game_id': game_id,
            'game_status': game.get('status', 'unknown')
        }, dumps=lambda obj: json.dumps(obj, cls=CustomJSONEncoder))
                
    except Exception as e:
        logger.error(f"Error getting sold cards: {e}")
        return web.json_response({
            'success': False,
            'message': f'Failed to get sold cards: {str(e)}'
        }, status=500)


# ==================== LIGHTNING-FAST BINGO CLAIM API ====================
@routes.post('/api/game/{game_id}/claim-bingo')
async def claim_bingo_lightning_fast(request):
    """Player claims bingo - LIGHTNING FAST VERIFICATION with 4 corners priority"""
    try:
        game_id = request.match_info['game_id']
        data = await request.json()
        
        user_id_str = data.get('user_id')
        if not user_id_str:
            return web.json_response({
                'success': False,
                'message': 'user_id is required'
            }, status=400)
        
        user_id = parse_user_id(user_id_str)
        
        from database.db import Database
        from utils.game_manager import game_manager
        
        logger.info(f"🚨 HTTP BINGO CLAIM from user {user_id} in game {game_id}")
        
        # Use game_manager's immediate bingo claim handler for 4 corners priority
        winner_data = await game_manager.handle_immediate_bingo_claim(game_id, user_id)
        
        if winner_data:
            # Get full card data for broadcast
            user_card = await Database.get_user_card_in_game(user_id, game_id)
            card_numbers = []
            if user_card and user_card.get('card_numbers'):
                card_data = user_card['card_numbers']
                if isinstance(card_data, str):
                    try:
                        card_numbers = json.loads(card_data)
                    except:
                        card_numbers = []
                elif isinstance(card_data, list):
                    card_numbers = card_data
            
            # Add card numbers to winner data for broadcast
            winner_data['card_numbers'] = card_numbers
            
            # Broadcast winner display to all clients
            await websocket_server.broadcast_winner_display(game_id, winner_data)
            
            return web.json_response({
                'success': True,
                'message': 'BINGO verified! You won!',
                'prize_amount': winner_data.get('prize_amount', 0),
                'pattern_type': winner_data.get('pattern_type', 'unknown'),
                'winning_pattern': winner_data.get('winning_pattern', []),
                'verification_time_ms': winner_data.get('verification_time_ms', 0),
                'game_type': 'round_based',
                'action': 'game_stopped'
            }, dumps=lambda obj: json.dumps(obj, cls=CustomJSONEncoder))
        else:
            # Check if game is still active
            game = await Database.get_game(game_id)
            if game and game.get('status') == 'active':
                # Game is still active, claim was invalid
                return web.json_response({
                    'success': False,
                    'message': 'No valid bingo pattern found',
                    'game_type': 'round_based',
                    'game_active': True
                }, dumps=lambda obj: json.dumps(obj, cls=CustomJSONEncoder))
            else:
                # Game already has a winner or not active
                return web.json_response({
                    'success': False,
                    'message': 'Game already has a winner or not active',
                    'game_type': 'round_based',
                    'game_active': False
                }, dumps=lambda obj: json.dumps(obj, cls=CustomJSONEncoder))
            
    except Exception as e:
        logger.error(f"Error claiming bingo: {e}", exc_info=True)
        return web.json_response({
            'success': False,
            'message': f'Error claiming bingo: {str(e)}'
        }, status=500)


# ==================== DEBUG BINGO VERIFICATION ENDPOINT ====================
@routes.get('/api/debug/verify-bingo/{game_id}/{user_id}')
async def debug_verify_bingo(request):
    """Debug endpoint to test bingo verification"""
    try:
        game_id = request.match_info['game_id']
        user_id_str = request.match_info['user_id']
        user_id = parse_user_id(user_id_str)
        
        from database.db import Database
        from utils.game_manager import game_manager
        
        # Get user card
        user_card = await Database.get_user_card_in_game(user_id, game_id)
        if not user_card:
            return web.json_response({
                'success': False,
                'message': 'No card found'
            })
        
        # Get called numbers
        called_numbers = await Database.get_drawn_numbers(game_id)
        
        # Test fast verification
        start_time = time.time()
        has_bingo, winning_pattern, pattern_type = await game_manager._fast_verify_bingo_with_pattern(user_card, called_numbers)
        verification_time = time.time() - start_time
        
        # Get card numbers
        card_numbers = []
        if user_card.get('card_numbers'):
            card_numbers_data = user_card['card_numbers']
            if isinstance(card_numbers_data, str):
                try:
                    card_numbers = json.loads(card_numbers_data)
                except:
                    pass
            elif isinstance(card_numbers_data, list):
                card_numbers = card_numbers_data
        
        # Get corner numbers
        corner_numbers = []
        if len(card_numbers) >= 25:
            corner_indices = [0, 4, 20, 24]
            corner_numbers = [card_numbers[i] for i in corner_indices]
        
        # Check if corners are in called numbers
        corners_called = all(corner in called_numbers for corner in corner_numbers if corner != 0)
        
        return web.json_response({
            'success': True,
            'has_bingo': has_bingo,
            'pattern_type': pattern_type,
            'winning_pattern': winning_pattern,
            'verification_time_ms': verification_time * 1000,
            'card_numbers': card_numbers,
            'corner_numbers': corner_numbers,
            'corners_called': corners_called,
            'corner_indices': [0, 4, 20, 24],
            'called_numbers_count': len(called_numbers),
            'called_numbers': called_numbers[:20],  # First 20 for debugging
            'message': f"Verification took {verification_time*1000:.1f}ms - 4 corners checked first"
        })
        
    except Exception as e:
        logger.error(f"Debug error: {e}")
        return web.json_response({
            'success': False,
            'message': str(e)
        }, status=500)


# ==================== FORCE BINGO VERIFICATION ENDPOINT ====================
@routes.post('/api/force-verify-bingo/{game_id}/{user_id}')
async def force_verify_bingo(request):
    """Force bingo verification (admin/debug tool)"""
    try:
        game_id = request.match_info['game_id']
        user_id_str = request.match_info['user_id']
        user_id = parse_user_id(user_id_str)
        
        from database.db import Database
        from utils.game_manager import game_manager
        
        # Get game
        game = await Database.get_game(game_id)
        if not game:
            return web.json_response({
                'success': False,
                'message': 'Game not found'
            })
        
        # Get user card
        user_card = await Database.get_user_card_in_game(user_id, game_id)
        if not user_card:
            return web.json_response({
                'success': False,
                'message': 'No card found'
            })
        
        # Get called numbers
        called_numbers = await Database.get_drawn_numbers(game_id)
        
        # Force verification
        has_bingo, winning_pattern, pattern_type = await game_manager._fast_verify_bingo_with_pattern(user_card, called_numbers)
        
        if has_bingo:
            # Process winner
            winner_data = await game_manager.process_winner(game_id, user_id)
            
            if winner_data:
                # Get full card data for broadcast
                card_numbers = []
                if user_card.get('card_numbers'):
                    card_data = user_card['card_numbers']
                    if isinstance(card_data, str):
                        try:
                            card_numbers = json.loads(card_data)
                        except:
                            card_numbers = []
                    elif isinstance(card_data, list):
                        card_numbers = card_data
                
                winner_data['card_numbers'] = card_numbers
                winner_data['winning_pattern'] = winning_pattern
                winner_data['pattern_type'] = pattern_type
                
                # Broadcast winner display
                await websocket_server.broadcast_winner_display(game_id, winner_data)
                
                return web.json_response({
                    'success': True,
                    'message': 'BINGO verified and winner processed!',
                    'winner_data': winner_data
                })
            else:
                return web.json_response({
                    'success': False,
                    'message': 'Failed to process winner',
                    'verification': {
                        'has_bingo': True,
                        'pattern_type': pattern_type,
                        'winning_pattern': winning_pattern
                    }
                })
        else:
            return web.json_response({
                'success': False,
                'message': 'No bingo found',
                'verification': {
                    'has_bingo': False,
                    'pattern_type': pattern_type,
                    'winning_pattern': winning_pattern
                }
            })
            
    except Exception as e:
        logger.error(f"Error in force verify bingo: {e}")
        return web.json_response({
            'success': False,
            'message': str(e)
        }, status=500)


# ==================== HEALTH CHECK ====================
@routes.get('/health')
async def health_check(request):
    """Health check endpoint"""
    try:
        from utils.game_manager import game_manager
        system_status = await game_manager.get_system_status() if hasattr(game_manager, 'get_system_status') else {}
    except:
        system_status = {}
    
    return web.json_response({
        'status': 'healthy',
        'service': 'habesha-bingo-validation-server',
        'timestamp': datetime.now().isoformat(),
        'architecture': 'server-coordinated',
        'server_controls': ['number_calling', 'phase_transitions', 'countdown'],
        'frontend_responsive': ['ui_updates', 'bingo_detection', 'card_purchase'],
        'bingo_verification': 'lightning_fast_with_4corners_priority',
        'sync_endpoint': '/api/game/{game_id}/sync',
        'websocket_connections': len(websocket_server.connections),
        'authenticated_users': len(websocket_server.user_connections),
        'game_manager_status': system_status,
        'commission_table': 'commission_records'
    }, dumps=lambda obj: json.dumps(obj, cls=CustomJSONEncoder))


# ==================== SYSTEM STATUS ENDPOINT ====================
@routes.get('/api/system/status')
async def system_status(request):
    """Get system status"""
    try:
        from utils.game_manager import game_manager
        system_status = await game_manager.get_system_status() if hasattr(game_manager, 'get_system_status') else {}
        
        return web.json_response({
            'success': True,
            'system_status': system_status,
            'websocket': {
                'connections': len(websocket_server.connections),
                'authenticated_users': len(websocket_server.user_connections)
            },
            'timestamp': datetime.now().isoformat()
        }, dumps=lambda obj: json.dumps(obj, cls=CustomJSONEncoder))
    except Exception as e:
        logger.error(f"Error getting system status: {e}")
        return web.json_response({
            'success': False,
            'message': str(e)
        }, status=500)


# ==================== WEBSOCKET HANDLER ====================
@routes.get('/ws')
async def websocket_handler(request):
    """WebSocket handler for validation messages"""
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    
    await websocket_server.handle_connection(ws)
    
    return ws


# ==================== HTML PAGES ====================
@routes.get('/')
async def home(request):
    """Home page"""
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>🎮 Habesha Bingo Server</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                margin: 40px;
                background-color: #f5f5f5;
            }
            .container {
                max-width: 800px;
                margin: 0 auto;
                background: white;
                padding: 30px;
                border-radius: 10px;
                box-shadow: 0 0 20px rgba(0,0,0,0.1);
            }
            h1 {
                color: #2c3e50;
                border-bottom: 3px solid #3498db;
                padding-bottom: 10px;
            }
            .link-list {
                list-style: none;
                padding: 0;
            }
            .link-list li {
                margin: 15px 0;
                padding: 15px;
                background: #f8f9fa;
                border-radius: 5px;
                border-left: 4px solid #3498db;
            }
            .link-list a {
                text-decoration: none;
                color: #2c3e50;
                font-weight: bold;
                display: block;
            }
            .link-list a:hover {
                color: #3498db;
            }
            .description {
                color: #666;
                font-size: 14px;
                margin-top: 5px;
            }
            .status {
                background: #d4edda;
                color: #155724;
                padding: 10px;
                border-radius: 5px;
                margin: 20px 0;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🎮 Habesha Bingo Server</h1>
            <div class="status">
                ✅ Server is running successfully! Ready to serve bingo games.
            </div>
            <p>Welcome to the Habesha Bingo Server-Coordinated Architecture. Choose an option below:</p>
            <ul class="link-list">
                <li>
                    <a href="/game.html" target="_blank">🎮 Game Interface</a>
                    <div class="description">Main bingo game interface for players</div>
                </li>
                <li>
                    <a href="/admin.html" target="_blank">👨‍💼 Admin Panel</a>
                    <div class="description">Administration panel for managing games, users, and payments</div>
                </li>
                <li>
                    <a href="/health" target="_blank">📊 Health Status</a>
                    <div class="description">Check server health and system status</div>
                </li>
                <li>
                    <a href="/api/system/status" target="_blank">⚙️ System Status</a>
                    <div class="description">Detailed system status and metrics</div>
                </li>
                <li>
                    <a href="/api/admin/stats" target="_blank">📈 Admin Statistics</a>
                    <div class="description">View game statistics and revenue reports</div>
                </li>
            </ul>
            <h3>API Endpoints:</h3>
            <ul class="link-list">
                <li><a href="/api/game/active" target="_blank">/api/game/active</a> - Get active game info</li>
                <li><a href="/api/user/balance/1" target="_blank">/api/user/balance/{user_id}</a> - Get user balance</li>
                <li><a href="/ws" target="_blank">/ws</a> - WebSocket connection</li>
            </ul>
        </div>
    </body>
    </html>
    """
    return web.Response(text=html_content, content_type='text/html')


@routes.get('/game.html')
async def game_html(request):
    """Serve the main game HTML page from external file"""
    try:
        # Get current directory
        current_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Try multiple possible locations for game.html
        possible_paths = [
            os.path.join(current_dir, 'game.html'),
            os.path.join(current_dir, 'templates', 'game.html'),
            os.path.join(current_dir, 'static', 'game.html'),
            os.path.join(current_dir, 'html', 'game.html'),
            'game.html',
            './game.html'
        ]
        
        html_content = None
        file_path_used = None
        
        for path in possible_paths:
            try:
                if os.path.exists(path):
                    with open(path, 'r', encoding='utf-8') as f:
                        html_content = f.read()
                    file_path_used = path
                    logger.info(f"Successfully served game.html from: {path}")
                    break
            except Exception as e:
                logger.debug(f"Failed to read {path}: {e}")
                continue
        
        if html_content is None:
            # If external file not found, use simplified embedded version
            logger.warning("game.html not found in any standard location, using embedded version")
            html_content = """
            No file found
            """
        
        return web.Response(
            text=html_content,
            content_type='text/html',
            headers={
                'Cache-Control': 'no-cache, no-store, must-revalidate',
                # 'Pragma': 'no-cache',
                'Expires': '0',
                'Access-Control-Allow-Origin': '*'
            }
        )
    except Exception as e:
        logger.error(f"Error serving game.html: {e}", exc_info=True)
        error_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Error - Habesha Bingo</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 40px; background-color: #f5f5f5; }}
                .container {{ max-width: 800px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 0 20px rgba(0,0,0,0.1); }}
                h1 {{ color: #e74c3c; }}
                .error {{ background: #f8d7da; color: #721c24; padding: 15px; border-radius: 5px; margin: 20px 0; border: 1px solid #f5c6cb; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>❌ Error Loading Game Page</h1>
                <div class="error">
                    Error: {str(e)}
                </div>
                <p>Please check the server logs for more details.</p>
                <p><a href="/">Return to Home Page</a></p>
            </div>
        </body>
        </html>
        """
        return web.Response(text=error_html, content_type='text/html', status=500)


@routes.get('/admin.html')
async def admin_html(request):
    """Serve the admin panel HTML page from external file"""
    try:
        # Get current directory
        current_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Try multiple possible locations for admin.html
        possible_paths = [
            os.path.join(current_dir, 'admin.html'),
            os.path.join(current_dir, 'templates', 'admin.html'),
            os.path.join(current_dir, 'static', 'admin.html'),
            os.path.join(current_dir, 'html', 'admin.html'),
            'admin.html',
            './admin.html'
        ]
        
        html_content = None
        file_path_used = None
        
        for path in possible_paths:
            try:
                if os.path.exists(path):
                    with open(path, 'r', encoding='utf-8') as f:
                        html_content = f.read()
                    file_path_used = path
                    logger.info(f"Successfully served admin.html from: {path}")
                    break
            except Exception as e:
                logger.debug(f"Failed to read {path}: {e}")
                continue
        
        if html_content is None:
            # If external file not found, use simplified embedded version
            logger.warning("admin.html not found in any standard location, using embedded version")
            html_content = """
            <!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>Habesha Bingo - Admin Panel</title>
                <style>
                    * {
                        margin: 0;
                        padding: 0;
                        box-sizing: border-box;
                    }
                    
                    body {
                        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                        background: #f5f7fa;
                        color: #333;
                    }
                    
                    .sidebar {
                        position: fixed;
                        left: 0;
                        top: 0;
                        bottom: 0;
                        width: 250px;
                        background: #2d3748;
                        color: white;
                        overflow-y: auto;
                    }
                    
                    .sidebar-header {
                        padding: 25px;
                        border-bottom: 1px solid #4a5568;
                    }
                    
                    .sidebar-header h2 {
                        font-size: 1.5rem;
                        color: #63b3ed;
                    }
                    
                    .sidebar-menu {
                        list-style: none;
                        padding: 20px 0;
                    }
                    
                    .sidebar-menu li {
                        margin: 5px 0;
                    }
                    
                    .sidebar-menu a {
                        display: block;
                        padding: 15px 25px;
                        color: #cbd5e0;
                        text-decoration: none;
                        transition: all 0.3s;
                    }
                    
                    .sidebar-menu a:hover,
                    .sidebar-menu a.active {
                        background: #4a5568;
                        color: white;
                        border-left: 4px solid #63b3ed;
                    }
                    
                    .sidebar-menu i {
                        margin-right: 10px;
                        width: 20px;
                        text-align: center;
                    }
                    
                    .main-content {
                        margin-left: 250px;
                        padding: 20px;
                    }
                    
                    .top-bar {
                        background: white;
                        padding: 20px;
                        border-radius: 10px;
                        margin-bottom: 25px;
                        box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                        display: flex;
                        justify-content: space-between;
                        align-items: center;
                    }
                    
                    .top-bar h1 {
                        color: #2d3748;
                        font-size: 1.8rem;
                    }
                    
                    .admin-info {
                        display: flex;
                        align-items: center;
                        gap: 15px;
                    }
                    
                    .admin-avatar {
                        width: 40px;
                        height: 40px;
                        background: #63b3ed;
                        border-radius: 50%;
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        color: white;
                        font-weight: bold;
                    }
                    
                    .stats-grid {
                        display: grid;
                        grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
                        gap: 25px;
                        margin-bottom: 25px;
                    }
                    
                    .stat-card {
                        background: white;
                        padding: 25px;
                        border-radius: 10px;
                        box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                        transition: transform 0.3s;
                    }
                    
                    .stat-card:hover {
                        transform: translateY(-5px);
                    }
                    
                    .stat-card-header {
                        display: flex;
                        justify-content: space-between;
                        align-items: center;
                        margin-bottom: 20px;
                    }
                    
                    .stat-card-icon {
                        width: 50px;
                        height: 50px;
                        border-radius: 10px;
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        font-size: 1.5rem;
                    }
                    
                    .stat-card-icon.games {
                        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                        color: white;
                    }
                    
                    .stat-card-icon.users {
                        background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
                        color: white;
                    }
                    
                    .stat-card-icon.revenue {
                        background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
                        color: white;
                    }
                    
                    .stat-card-icon.balance {
                        background: linear-gradient(135deg, #43e97b 0%, #38f9d7 100%);
                        color: white;
                    }
                    
                    .stat-card-value {
                        font-size: 2.5rem;
                        font-weight: bold;
                        color: #2d3748;
                    }
                    
                    .stat-card-label {
                        color: #718096;
                        font-size: 1.1rem;
                    }
                    
                    .dashboard-section {
                        background: white;
                        padding: 30px;
                        border-radius: 10px;
                        box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                        margin-bottom: 25px;
                    }
                    
                    .section-header {
                        display: flex;
                        justify-content: space-between;
                        align-items: center;
                        margin-bottom: 25px;
                        padding-bottom: 15px;
                        border-bottom: 2px solid #e2e8f0;
                    }
                    
                    .section-header h3 {
                        color: #2d3748;
                        font-size: 1.5rem;
                    }
                    
                    table {
                        width: 100%;
                        border-collapse: collapse;
                    }
                    
                    thead {
                        background: #f7fafc;
                    }
                    
                    th {
                        padding: 15px;
                        text-align: left;
                        color: #4a5568;
                        font-weight: 600;
                        border-bottom: 2px solid #e2e8f0;
                    }
                    
                    td {
                        padding: 15px;
                        border-bottom: 1px solid #e2e8f0;
                    }
                    
                    tr:hover {
                        background: #f7fafc;
                    }
                    
                    .status-badge {
                        padding: 5px 15px;
                        border-radius: 20px;
                        font-size: 0.9rem;
                        font-weight: 600;
                    }
                    
                    .status-active {
                        background: #c6f6d5;
                        color: #22543d;
                    }
                    
                    .status-pending {
                        background: #fed7d7;
                        color: #742a2a;
                    }
                    
                    .status-completed {
                        background: #bee3f8;
                        color: #2a4365;
                    }
                    
                    .btn {
                        padding: 10px 20px;
                        border: none;
                        border-radius: 6px;
                        font-weight: 600;
                        cursor: pointer;
                        transition: all 0.3s;
                    }
                    
                    .btn-sm {
                        padding: 5px 15px;
                        font-size: 0.9rem;
                    }
                    
                    .btn-primary {
                        background: #4299e1;
                        color: white;
                    }
                    
                    .btn-primary:hover {
                        background: #3182ce;
                    }
                    
                    .btn-success {
                        background: #48bb78;
                        color: white;
                    }
                    
                    .btn-success:hover {
                        background: #38a169;
                    }
                    
                    .btn-danger {
                        background: #f56565;
                        color: white;
                    }
                    
                    .btn-danger:hover {
                        background: #e53e3e;
                    }
                    
                    .btn-warning {
                        background: #ed8936;
                        color: white;
                    }
                    
                    .btn-warning:hover {
                        background: #dd6b20;
                    }
                    
                    .modal {
                        display: none;
                        position: fixed;
                        top: 0;
                        left: 0;
                        right: 0;
                        bottom: 0;
                        background: rgba(0,0,0,0.5);
                        z-index: 1000;
                        align-items: center;
                        justify-content: center;
                    }
                    
                    .modal-content {
                        background: white;
                        border-radius: 10px;
                        width: 90%;
                        max-width: 500px;
                        max-height: 90vh;
                        overflow-y: auto;
                    }
                    
                    .modal-header {
                        padding: 25px;
                        border-bottom: 1px solid #e2e8f0;
                        display: flex;
                        justify-content: space-between;
                        align-items: center;
                    }
                    
                    .modal-body {
                        padding: 25px;
                    }
                    
                    .modal-footer {
                        padding: 25px;
                        border-top: 1px solid #e2e8f0;
                        display: flex;
                        justify-content: flex-end;
                        gap: 15px;
                    }
                    
                    .form-group {
                        margin-bottom: 20px;
                    }
                    
                    .form-group label {
                        display: block;
                        margin-bottom: 8px;
                        color: #4a5568;
                        font-weight: 600;
                    }
                    
                    .form-control {
                        width: 100%;
                        padding: 12px;
                        border: 1px solid #e2e8f0;
                        border-radius: 6px;
                        font-size: 1rem;
                        transition: border-color 0.3s;
                    }
                    
                    .form-control:focus {
                        outline: none;
                        border-color: #4299e1;
                    }
                    
                    .notifications {
                        position: fixed;
                        top: 20px;
                        right: 20px;
                        width: 350px;
                        z-index: 2000;
                    }
                    
                    .notification {
                        background: white;
                        border-radius: 10px;
                        padding: 20px;
                        margin-bottom: 15px;
                        box-shadow: 0 10px 30px rgba(0,0,0,0.2);
                        border-left: 5px solid #4299e1;
                        animation: slideIn 0.3s ease;
                    }
                    
                    .notification.success {
                        border-left-color: #48bb78;
                    }
                    
                    .notification.error {
                        border-left-color: #f56565;
                    }
                    
                    .notification.warning {
                        border-left-color: #ed8936;
                    }
                    
                    @keyframes slideIn {
                        from {
                            transform: translateX(100%);
                            opacity: 0;
                        }
                        to {
                            transform: translateX(0);
                            opacity: 1;
                        }
                    }
                    
                    .loader {
                        border: 3px solid #f3f3f3;
                        border-top: 3px solid #4299e1;
                        border-radius: 50%;
                        width: 30px;
                        height: 30px;
                        animation: spin 1s linear infinite;
                        margin: 20px auto;
                    }
                    
                    @keyframes spin {
                        0% { transform: rotate(0deg); }
                        100% { transform: rotate(360deg); }
                    }
                    
                    .pagination {
                        display: flex;
                        justify-content: center;
                        gap: 10px;
                        margin-top: 25px;
                    }
                    
                    .page-link {
                        padding: 8px 15px;
                        background: #edf2f7;
                        border: none;
                        border-radius: 6px;
                        cursor: pointer;
                        transition: all 0.3s;
                    }
                    
                    .page-link:hover {
                        background: #e2e8f0;
                    }
                    
                    .page-link.active {
                        background: #4299e1;
                        color: white;
                    }
                    
                    .chart-container {
                        height: 300px;
                        margin-top: 20px;
                    }
                    
                    .tab-nav {
                        display: flex;
                        border-bottom: 2px solid #e2e8f0;
                        margin-bottom: 25px;
                    }
                    
                    .tab-link {
                        padding: 15px 25px;
                        background: none;
                        border: none;
                        color: #718096;
                        font-weight: 600;
                        cursor: pointer;
                        transition: all 0.3s;
                    }
                    
                    .tab-link:hover {
                        color: #4299e1;
                    }
                    
                    .tab-link.active {
                        color: #4299e1;
                        border-bottom: 3px solid #4299e1;
                        margin-bottom: -2px;
                    }
                    
                    .tab-content {
                        display: none;
                    }
                    
                    .tab-content.active {
                        display: block;
                    }
                    
                    .search-box {
                        position: relative;
                        margin-bottom: 25px;
                    }
                    
                    .search-box input {
                        width: 100%;
                        padding: 12px 45px 12px 15px;
                        border: 1px solid #e2e8f0;
                        border-radius: 6px;
                        font-size: 1rem;
                    }
                    
                    .search-box i {
                        position: absolute;
                        right: 15px;
                        top: 50%;
                        transform: translateY(-50%);
                        color: #a0aec0;
                    }
                    
                    @media (max-width: 768px) {
                        .sidebar {
                            width: 70px;
                        }
                        
                        .sidebar-header h2 {
                            display: none;
                        }
                        
                        .sidebar-menu a span {
                            display: none;
                        }
                        
                        .sidebar-menu a {
                            text-align: center;
                            padding: 15px;
                        }
                        
                        .sidebar-menu i {
                            margin-right: 0;
                            font-size: 1.2rem;
                        }
                        
                        .main-content {
                            margin-left: 70px;
                        }
                        
                        .top-bar h1 {
                            font-size: 1.5rem;
                        }
                    }
                </style>
                <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
            </head>
            <body>
                <div class="sidebar">
                    <div class="sidebar-header">
                        <h2><i class="fas fa-crown"></i> Admin Panel</h2>
                    </div>
                    <ul class="sidebar-menu">
                        <li><a href="#" class="active" onclick="showTab('dashboard')"><i class="fas fa-tachometer-alt"></i> <span>Dashboard</span></a></li>
                        <li><a href="#" onclick="showTab('games')"><i class="fas fa-gamepad"></i> <span>Games</span></a></li>
                        <li><a href="#" onclick="showTab('users')"><i class="fas fa-users"></i> <span>Users</span></a></li>
                        <li><a href="#" onclick="showTab('payments')"><i class="fas fa-credit-card"></i> <span>Payments</span></a></li>
                        <li><a href="#" onclick="showTab('withdrawals')"><i class="fas fa-money-bill-wave"></i> <span>Withdrawals</span></a></li>
                        <li><a href="#" onclick="showTab('transactions')"><i class="fas fa-exchange-alt"></i> <span>Transactions</span></a></li>
                        <li><a href="#" onclick="showTab('notifications')"><i class="fas fa-bell"></i> <span>Notifications</span></a></li>
                        <li><a href="#" onclick="showTab('system')"><i class="fas fa-cogs"></i> <span>System</span></a></li>
                    </ul>
                </div>
                
                <div class="main-content">
                    <div class="top-bar">
                        <h1 id="pageTitle">Admin Dashboard</h1>
                        <div class="admin-info">
                            <div class="admin-avatar">AD</div>
                            <div>
                                <div>Admin User</div>
                                <div style="font-size: 0.9rem; color: #718096;">Administrator</div>
                            </div>
                        </div>
                    </div>
                    
                    <!-- Dashboard Tab -->
                    <div id="dashboard" class="tab-content active">
                        <div class="stats-grid">
                            <div class="stat-card">
                                <div class="stat-card-header">
                                    <div>
                                        <div class="stat-card-label">Total Games</div>
                                        <div class="stat-card-value" id="totalGames">0</div>
                                    </div>
                                    <div class="stat-card-icon games"><i class="fas fa-gamepad"></i></div>
                                </div>
                                <div>Active: <span id="activeGames">0</span></div>
                            </div>
                            
                            <div class="stat-card">
                                <div class="stat-card-header">
                                    <div>
                                        <div class="stat-card-label">Total Users</div>
                                        <div class="stat-card-value" id="totalUsers">0</div>
                                    </div>
                                    <div class="stat-card-icon users"><i class="fas fa-users"></i></div>
                                </div>
                                <div>Online: <span id="onlineUsers">0</span></div>
                            </div>
                            
                            <div class="stat-card">
                                <div class="stat-card-header">
                                    <div>
                                        <div class="stat-card-label">Today's Revenue</div>
                                        <div class="stat-card-value" id="todayRevenue">0 birr</div>
                                    </div>
                                    <div class="stat-card-icon revenue"><i class="fas fa-chart-line"></i></div>
                                </div>
                                <div>Total: <span id="totalRevenue">0 birr</span></div>
                            </div>
                            
                            <div class="stat-card">
                                <div class="stat-card-header">
                                    <div>
                                        <div class="stat-card-label">Total Balance</div>
                                        <div class="stat-card-value" id="totalBalance">0 birr</div>
                                    </div>
                                    <div class="stat-card-icon balance"><i class="fas fa-wallet"></i></div>
                                </div>
                                <div>Commission: <span id="totalCommission">0 birr</span></div>
                            </div>
                        </div>
                        
                        <div class="dashboard-section">
                            <div class="section-header">
                                <h3>Recent Games</h3>
                                <button class="btn btn-primary" onclick="loadGames()"><i class="fas fa-sync"></i> Refresh</button>
                            </div>
                            <div id="recentGames">
                                <div class="loader"></div>
                            </div>
                        </div>
                        
                        <div class="dashboard-section">
                            <div class="section-header">
                                <h3>Active Game Controls</h3>
                                <div>
                                    <button class="btn btn-success" onclick="startCurrentGame()"><i class="fas fa-play"></i> Start Game</button>
                                    <button class="btn btn-danger" onclick="stopCurrentGame()"><i class="fas fa-stop"></i> Stop Game</button>
                                    <button class="btn btn-warning" onclick="openCallNumberModal()"><i class="fas fa-bullhorn"></i> Call Number</button>
                                </div>
                            </div>
                            <div id="activeGameInfo">
                                <p>Loading active game info...</p>
                            </div>
                        </div>
                    </div>
                    
                    <!-- Games Tab -->
                    <div id="games" class="tab-content">
                        <div class="dashboard-section">
                            <div class="section-header">
                                <h3>All Games</h3>
                                <div>
                                    <button class="btn btn-primary" onclick="loadGames()"><i class="fas fa-sync"></i> Refresh</button>
                                </div>
                            </div>
                            <div class="search-box">
                                <input type="text" id="gameSearch" placeholder="Search games..." onkeyup="searchGames()">
                                <i class="fas fa-search"></i>
                            </div>
                            <div id="gamesTable">
                                <div class="loader"></div>
                            </div>
                            <div class="pagination" id="gamesPagination"></div>
                        </div>
                    </div>
                    
                    <!-- Users Tab -->
                    <div id="users" class="tab-content">
                        <div class="dashboard-section">
                            <div class="section-header">
                                <h3>All Users</h3>
                                <div>
                                    <button class="btn btn-primary" onclick="loadUsers()"><i class="fas fa-sync"></i> Refresh</button>
                                    <button class="btn btn-success" onclick="openAddBalanceModal()"><i class="fas fa-plus"></i> Add Balance</button>
                                </div>
                            </div>
                            <div class="search-box">
                                <input type="text" id="userSearch" placeholder="Search users..." onkeyup="searchUsers()">
                                <i class="fas fa-search"></i>
                            </div>
                            <div id="usersTable">
                                <div class="loader"></div>
                            </div>
                            <div class="pagination" id="usersPagination"></div>
                        </div>
                    </div>
                    
                    <!-- Payments Tab -->
                    <div id="payments" class="tab-content">
                        <div class="tab-nav">
                            <button class="tab-link active" onclick="showPaymentTab('pending')">Pending</button>
                            <button class="tab-link" onclick="showPaymentTab('approved')">Approved</button>
                            <button class="tab-link" onclick="showPaymentTab('rejected')">Rejected</button>
                            <button class="tab-link" onclick="showPaymentTab('all')">All</button>
                        </div>
                        <div class="dashboard-section">
                            <div class="section-header">
                                <h3>Payment Requests</h3>
                                <button class="btn btn-primary" onclick="loadPayments()"><i class="fas fa-sync"></i> Refresh</button>
                            </div>
                            <div id="paymentsTable">
                                <div class="loader"></div>
                            </div>
                            <div class="pagination" id="paymentsPagination"></div>
                        </div>
                    </div>
                    
                    <!-- Withdrawals Tab -->
                    <div id="withdrawals" class="tab-content">
                        <div class="tab-nav">
                            <button class="tab-link active" onclick="showWithdrawalTab('pending')">Pending</button>
                            <button class="tab-link" onclick="showWithdrawalTab('approved')">Approved</button>
                            <button class="tab-link" onclick="showWithdrawalTab('rejected')">Rejected</button>
                            <button class="tab-link" onclick="showWithdrawalTab('all')">All</button>
                        </div>
                        <div class="dashboard-section">
                            <div class="section-header">
                                <h3>Withdrawal Requests</h3>
                                <button class="btn btn-primary" onclick="loadWithdrawals()"><i class="fas fa-sync"></i> Refresh</button>
                            </div>
                            <div id="withdrawalsTable">
                                <div class="loader"></div>
                            </div>
                            <div class="pagination" id="withdrawalsPagination"></div>
                        </div>
                    </div>
                    
                    <!-- Transactions Tab -->
                    <div id="transactions" class="tab-content">
                        <div class="dashboard-section">
                            <div class="section-header">
                                <h3>All Transactions</h3>
                                <div>
                                    <button class="btn btn-primary" onclick="loadTransactions()"><i class="fas fa-sync"></i> Refresh</button>
                                </div>
                            </div>
                            <div class="tab-nav">
                                <button class="tab-link" onclick="showTransactionTab('all')">All</button>
                                <button class="tab-link active" onclick="showTransactionTab('deposit')">Deposits</button>
                                <button class="tab-link" onclick="showTransactionTab('withdrawal')">Withdrawals</button>
                                <button class="tab-link" onclick="showTransactionTab('game')">Game</button>
                                <button class="tab-link" onclick="showTransactionTab('admin')">Admin</button>
                            </div>
                            <div class="search-box">
                                <input type="text" id="transactionSearch" placeholder="Search transactions..." onkeyup="searchTransactions()">
                                <i class="fas fa-search"></i>
                            </div>
                            <div id="transactionsTable">
                                <div class="loader"></div>
                            </div>
                            <div class="pagination" id="transactionsPagination"></div>
                        </div>
                    </div>
                    
                    <!-- Notifications Tab -->
                    <div id="notifications" class="tab-content">
                        <div class="dashboard-section">
                            <div class="section-header">
                                <h3>Send Notification</h3>
                            </div>
                            <div class="form-group">
                                <label>Title</label>
                                <input type="text" id="notificationTitle" class="form-control" placeholder="Enter notification title">
                            </div>
                            <div class="form-group">
                                <label>Message</label>
                                <textarea id="notificationMessage" class="form-control" rows="4" placeholder="Enter notification message"></textarea>
                            </div>
                            <div class="form-group">
                                <label>Target</label>
                                <select id="notificationTarget" class="form-control" onchange="toggleNotificationTarget()">
                                    <option value="all">All Users</option>
                                    <option value="active">Active Users Only</option>
                                    <option value="specific">Specific Users</option>
                                </select>
                            </div>
                            <div class="form-group" id="specificUsersGroup" style="display: none;">
                                <label>User IDs (comma-separated)</label>
                                <input type="text" id="specificUserIds" class="form-control" placeholder="e.g., 123,456,789">
                            </div>
                            <button class="btn btn-success" onclick="sendNotification()"><i class="fas fa-paper-plane"></i> Send Notification</button>
                        </div>
                    </div>
                    
                    <!-- System Tab -->
                    <div id="system" class="tab-content">
                        <div class="dashboard-section">
                            <div class="section-header">
                                <h3>System Status</h3>
                                <button class="btn btn-primary" onclick="loadSystemStatus()"><i class="fas fa-sync"></i> Refresh</button>
                            </div>
                            <div id="systemStatus">
                                <div class="loader"></div>
                            </div>
                        </div>
                        
                        <div class="dashboard-section">
                            <div class="section-header">
                                <h3>System Actions</h3>
                            </div>
                            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px;">
                                <button class="btn btn-warning" onclick="restartGameManager()"><i class="fas fa-redo"></i> Restart Game Manager</button>
                                <button class="btn btn-danger" onclick="clearCache()"><i class="fas fa-trash"></i> Clear Cache</button>
                                <button class="btn btn-primary" onclick="backupDatabase()"><i class="fas fa-database"></i> Backup Database</button>
                                <button class="btn btn-success" onclick="checkHealth()"><i class="fas fa-heartbeat"></i> Check Health</button>
                            </div>
                        </div>
                    </div>
                </div>
                
                <!-- Modals -->
                <div id="callNumberModal" class="modal">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h3>Call Number</h3>
                            <button onclick="closeModal('callNumberModal')" style="background: none; border: none; font-size: 1.5rem; cursor: pointer;">&times;</button>
                        </div>
                        <div class="modal-body">
                            <div class="form-group">
                                <label>Game ID</label>
                                <input type="text" id="callNumberGameId" class="form-control" readonly>
                            </div>
                            <div class="form-group">
                                <label>Number (1-75)</label>
                                <input type="number" id="callNumberInput" class="form-control" min="1" max="75">
                            </div>
                        </div>
                        <div class="modal-footer">
                            <button class="btn" onclick="closeModal('callNumberModal')">Cancel</button>
                            <button class="btn btn-success" onclick="callNumber()">Call Number</button>
                        </div>
                    </div>
                </div>
                
                <div id="addBalanceModal" class="modal">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h3>Add Balance to User</h3>
                            <button onclick="closeModal('addBalanceModal')" style="background: none; border: none; font-size: 1.5rem; cursor: pointer;">&times;</button>
                        </div>
                        <div class="modal-body">
                            <div class="form-group">
                                <label>User ID</label>
                                <input type="text" id="addBalanceUserId" class="form-control" placeholder="Enter user ID">
                            </div>
                            <div class="form-group">
                                <label>Amount (birr)</label>
                                <input type="number" id="addBalanceAmount" class="form-control" min="1" step="0.01">
                            </div>
                            <div class="form-group">
                                <label>Notes</label>
                                <textarea id="addBalanceNotes" class="form-control" rows="3" placeholder="Optional notes"></textarea>
                            </div>
                        </div>
                        <div class="modal-footer">
                            <button class="btn" onclick="closeModal('addBalanceModal')">Cancel</button>
                            <button class="btn btn-success" onclick="addBalance()">Add Balance</button>
                        </div>
                    </div>
                </div>
                
                <div id="approvePaymentModal" class="modal">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h3>Approve Payment</h3>
                            <button onclick="closeModal('approvePaymentModal')" style="background: none; border: none; font-size: 1.5rem; cursor: pointer;">&times;</button>
                        </div>
                        <div class="modal-body">
                            <input type="hidden" id="approvePaymentId">
                            <div class="form-group">
                                <label>Payment ID</label>
                                <input type="text" id="approvePaymentDisplayId" class="form-control" readonly>
                            </div>
                            <div class="form-group">
                                <label>Admin Notes</label>
                                <textarea id="approvePaymentNotes" class="form-control" rows="3" placeholder="Optional notes"></textarea>
                            </div>
                        </div>
                        <div class="modal-footer">
                            <button class="btn" onclick="closeModal('approvePaymentModal')">Cancel</button>
                            <button class="btn btn-success" onclick="approvePayment()">Approve Payment</button>
                        </div>
                    </div>
                </div>
                
                <div id="approveWithdrawalModal" class="modal">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h3>Approve Withdrawal</h3>
                            <button onclick="closeModal('approveWithdrawalModal')" style="background: none; border: none; font-size: 1.5rem; cursor: pointer;">&times;</button>
                        </div>
                        <div class="modal-body">
                            <input type="hidden" id="approveWithdrawalId">
                            <div class="form-group">
                                <label>Withdrawal ID</label>
                                <input type="text" id="approveWithdrawalDisplayId" class="form-control" readonly>
                            </div>
                            <div class="form-group">
                                <label>Admin Notes</label>
                                <textarea id="approveWithdrawalNotes" class="form-control" rows="3" placeholder="Optional notes"></textarea>
                            </div>
                        </div>
                        <div class="modal-footer">
                            <button class="btn" onclick="closeModal('approveWithdrawalModal')">Cancel</button>
                            <button class="btn btn-success" onclick="approveWithdrawal()">Approve Withdrawal</button>
                        </div>
                    </div>
                </div>
                
                <div class="notifications" id="notifications"></div>
                
                <script>
                    // Admin state
                    let adminState = {
                        currentTab: 'dashboard',
                        activeGame: null,
                        gamesPage: 1,
                        usersPage: 1,
                        paymentsPage: 1,
                        withdrawalsPage: 1,
                        transactionsPage: 1,
                        transactionFilter: 'all',
                        paymentStatus: 'pending',
                        withdrawalStatus: 'pending'
                    };
                    
                    // WebSocket connection
                    let adminWs = null;
                    
                    // Initialize admin panel
                    async function initAdminPanel() {
                        // Get admin ID from URL
                        const urlParams = new URLSearchParams(window.location.search);
                        const adminId = urlParams.get('admin_id') || 'admin';
                        
                        // Connect WebSocket
                        connectAdminWebSocket();
                        
                        // Load initial data
                        loadDashboardStats();
                        loadActiveGame();
                        loadRecentGames();
                        
                        // Set refresh interval
                        setInterval(loadDashboardStats, 10000);
                        
                        showNotification('✅ Admin panel loaded', 'success');
                    }
                    
                    // Connect admin WebSocket
                    function connectAdminWebSocket() {
                        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
                        const wsUrl = `${protocol}//${window.location.host}/ws`;
                        
                        adminWs = new WebSocket(wsUrl);
                        
                        adminWs.onopen = function() {
                            console.log('Admin WebSocket connected');
                        };
                        
                        adminWs.onmessage = function(event) {
                            try {
                                const data = JSON.parse(event.data);
                                handleAdminWebSocketMessage(data);
                            } catch (error) {
                                console.error('Error parsing admin WebSocket message:', error);
                            }
                        };
                        
                        adminWs.onerror = function(error) {
                            console.error('Admin WebSocket error:', error);
                        };
                        
                        adminWs.onclose = function() {
                            console.log('Admin WebSocket disconnected');
                            setTimeout(connectAdminWebSocket, 3000);
                        };
                    }
                    
                    // Handle admin WebSocket messages
                    function handleAdminWebSocketMessage(data) {
                        switch (data.type) {
                            case 'number_called':
                                showNotification(`🎲 Number ${data.number} called`, 'info');
                                break;
                                
                            case 'card_purchased':
                                if (adminState.currentTab === 'dashboard') {
                                    loadDashboardStats();
                                }
                                break;
                                
                            case 'bingo_claim_verified':
                                showNotification(`🎉 User ${data.user_id} won with ${data.pattern_type}!`, 'success');
                                break;
                                
                            case 'phase_transition':
                                showNotification(`🔄 Game phase changed to ${data.to_phase}`, 'info');
                                loadActiveGame();
                                break;
                                
                            case 'admin_game_started':
                                showNotification(`🎮 Game ${data.game_id} started by admin`, 'info');
                                break;
                                
                            case 'admin_game_stopped':
                                showNotification(`🛑 Game ${data.game_id} stopped by admin`, 'warning');
                                break;
                                
                            case 'admin_number_called':
                                showNotification(`🎲 Number ${data.number} called by admin`, 'info');
                                break;
                                
                            case 'pong':
                                // Keep-alive response
                                break;
                        }
                    }
                    
                    // Show tab
                    function showTab(tabName) {
                        // Update active tab in menu
                        document.querySelectorAll('.sidebar-menu a').forEach(a => a.classList.remove('active'));
                        event.target.classList.add('active');
                        
                        // Update active tab content
                        document.querySelectorAll('.tab-content').forEach(tab => tab.classList.remove('active'));
                        document.getElementById(tabName).classList.add('active');
                        
                        // Update page title
                        const titles = {
                            dashboard: 'Admin Dashboard',
                            games: 'Games Management',
                            users: 'Users Management',
                            payments: 'Payment Requests',
                            withdrawals: 'Withdrawal Requests',
                            transactions: 'Transaction History',
                            notifications: 'Send Notifications',
                            system: 'System Settings'
                        };
                        document.getElementById('pageTitle').textContent = titles[tabName] || 'Admin Panel';
                        
                        // Load tab data
                        adminState.currentTab = tabName;
                        
                        switch (tabName) {
                            case 'games':
                                loadGames();
                                break;
                            case 'users':
                                loadUsers();
                                break;
                            case 'payments':
                                loadPayments();
                                break;
                            case 'withdrawals':
                                loadWithdrawals();
                                break;
                            case 'transactions':
                                loadTransactions(1, adminState.transactionFilter);
                                break;
                            case 'system':
                                loadSystemStatus();
                                break;
                        }
                    }
                    
                    // Load dashboard statistics
                    async function loadDashboardStats() {
                        try {
                            const response = await fetch('/api/admin/stats');
                            const data = await response.json();
                            
                            if (data.success) {
                                document.getElementById('totalGames').textContent = data.stats.total_games;
                                document.getElementById('activeGames').textContent = data.stats.active_games;
                                document.getElementById('totalUsers').textContent = data.stats.total_users;
                                document.getElementById('onlineUsers').textContent = data.stats.online_players;
                                document.getElementById('todayRevenue').textContent = data.stats.today_revenue.toFixed(2) + ' birr';
                                document.getElementById('totalRevenue').textContent = data.stats.total_revenue.toFixed(2) + ' birr';
                                document.getElementById('totalBalance').textContent = data.stats.total_balance.toFixed(2) + ' birr';
                                document.getElementById('totalCommission').textContent = data.stats.this_week_commission.toFixed(2) + ' birr';
                            }
                        } catch (error) {
                            console.error('Error loading dashboard stats:', error);
                        }
                    }
                    
                    // Load active game
                    async function loadActiveGame() {
                        try {
                            const response = await fetch('/api/game/active');
                            const data = await response.json();
                            
                            if (data.success) {
                                adminState.activeGame = data;
                                
                                const container = document.getElementById('activeGameInfo');
                                container.innerHTML = `
                                    <div class="stat-item">
                                        <span class="stat-label">Game ID:</span>
                                        <span class="stat-value">${data.game_id}</span>
                                    </div>
                                    <div class="stat-item">
                                        <span class="stat-label">Status:</span>
                                        <span class="stat-value ${data.status === 'active' ? 'status-active' : data.status === 'card_purchase' ? 'status-pending' : 'status-completed'}">${data.status}</span>
                                    </div>
                                    <div class="stat-item">
                                        <span class="stat-label">Phase:</span>
                                        <span class="stat-value">${data.phase}</span>
                                    </div>
                                    <div class="stat-item">
                                        <span class="stat-label">Round:</span>
                                        <span class="stat-value">${data.round_number}</span>
                                    </div>
                                    <div class="stat-item">
                                        <span class="stat-label">Players:</span>
                                        <span class="stat-value">${data.total_players}</span>
                                    </div>
                                    <div class="stat-item">
                                        <span class="stat-label">Prize Pool:</span>
                                        <span class="stat-value">${data.prize_pool.toFixed(2)} birr</span>
                                    </div>
                                    <div class="stat-item">
                                        <span class="stat-label">Countdown:</span>
                                        <span class="stat-value">${data.countdown_remaining}s</span>
                                    </div>
                                `;
                                
                                // Update call number modal with game ID
                                document.getElementById('callNumberGameId').value = data.game_id;
                            }
                        } catch (error) {
                            console.error('Error loading active game:', error);
                        }
                    }
                    
                    // Load recent games
                    async function loadRecentGames() {
                        try {
                            const response = await fetch('/api/admin/games?limit=5');
                            const data = await response.json();
                            
                            if (data.success) {
                                const container = document.getElementById('recentGames');
                                if (data.games.length === 0) {
                                    container.innerHTML = '<p>No games found</p>';
                                    return;
                                }
                                
                                let html = '<table>';
                                html += `
                                    <thead>
                                        <tr>
                                            <th>Game ID</th>
                                            <th>Status</th>
                                            <th>Players</th>
                                            <th>Prize Pool</th>
                                            <th>Created</th>
                                            <th>Actions</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                `;
                                
                                data.games.forEach(game => {
                                    html += `
                                        <tr>
                                            <td>${game.game_id}</td>
                                            <td><span class="status-badge ${game.status === 'active' ? 'status-active' : game.status === 'completed' ? 'status-completed' : 'status-pending'}">${game.status}</span></td>
                                            <td>${game.total_players || 0}</td>
                                            <td>${parseFloat(game.prize_pool || 0).toFixed(2)} birr</td>
                                            <td>${new Date(game.created_at).toLocaleDateString()}</td>
                                            <td>
                                                <button class="btn btn-sm btn-primary" onclick="viewGameDetails('${game.game_id}')"><i class="fas fa-eye"></i></button>
                                            </td>
                                        </tr>
                                    `;
                                });
                                
                                html += '</tbody></table>';
                                container.innerHTML = html;
                            }
                        } catch (error) {
                            console.error('Error loading recent games:', error);
                        }
                    }
                    
                    // Load all games
                    async function loadGames(page = 1) {
                        try {
                            adminState.gamesPage = page;
                            const response = await fetch(`/api/admin/games?page=${page}&limit=20`);
                            const data = await response.json();
                            
                            if (data.success) {
                                const container = document.getElementById('gamesTable');
                                if (data.games.length === 0) {
                                    container.innerHTML = '<p>No games found</p>';
                                    return;
                                }
                                
                                let html = '<table>';
                                html += `
                                    <thead>
                                        <tr>
                                            <th>Game ID</th>
                                            <th>Round</th>
                                            <th>Status</th>
                                            <th>Players</th>
                                            <th>Cards Sold</th>
                                            <th>Prize Pool</th>
                                            <th>Created</th>
                                            <th>Actions</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                `;
                                
                                data.games.forEach(game => {
                                    html += `
                                        <tr>
                                            <td>${game.game_id}</td>
                                            <td>${game.round_number || 1}</td>
                                            <td><span class="status-badge ${game.status === 'active' ? 'status-active' : game.status === 'completed' ? 'status-completed' : 'status-pending'}">${game.status}</span></td>
                                            <td>${game.total_players || 0}</td>
                                            <td>${game.total_cards_sold || 0}</td>
                                            <td>${parseFloat(game.prize_pool || 0).toFixed(2)} birr</td>
                                            <td>${new Date(game.created_at).toLocaleDateString()}</td>
                                            <td>
                                                <button class="btn btn-sm btn-primary" onclick="viewGameDetails('${game.game_id}')"><i class="fas fa-eye"></i></button>
                                                ${game.status === 'card_purchase' ? `<button class="btn btn-sm btn-success" onclick="adminStartGame('${game.game_id}')"><i class="fas fa-play"></i></button>` : ''}
                                                ${game.status === 'active' ? `<button class="btn btn-sm btn-danger" onclick="adminStopGame('${game.game_id}')"><i class="fas fa-stop"></i></button>` : ''}
                                            </td>
                                        </tr>
                                    `;
                                });
                                
                                html += '</tbody></table>';
                                container.innerHTML = html;
                                
                                // Update pagination
                                updatePagination('gamesPagination', data.pagination);
                            }
                        } catch (error) {
                            console.error('Error loading games:', error);
                        }
                    }
                    
                    // Load users
                    async function loadUsers(page = 1) {
                        try {
                            adminState.usersPage = page;
                            const response = await fetch(`/api/admin/users?page=${page}&limit=20`);
                            const data = await response.json();
                            
                            if (data.success) {
                                const container = document.getElementById('usersTable');
                                if (data.users.length === 0) {
                                    container.innerHTML = '<p>No users found</p>';
                                    return;
                                }
                                
                                let html = '<table>';
                                html += `
                                    <thead>
                                        <tr>
                                            <th>User ID</th>
                                            <th>Username</th>
                                            <th>Full Name</th>
                                            <th>Balance</th>
                                            <th>Games Played</th>
                                            <th>Joined</th>
                                            <th>Actions</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                `;
                                
                                data.users.forEach(user => {
                                    html += `
                                        <tr>
                                            <td>${user.user_id}</td>
                                            <td>${user.username || 'N/A'}</td>
                                            <td>${user.full_name || 'N/A'}</td>
                                            <td>${parseFloat(user.balance || 0).toFixed(2)} birr</td>
                                            <td>${user.games_played || 0}</td>
                                            <td>${new Date(user.created_at).toLocaleDateString()}</td>
                                            <td>
                                                <button class="btn btn-sm btn-primary" onclick="viewUserDetails(${user.user_id})"><i class="fas fa-eye"></i></button>
                                                <button class="btn btn-sm btn-success" onclick="addBalanceToUser(${user.user_id})"><i class="fas fa-plus"></i></button>
                                            </td>
                                        </tr>
                                    `;
                                });
                                
                                html += '</tbody></table>';
                                container.innerHTML = html;
                                
                                // Update pagination
                                updatePagination('usersPagination', data.pagination);
                            }
                        } catch (error) {
                            console.error('Error loading users:', error);
                        }
                    }
                    
                    // Load payments
                    async function loadPayments(page = 1) {
                        try {
                            adminState.paymentsPage = page;
                            const response = await fetch(`/api/admin/payments?status=${adminState.paymentStatus}&page=${page}&limit=20`);
                            const data = await response.json();
                            
                            if (data.success) {
                                const container = document.getElementById('paymentsTable');
                                if (data.payments.length === 0) {
                                    container.innerHTML = '<p>No payments found</p>';
                                    return;
                                }
                                
                                let html = '<table>';
                                html += `
                                    <thead>
                                        <tr>
                                            <th>ID</th>
                                            <th>User</th>
                                            <th>Amount</th>
                                            <th>Method</th>
                                            <th>Status</th>
                                            <th>Requested</th>
                                            <th>Actions</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                `;
                                
                                data.payments.forEach(payment => {
                                    html += `
                                        <tr>
                                            <td>${payment.id}</td>
                                            <td>${payment.username || `User ${payment.user_id}`}</td>
                                            <td>${parseFloat(payment.amount).toFixed(2)} birr</td>
                                            <td>${payment.payment_method}</td>
                                            <td><span class="status-badge ${payment.status === 'approved' ? 'status-active' : payment.status === 'rejected' ? 'status-pending' : 'status-pending'}">${payment.status}</span></td>
                                            <td>${new Date(payment.created_at).toLocaleDateString()}</td>
                                            <td>
                                                ${payment.status === 'pending' ? `
                                                    <button class="btn btn-sm btn-success" onclick="openApprovePaymentModal(${payment.id})"><i class="fas fa-check"></i></button>
                                                    <button class="btn btn-sm btn-danger" onclick="rejectPayment(${payment.id})"><i class="fas fa-times"></i></button>
                                                ` : ''}
                                                <button class="btn btn-sm btn-primary" onclick="viewPaymentDetails(${payment.id})"><i class="fas fa-eye"></i></button>
                                            </td>
                                        </tr>
                                    `;
                                });
                                
                                html += '</tbody></table>';
                                container.innerHTML = html;
                                
                                // Update pagination
                                updatePagination('paymentsPagination', data.pagination);
                            }
                        } catch (error) {
                            console.error('Error loading payments:', error);
                        }
                    }
                    
                    // Load withdrawals
                    async function loadWithdrawals(page = 1) {
                        try {
                            adminState.withdrawalsPage = page;
                            const response = await fetch(`/api/admin/withdrawals?status=${adminState.withdrawalStatus}&page=${page}&limit=20`);
                            const data = await response.json();
                            if (data.success) {
                                const container = document.getElementById('withdrawalsTable');
                                if (data.withdrawals.length === 0) {
                                    container.innerHTML = '<p>No withdrawals found</p>';
                                    return;
                                }
                                
                                let html = '<table>';
                                html += `
                                    <thead>
                                        <tr>
                                            <th>ID</th>
                                            <th>User</th>
                                            <th>Amount</th>
                                            <th>Method</th>
                                            <th>Status</th>
                                            <th>Requested</th>
                                            <th>Actions</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                `;
                                
                                data.withdrawals.forEach(withdrawal => {
                                    html += `
                                        <tr>
                                            <td>${withdrawal.id}</td>
                                            <td>${withdrawal.username || `User ${withdrawal.user_id}`}</td>
                                            <td>${parseFloat(withdrawal.amount).toFixed(2)} birr</td>
                                            <td>${withdrawal.payment_method}</td>
                                            <td><span class="status-badge ${withdrawal.status === 'approved' ? 'status-active' : withdrawal.status === 'rejected' ? 'status-pending' : 'status-pending'}">${withdrawal.status}</span></td>
                                            <td>${new Date(withdrawal.requested_at).toLocaleDateString()}</td>
                                            <td>
                                                ${withdrawal.status === 'pending' ? `
                                                    <button class="btn btn-sm btn-success" onclick="openApproveWithdrawalModal(${withdrawal.id})"><i class="fas fa-check"></i></button>
                                                    <button class="btn btn-sm btn-danger" onclick="rejectWithdrawal(${withdrawal.id})"><i class="fas fa-times"></i></button>
                                                ` : ''}
                                                <button class="btn btn-sm btn-primary" onclick="viewWithdrawalDetails(${withdrawal.id})"><i class="fas fa-eye"></i></button>
                                            </td>
                                        </tr>
                                    `;
                                });
                                
                                html += '</tbody></table>';
                                container.innerHTML = html;
                                
                                // Update pagination
                                updatePagination('withdrawalsPagination', data.pagination);
                            }
                        } catch (error) {
                            console.error('Error loading withdrawals:', error);
                        }
                    }
                    
                    // Load transactions with filtering
                    async function loadTransactions(page = 1, typeFilter = 'all') {
                        try {
                            adminState.transactionsPage = page;
                            adminState.transactionFilter = typeFilter;
                            
                            // Update active tab
                            document.querySelectorAll('#transactions .tab-link').forEach(tab => {
                                tab.classList.remove('active');
                                if (tab.textContent.toLowerCase().includes(typeFilter) || 
                                    (typeFilter === 'all' && tab.textContent.toLowerCase().includes('all'))) {
                                    tab.classList.add('active');
                                }
                            });
                            
                            const response = await fetch(`/api/admin/transactions?page=${page}&limit=20&type=${typeFilter}`);
                            const data = await response.json();
                            
                            if (data.success) {
                                const container = document.getElementById('transactionsTable');
                                if (data.transactions.length === 0) {
                                    container.innerHTML = '<p>No transactions found</p>';
                                    return;
                                }
                                
                                let html = '<table>';
                                html += `
                                    <thead>
                                        <tr>
                                            <th>ID</th>
                                            <th>User</th>
                                            <th>Type</th>
                                            <th>Amount</th>
                                            <th>Description</th>
                                            <th>Date</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                `;
                                
                                data.transactions.forEach(transaction => {
                                    let typeClass = 'status-pending';
                                    if (transaction.transaction_type.includes('winning') || transaction.transaction_type.includes('deposit')) {
                                        typeClass = 'status-active';
                                    } else if (transaction.transaction_type.includes('withdrawal')) {
                                        typeClass = 'status-completed';
                                    }
                                    
                                    html += `
                                        <tr>
                                            <td>${transaction.id}</td>
                                            <td>${transaction.username || `User ${transaction.user_id}`}</td>
                                            <td><span class="status-badge ${typeClass}">${transaction.transaction_type}</span></td>
                                            <td>${parseFloat(transaction.amount).toFixed(2)} birr</td>
                                            <td>${transaction.description || ''}</td>
                                            <td>${new Date(transaction.created_at).toLocaleDateString()}</td>
                                        </tr>
                                    `;
                                });
                                
                                html += '</tbody></table>';
                                container.innerHTML = html;
                                
                                // Update pagination
                                updatePagination('transactionsPagination', data.pagination);
                            }
                        } catch (error) {
                            console.error('Error loading transactions:', error);
                        }
                    }
                    
                    // Show transaction tab
                    function showTransactionTab(type) {
                        loadTransactions(1, type);
                    }
                    
                    // Show payment tab
                    function showPaymentTab(status) {
                        document.querySelectorAll('#payments .tab-link').forEach(tab => tab.classList.remove('active'));
                        event.target.classList.add('active');
                        adminState.paymentStatus = status;
                        loadPayments(1);
                    }
                    
                    // Show withdrawal tab
                    function showWithdrawalTab(status) {
                        document.querySelectorAll('#withdrawals .tab-link').forEach(tab => tab.classList.remove('active'));
                        event.target.classList.add('active');
                        adminState.withdrawalStatus = status;
                        loadWithdrawals(1);
                    }
                    
                    // Update pagination
                    function updatePagination(elementId, pagination) {
                        const container = document.getElementById(elementId);
                        if (!container) return;
                        
                        let html = '';
                        
                        if (pagination.page > 1) {
                            html += `<button class="page-link" onclick="load${elementId.replace('Pagination', '')}(${pagination.page - 1})">Previous</button>`;
                        }
                        
                        const startPage = Math.max(1, pagination.page - 2);
                        const endPage = Math.min(pagination.pages, pagination.page + 2);
                        
                        for (let i = startPage; i <= endPage; i++) {
                            html += `<button class="page-link ${i === pagination.page ? 'active' : ''}" onclick="load${elementId.replace('Pagination', '')}(${i})">${i}</button>`;
                        }
                        
                        if (pagination.page < pagination.pages) {
                            html += `<button class="page-link" onclick="load${elementId.replace('Pagination', '')}(${pagination.page + 1})">Next</button>`;
                        }
                        
                        container.innerHTML = html;
                    }
                    
                    // Open call number modal
                    function openCallNumberModal() {
                        if (!adminState.activeGame) {
                            showNotification('❌ No active game found', 'error');
                            return;
                        }
                        
                        document.getElementById('callNumberGameId').value = adminState.activeGame.game_id;
                        document.getElementById('callNumberInput').value = '';
                        document.getElementById('callNumberModal').style.display = 'flex';
                    }
                    
                    // Call number
                    async function callNumber() {
                        const gameId = document.getElementById('callNumberGameId').value;
                        const number = parseInt(document.getElementById('callNumberInput').value);
                        
                        if (!number || number < 1 || number > 75) {
                            showNotification('❌ Please enter a valid number between 1 and 75', 'error');
                            return;
                        }
                        
                        try {
                            const response = await fetch('/api/admin/callnumber', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({
                                    game_id: gameId,
                                    number: number,
                                    admin_id: 'admin'
                                })
                            });
                            
                            const data = await response.json();
                            if (data.success) {
                                showNotification(`✅ Number ${number} called successfully`, 'success');
                                closeModal('callNumberModal');
                            } else {
                                showNotification(`❌ ${data.message}`, 'error');
                            }
                        } catch (error) {
                            console.error('Error calling number:', error);
                            showNotification('❌ Failed to call number', 'error');
                        }
                    }
                    
                    // Start current game
                    async function startCurrentGame() {
                        if (!adminState.activeGame) {
                            showNotification('❌ No active game found', 'error');
                            return;
                        }
                        
                        try {
                            const response = await fetch('/api/admin/startgame', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({
                                    game_id: adminState.activeGame.game_id,
                                    admin_id: 'admin'
                                })
                            });
                            
                            const data = await response.json();
                            if (data.success) {
                                showNotification('✅ Game started successfully', 'success');
                                loadActiveGame();
                            } else {
                                showNotification(`❌ ${data.message}`, 'error');
                            }
                        } catch (error) {
                            console.error('Error starting game:', error);
                            showNotification('❌ Failed to start game', 'error');
                        }
                    }
                    
                    // Stop current game
                    async function stopCurrentGame() {
                        if (!adminState.activeGame) {
                            showNotification('❌ No active game found', 'error');
                            return;
                        }
                        
                        if (!confirm('Are you sure you want to stop the current game?')) {
                            return;
                        }
                        
                        try {
                            const response = await fetch('/api/admin/stopgame', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({
                                    game_id: adminState.activeGame.game_id,
                                    admin_id: 'admin'
                                })
                            });
                            
                            const data = await response.json();
                            if (data.success) {
                                showNotification('✅ Game stopped successfully', 'success');
                                loadActiveGame();
                            } else {
                                showNotification(`❌ ${data.message}`, 'error');
                            }
                        } catch (error) {
                            console.error('Error stopping game:', error);
                            showNotification('❌ Failed to stop game', 'error');
                        }
                    }
                    
                    // Admin start game
                    async function adminStartGame(gameId) {
                        try {
                            const response = await fetch('/api/admin/startgame', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({
                                    game_id: gameId,
                                    admin_id: 'admin'
                                })
                            });
                            
                            const data = await response.json();
                            if (data.success) {
                                showNotification('✅ Game started successfully', 'success');
                                loadGames(adminState.gamesPage);
                            } else {
                                showNotification(`❌ ${data.message}`, 'error');
                            }
                        } catch (error) {
                            console.error('Error starting game:', error);
                            showNotification('❌ Failed to start game', 'error');
                        }
                    }
                    
                    // Admin stop game
                    async function adminStopGame(gameId) {
                        if (!confirm('Are you sure you want to stop this game?')) {
                            return;
                        }
                        
                        try {
                            const response = await fetch('/api/admin/stopgame', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({
                                    game_id: gameId,
                                    admin_id: 'admin'
                                })
                            });
                            
                            const data = await response.json();
                            if (data.success) {
                                showNotification('✅ Game stopped successfully', 'success');
                                loadGames(adminState.gamesPage);
                            } else {
                                showNotification(`❌ ${data.message}`, 'error');
                            }
                        } catch (error) {
                            console.error('Error stopping game:', error);
                            showNotification('❌ Failed to stop game', 'error');
                        }
                    }
                    
                    // Open add balance modal
                    function openAddBalanceModal(userId = '') {
                        document.getElementById('addBalanceUserId').value = userId;
                        document.getElementById('addBalanceAmount').value = '';
                        document.getElementById('addBalanceNotes').value = '';
                        document.getElementById('addBalanceModal').style.display = 'flex';
                    }
                    
                    // Add balance to user
                    function addBalanceToUser(userId) {
                        openAddBalanceModal(userId);
                    }
                    
                    // Add balance
                    async function addBalance() {
                        const userId = document.getElementById('addBalanceUserId').value;
                        const amount = parseFloat(document.getElementById('addBalanceAmount').value);
                        const notes = document.getElementById('addBalanceNotes').value;
                        
                        if (!userId || !amount || amount <= 0) {
                            showNotification('❌ Please enter valid user ID and amount', 'error');
                            return;
                        }
                        
                        try {
                            const response = await fetch('/api/admin/addbalance', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({
                                    user_id: userId,
                                    amount: amount,
                                    notes: notes,
                                    admin_id: 'admin'
                                })
                            });
                            
                            const data = await response.json();
                            if (data.success) {
                                showNotification(`✅ Added ${amount} birr to user ${userId}`, 'success');
                                closeModal('addBalanceModal');
                                loadUsers(adminState.usersPage);
                            } else {
                                showNotification(`❌ ${data.message}`, 'error');
                            }
                        } catch (error) {
                            console.error('Error adding balance:', error);
                            showNotification('❌ Failed to add balance', 'error');
                        }
                    }
                    
                    // Open approve payment modal
                    function openApprovePaymentModal(paymentId) {
                        document.getElementById('approvePaymentId').value = paymentId;
                        document.getElementById('approvePaymentDisplayId').value = paymentId;
                        document.getElementById('approvePaymentNotes').value = '';
                        document.getElementById('approvePaymentModal').style.display = 'flex';
                    }
                    
                    // Approve payment
                    async function approvePayment() {
                        const paymentId = document.getElementById('approvePaymentId').value;
                        const notes = document.getElementById('approvePaymentNotes').value;
                        
                        try {
                            const response = await fetch('/api/admin/approvepayment', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({
                                    payment_id: paymentId,
                                    admin_id: 'admin',
                                    notes: notes
                                })
                            });
                            
                            const data = await response.json();
                            if (data.success) {
                                showNotification('✅ Payment approved successfully', 'success');
                                closeModal('approvePaymentModal');
                                loadPayments(adminState.paymentsPage);
                            } else {
                                showNotification(`❌ ${data.message}`, 'error');
                            }
                        } catch (error) {
                            console.error('Error approving payment:', error);
                            showNotification('❌ Failed to approve payment', 'error');
                        }
                    }
                    
                    // Open approve withdrawal modal
                    function openApproveWithdrawalModal(withdrawalId) {
                        document.getElementById('approveWithdrawalId').value = withdrawalId;
                        document.getElementById('approveWithdrawalDisplayId').value = withdrawalId;
                        document.getElementById('approveWithdrawalNotes').value = '';
                        document.getElementById('approveWithdrawalModal').style.display = 'flex';
                    }
                    
                    // Approve withdrawal
                    async function approveWithdrawal() {
                        const withdrawalId = document.getElementById('approveWithdrawalId').value;
                        const notes = document.getElementById('approveWithdrawalNotes').value;
                        
                        try {
                            const response = await fetch('/api/admin/approvewithdrawal', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({
                                    withdrawal_id: withdrawalId,
                                    admin_id: 'admin',
                                    notes: notes
                                })
                            });
                            
                            const data = await response.json();
                            if (data.success) {
                                showNotification('✅ Withdrawal approved successfully', 'success');
                                closeModal('approveWithdrawalModal');
                                loadWithdrawals(adminState.withdrawalsPage);
                            } else {
                                showNotification(`❌ ${data.message}`, 'error');
                            }
                        } catch (error) {
                            console.error('Error approving withdrawal:', error);
                            showNotification('❌ Failed to approve withdrawal', 'error');
                        }
                    }
                    
                    // Send notification
                    async function sendNotification() {
                        const title = document.getElementById('notificationTitle').value;
                        const message = document.getElementById('notificationMessage').value;
                        const target = document.getElementById('notificationTarget').value;
                        const specificUserIds = document.getElementById('specificUserIds').value;
                        
                        if (!title || !message) {
                            showNotification('❌ Title and message are required', 'error');
                            return;
                        }
                        
                        const data = {
                            title: title,
                            message: message,
                            target: target,
                            admin_id: 'admin'
                        };
                        
                        if (target === 'specific' && specificUserIds) {
                            data.target_ids = specificUserIds.split(',').map(id => id.trim());
                        }
                        
                        try {
                            const response = await fetch('/api/admin/notification', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify(data)
                            });
                            
                            const result = await response.json();
                            if (result.success) {
                                showNotification('✅ Notification sent successfully', 'success');
                                document.getElementById('notificationTitle').value = '';
                                document.getElementById('notificationMessage').value = '';
                                document.getElementById('specificUserIds').value = '';
                            } else {
                                showNotification(`❌ ${result.message}`, 'error');
                            }
                        } catch (error) {
                            console.error('Error sending notification:', error);
                            showNotification('❌ Failed to send notification', 'error');
                        }
                    }
                    
                    // Toggle notification target
                    function toggleNotificationTarget() {
                        const target = document.getElementById('notificationTarget').value;
                        const specificGroup = document.getElementById('specificUsersGroup');
                        
                        if (target === 'specific') {
                            specificGroup.style.display = 'block';
                        } else {
                            specificGroup.style.display = 'none';
                        }
                    }
                    
                    // Load system status
                    async function loadSystemStatus() {
                        try {
                            const response = await fetch('/api/system/status');
                            const data = await response.json();
                            
                            if (data.success) {
                                const container = document.getElementById('systemStatus');
                                container.innerHTML = `
                                    <div class="stat-item">
                                        <span class="stat-label">WebSocket Connections:</span>
                                        <span class="stat-value">${data.websocket.connections}</span>
                                    </div>
                                    <div class="stat-item">
                                        <span class="stat-label">Authenticated Users:</span>
                                        <span class="stat-value">${data.websocket.authenticated_users}</span>
                                    </div>
                                    <div class="stat-item">
                                        <span class="stat-label">Server Status:</span>
                                        <span class="stat-value status-active">Healthy</span>
                                    </div>
                                    <div class="stat-item">
                                        <span class="stat-label">Last Updated:</span>
                                        <span class="stat-value">${new Date(data.timestamp).toLocaleString()}</span>
                                    </div>
                                `;
                            }
                        } catch (error) {
                            console.error('Error loading system status:', error);
                        }
                    }
                    
                    // View game details
                    function viewGameDetails(gameId) {
                        window.open(`/api/admin/gamedetails/${gameId}`, '_blank');
                    }
                    
                    // View user details
                    function viewUserDetails(userId) {
                        showNotification(`Viewing user ${userId} details`, 'info');
                        // Implement user details view
                    }
                    
                    // View payment details
                    function viewPaymentDetails(paymentId) {
                        window.open(`/api/admin/payment/${paymentId}`, '_blank');
                    }
                    
                    // View withdrawal details
                    function viewWithdrawalDetails(withdrawalId) {
                        window.open(`/api/admin/withdrawal/${withdrawalId}`, '_blank');
                    }
                    
                    // Reject payment
                    async function rejectPayment(paymentId) {
                        const reason = prompt('Enter rejection reason:');
                        if (!reason) return;
                        
                        try {
                            const response = await fetch('/api/admin/rejectpayment', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({
                                    payment_id: paymentId,
                                    admin_id: 'admin',
                                    reason: reason
                                })
                            });
                            
                            const data = await response.json();
                            if (data.success) {
                                showNotification('✅ Payment rejected', 'success');
                                loadPayments(adminState.paymentsPage);
                            } else {
                                showNotification(`❌ ${data.message}`, 'error');
                            }
                        } catch (error) {
                            console.error('Error rejecting payment:', error);
                            showNotification('❌ Failed to reject payment', 'error');
                        }
                    }
                    
                    // Reject withdrawal
                    async function rejectWithdrawal(withdrawalId) {
                        const reason = prompt('Enter rejection reason:');
                        if (!reason) return;
                        
                        try {
                            const response = await fetch('/api/admin/rejectwithdrawal', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({
                                    withdrawal_id: withdrawalId,
                                    admin_id: 'admin',
                                    reason: reason
                                })
                            });
                            
                            const data = await response.json();
                            if (data.success) {
                                showNotification('✅ Withdrawal rejected and refunded', 'success');
                                loadWithdrawals(adminState.withdrawalsPage);
                            } else {
                                showNotification(`❌ ${data.message}`, 'error');
                            }
                        } catch (error) {
                            console.error('Error rejecting withdrawal:', error);
                            showNotification('❌ Failed to reject withdrawal', 'error');
                        }
                    }
                    
                    // Close modal
                    function closeModal(modalId) {
                        document.getElementById(modalId).style.display = 'none';
                    }
                    
                    // Show notification
                    function showNotification(message, type = 'info') {
                        const container = document.getElementById('notifications');
                        const notification = document.createElement('div');
                        notification.className = `notification ${type}`;
                        notification.textContent = message;
                        container.appendChild(notification);
                        
                        setTimeout(() => {
                            notification.remove();
                        }, 5000);
                    }
                    
                    // Search games
                    function searchGames() {
                        const searchTerm = document.getElementById('gameSearch').value.toLowerCase();
                        const rows = document.querySelectorAll('#gamesTable tbody tr');
                        
                        rows.forEach(row => {
                            const text = row.textContent.toLowerCase();
                            row.style.display = text.includes(searchTerm) ? '' : 'none';
                        });
                    }
                    
                    // Search users
                    function searchUsers() {
                        const searchTerm = document.getElementById('userSearch').value.toLowerCase();
                        const rows = document.querySelectorAll('#usersTable tbody tr');
                        
                        rows.forEach(row => {
                            const text = row.textContent.toLowerCase();
                            row.style.display = text.includes(searchTerm) ? '' : 'none';
                        });
                    }
                    
                    // Search transactions
                    function searchTransactions() {
                        const searchTerm = document.getElementById('transactionSearch').value.toLowerCase();
                        const rows = document.querySelectorAll('#transactionsTable tbody tr');
                        
                        rows.forEach(row => {
                            const text = row.textContent.toLowerCase();
                            row.style.display = text.includes(searchTerm) ? '' : 'none';
                        });
                    }
                    
                    // Clear user search
                    function clearUserSearch() {
                        document.getElementById('userSearch').value = '';
                        loadUsers(1);
                    }
                    
                    // System actions (placeholder)
                    function restartGameManager() {
                        showNotification('🔄 Restarting game manager...', 'info');
                        setTimeout(() => {
                            showNotification('✅ Game manager restarted', 'success');
                        }, 1000);
                    }
                    
                    function clearCache() {
                        showNotification('🗑️ Clearing cache...', 'info');
                        setTimeout(() => {
                            showNotification('✅ Cache cleared', 'success');
                        }, 1000);
                    }
                    
                    function backupDatabase() {
                        showNotification('💾 Backing up database...', 'info');
                        setTimeout(() => {
                            showNotification('✅ Database backup completed', 'success');
                        }, 1000);
                    }
                    
                    function checkHealth() {
                        window.open('/health', '_blank');
                    }
                    
                    // Initialize admin panel
                    window.onload = initAdminPanel;
                </script>
            </body>
            </html>
            """
        
        return web.Response(
            text=html_content,
            content_type='text/html',
            headers={
                'Cache-Control': 'no-cache, no-store, must-revalidate',
                'Pragma': 'no-cache',
                'Expires': '0',
                'Access-Control-Allow-Origin': '*'
            }
        )
    except Exception as e:
        logger.error(f"Error serving admin.html: {e}", exc_info=True)
        error_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Error - Habesha Bingo Admin</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 40px; background-color: #f5f5f5; }}
                .container {{ max-width: 800px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 0 20px rgba(0,0,0,0.1); }}
                h1 {{ color: #e74c3c; }}
                .error {{ background: #f8d7da; color: #721c24; padding: 15px; border-radius: 5px; margin: 20px 0; border: 1px solid #f5c6cb; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>❌ Error Loading Admin Panel</h1>
                <div class="error">
                    Error: {str(e)}
                </div>
                <p>Please check the server logs for more details.</p>
                <p><a href="/">Return to Home Page</a></p>
            </div>
        </body>
        </html>
        """
        return web.Response(text=error_html, content_type='text/html', status=500)


# ==================== MAIN APPLICATION SETUP ====================
app = web.Application(middlewares=[cors_middleware])
app.add_routes(routes)

if __name__ == '__main__':
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('web_server.log')
        ]
    )
    
    logger.info(f"Starting Habesha Bingo Web Server on {WEBSERVER_HOST}:{WEBSERVER_PORT}")
    logger.info(f"Web App URL: {WEB_APP_URL}")
    
    # Start the server
    web.run_app(app, host=WEBSERVER_HOST, port=WEBSERVER_PORT)


# ==================== SERVER START FUNCTION ====================
async def run_server():
    """Run the web server - main entry point"""
    # Create necessary directories
    import os
    os.makedirs('/app/static', exist_ok=True)
    os.makedirs('/app/sounds', exist_ok=True)
    os.makedirs('/app/html', exist_ok=True)
    
    # Initialize commission table
    from database.db import Database
    try:
        with Database.get_cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS commission_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    game_id TEXT NOT NULL,
                    commission_amount REAL NOT NULL,
                    real_players_count INTEGER NOT NULL,
                    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status TEXT DEFAULT 'recorded',
                    FOREIGN KEY (game_id) REFERENCES games(game_id)
                )
            """)
            logger.info("✅ commission_records table initialized")
    except Exception as e:
        logger.error(f"Error initializing commission_records table: {e}")
    
    app = web.Application(middlewares=[cors_middleware])
    app.add_routes(routes)
    
    # Configure static file serving for HTML files (optional - can comment out)
    try:
        app.router.add_static('/static/', path='/app/static/', name='static')
        app.router.add_static('/sounds/', path='/app/sounds/', name='sounds')
        logger.info("✅ Static file serving configured")
    except Exception as e:
        logger.warning(f"⚠️ Static file serving disabled: {e}")
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    # Use port 8001
    site = web.TCPSite(runner, WEBSERVER_HOST, 8001)
    await site.start()
    
    logger.info(f"✅ Web server started on http://{WEBSERVER_HOST}:8001")
    logger.info(f"✅ WebSocket server ready on ws://{WEBSERVER_HOST}:8001/ws")
    logger.info(f"✅ Game interface: http://{WEBSERVER_HOST}:8001/game.html")
    logger.info(f"✅ Admin panel: http://{WEBSERVER_HOST}:8001/admin.html")
    logger.info("Press Ctrl+C to stop the server")
    
    try:
        # Keep server running
        while True:
            await asyncio.sleep(3600)  # Sleep for 1 hour at a time
    except asyncio.CancelledError:
        logger.info("Server shutdown requested")
    finally:
        await runner.cleanup()
        await websocket_server.cleanup()

# Function name that the bot expects
start_web_server = run_server