import asyncio
import json
import logging
import ssl
from websockets.server import serve
from websockets.exceptions import ConnectionClosed, ConnectionClosedError
from websockets.legacy.server import WebSocketServerProtocol
from typing import Set, Dict, Optional
from config import WEBSOCKET_PORT
from database.db import Database
from datetime import datetime
from utils.game_manager import GameManager

logger = logging.getLogger(__name__)

class GameWebSocketServer:
    def __init__(self):
        self.connections: Set[WebSocketServerProtocol] = set()
        self.user_connections: Dict[str, WebSocketServerProtocol] = {}  # user_id -> websocket
        self.active_games: Dict[str, dict] = {}  # game_id -> game data
        self._keep_alive_task = None
        self._max_retries = 5
        self._retry_delay = 2
        self._ping_interval = 30  # Send ping every 30 seconds
        self._connection_timeout = 60  # Close connection after 60 seconds of inactivity
        self._shutting_down = False
        
    async def cleanup(self):
        """Cleanup resources on shutdown"""
        self._shutting_down = True
        
        # Cancel keep-alive task
        if self._keep_alive_task:
            self._keep_alive_task.cancel()
            try:
                await self._keep_alive_task
            except asyncio.CancelledError:
                pass
        
        # Close all connections gracefully
        close_tasks = []
        for websocket in list(self.connections):
            try:
                await websocket.close(code=1000, reason="Server shutting down")
            except Exception as e:
                logger.debug(f"Error closing connection: {e}")
        
        self.connections.clear()
        self.user_connections.clear()
        logger.info("WebSocket server cleanup completed")
    
    async def handle_connection(self, websocket: WebSocketServerProtocol, path: str):
        """Handle new WebSocket connection with improved error handling"""
        client_address = websocket.remote_address
        connection_id = f"{client_address[0]}:{client_address[1]}"
        
        # Set timeout for connection
        websocket.timeout = self._connection_timeout
        
        self.connections.add(websocket)
        logger.info(f"WebSocket connection established from {connection_id}")
        
        try:
            # Send welcome message with error handling
            try:
                await self._safe_send(websocket, {
                    'type': 'welcome',
                    'message': 'Connected to Habesha Bingo WebSocket server',
                    'timestamp': datetime.now().isoformat(),
                    'connection_id': connection_id
                })
            except Exception as e:
                logger.warning(f"Failed to send welcome to {connection_id}: {e}")
            
            # Get active game
            try:
                active_game = await GameManager.get_active_continuous_game()
                if active_game:
                    game_state = await GameManager.get_game_status(active_game['game_id'])
                    await self._safe_send(websocket, {
                        'type': 'current_game_state',
                        'data': game_state
                    })
            except Exception as e:
                logger.error(f"Error sending initial game state to {connection_id}: {e}")
            
            # Main message handling loop
            while not self._shutting_down:
                try:
                    message = await websocket.recv()
                    
                    if isinstance(message, bytes):
                        message = message.decode('utf-8')
                    
                    try:
                        data = json.loads(message)
                        await self.handle_message(websocket, data, connection_id)
                    except json.JSONDecodeError as e:
                        await self._safe_send(websocket, {
                            'type': 'error',
                            'message': 'Invalid JSON format',
                            'details': str(e)
                        })
                        logger.warning(f"Invalid JSON from {connection_id}: {e}")
                    except Exception as e:
                        logger.error(f"Error processing message from {connection_id}: {e}")
                        await self._safe_send(websocket, {
                            'type': 'error',
                            'message': f'Server error: {str(e)[:100]}'
                        })
                        
                except (ConnectionClosed, ConnectionClosedError) as e:
                    logger.info(f"WebSocket connection closed normally from {connection_id}: {e}")
                    break
                except asyncio.TimeoutError:
                    logger.info(f"Connection timeout for {connection_id}")
                    break
                except Exception as e:
                    logger.error(f"Unexpected error in connection loop for {connection_id}: {e}")
                    break
                    
        except Exception as e:
            logger.error(f"WebSocket error from {connection_id}: {e}", exc_info=True)
        finally:
            # Remove connection
            self.connections.discard(websocket)
            
            # Remove from user connections
            for user_id, ws in list(self.user_connections.items()):
                if ws == websocket:
                    del self.user_connections[user_id]
                    logger.info(f"User {user_id} disconnected from WebSocket")
                    break
            
            logger.info(f"Connection closed from {connection_id}. Total connections: {len(self.connections)}")
    
    async def handle_message(self, websocket: WebSocketServerProtocol, data: dict, connection_id: str):
        """Handle incoming WebSocket messages with better error handling"""
        msg_type = data.get('type')
        
        try:
            if msg_type == 'auth':
                await self._handle_auth(websocket, data, connection_id)
            elif msg_type == 'ping':
                await self._handle_ping(websocket)
            elif msg_type == 'get_game_status':
                await self._handle_get_game_status(websocket, data)
            elif msg_type == 'get_user_game_state':
                await self._handle_get_user_game_state(websocket, data)
            elif msg_type == 'buy_card':
                await self._handle_buy_card(websocket, data)
            elif msg_type == 'claim_bingo':
                await self._handle_claim_bingo(websocket, data)
            elif msg_type == 'get_balances':
                await self._handle_get_balances(websocket, data)
            elif msg_type in ['admin_start_game', 'admin_stop_game']:
                await self._handle_admin_command(websocket, data, msg_type)
            else:
                await self._safe_send(websocket, {
                    'type': 'error',
                    'message': f'Unknown message type: {msg_type}'
                })
                logger.warning(f"Unknown message type from {connection_id}: {msg_type}")
                
        except Exception as e:
            logger.error(f"Error handling message type {msg_type} from {connection_id}: {e}")
            await self._safe_send(websocket, {
                'type': 'error',
                'message': f'Error processing {msg_type}: {str(e)[:100]}'
            })
    
    async def _handle_auth(self, websocket: WebSocketServerProtocol, data: dict, connection_id: str):
        """Handle authentication"""
        user_id = data.get('userId')
        if user_id:
            # Remove old connection for this user if exists
            old_ws = self.user_connections.get(str(user_id))
            if old_ws and old_ws != websocket:
                try:
                    await old_ws.close(code=1000, reason="New login from different device")
                except:
                    pass
            
            self.user_connections[str(user_id)] = websocket
            await self._safe_send(websocket, {
                'type': 'auth_success',
                'message': f'Authenticated as user {user_id}',
                'user_id': user_id,
                'connection_id': connection_id
            })
            logger.info(f"User {user_id} authenticated via WebSocket from {connection_id}")
        else:
            await self._safe_send(websocket, {
                'type': 'auth_error',
                'message': 'User ID required for authentication'
            })
    
    async def _handle_ping(self, websocket: WebSocketServerProtocol):
        """Handle ping request"""
        await self._safe_send(websocket, {
            'type': 'pong',
            'timestamp': datetime.now().isoformat()
        })
    
    async def _handle_get_game_status(self, websocket: WebSocketServerProtocol, data: dict):
        """Handle get game status request"""
        game_id = data.get('game_id')
        if game_id:
            game_status = await GameManager.get_game_status(game_id)
            await self._safe_send(websocket, {
                'type': 'game_status',
                'data': game_status
            })
    
    async def _handle_get_user_game_state(self, websocket: WebSocketServerProtocol, data: dict):
        """Handle get user game state request"""
        game_id = data.get('game_id')
        user_id = data.get('user_id')
        if game_id and user_id:
            try:
                user_state = await GameManager.get_user_game_state(game_id, int(user_id))
                await self._safe_send(websocket, {
                    'type': 'user_game_state',
                    'data': user_state
                })
            except ValueError:
                await self._safe_send(websocket, {
                    'type': 'error',
                    'message': 'Invalid user ID format'
                })
    
    async def _handle_buy_card(self, websocket: WebSocketServerProtocol, data: dict):
        """Handle buy card request"""
        game_id = data.get('game_id')
        user_id = data.get('user_id')
        if game_id and user_id:
            try:
                result = await GameManager.player_buy_card_continuous(int(user_id), game_id)
                await self._safe_send(websocket, {
                    'type': 'card_purchase_result',
                    'data': result
                })
                
                # Broadcast player joined update
                if result.get('success'):
                    await self.broadcast_with_retry({
                        'type': 'player_joined',
                        'game_id': game_id,
                        'user_id': user_id,
                        'prize_pool': result.get('prize_pool', 0),
                        'timestamp': datetime.now().isoformat()
                    })
            except ValueError:
                await self._safe_send(websocket, {
                    'type': 'error',
                    'message': 'Invalid user ID format'
                })
    
    async def _handle_claim_bingo(self, websocket: WebSocketServerProtocol, data: dict):
        """Handle claim bingo request"""
        game_id = data.get('game_id')
        user_id = data.get('user_id')
        if game_id and user_id:
            try:
                result = await GameManager.player_claim_bingo(int(user_id), game_id)
                await self._safe_send(websocket, {
                    'type': 'bingo_claim_result',
                    'data': result
                })
            except ValueError:
                await self._safe_send(websocket, {
                    'type': 'error',
                    'message': 'Invalid user ID format'
                })
    
    async def _handle_get_balances(self, websocket: WebSocketServerProtocol, data: dict):
        """Handle get balances request"""
        game_id = data.get('game_id')
        if game_id:
            try:
                players = await Database.get_game_players(game_id)
                await self._safe_send(websocket, {
                    'type': 'balances',
                    'data': players,
                    'game_id': game_id
                })
            except Exception as e:
                logger.error(f"Error getting balances: {e}")
                await self._safe_send(websocket, {
                    'type': 'error',
                    'message': 'Error retrieving balances'
                })
    
    async def _handle_admin_command(self, websocket: WebSocketServerProtocol, data: dict, msg_type: str):
        """Handle admin commands"""
        # Add admin authentication here if needed
        game_id = data.get('game_id')
        if game_id:
            if msg_type == 'admin_start_game':
                await GameManager.start_continuous_game_numbers(game_id)
                await self._safe_send(websocket, {
                    'type': 'admin_response',
                    'message': f'Game {game_id} started'
                })
            elif msg_type == 'admin_stop_game':
                await GameManager.stop_continuous_game(game_id)
                await self._safe_send(websocket, {
                    'type': 'admin_response',
                    'message': f'Game {game_id} stopped'
                })
    
    async def _safe_send(self, websocket: WebSocketServerProtocol, message: dict) -> bool:
        """Safely send message with error handling"""
        try:
            if websocket.closed:
                return False
            
            await websocket.send(json.dumps(message))
            return True
        except (ConnectionClosed, ConnectionClosedError):
            return False
        except Exception as e:
            logger.debug(f"Error sending message: {e}")
            return False
    
    async def broadcast_with_retry(self, message: dict, max_retries: int = 3):
        """Broadcast message with retry logic"""
        for attempt in range(max_retries):
            try:
                await self.broadcast(message)
                return True
            except Exception as e:
                if attempt == max_retries - 1:
                    logger.error(f"Failed to broadcast after {max_retries} attempts: {e}")
                    return False
                await asyncio.sleep(1 * (attempt + 1))  # Exponential backoff
        
        return False
    
    async def broadcast(self, message: dict):
        """Broadcast message to all connected clients with improved error handling"""
        disconnected = set()
        
        for websocket in list(self.connections):
            try:
                await websocket.send(json.dumps(message))
            except (ConnectionClosed, ConnectionClosedError):
                disconnected.add(websocket)
            except Exception as e:
                logger.debug(f"Error broadcasting to {websocket.remote_address}: {e}")
                disconnected.add(websocket)
        
        # Remove disconnected clients
        if disconnected:
            for websocket in disconnected:
                self.connections.discard(websocket)
                
                # Remove from user connections
                for user_id, ws in list(self.user_connections.items()):
                    if ws == websocket:
                        del self.user_connections[user_id]
                        break
            
            logger.info(f"Removed {len(disconnected)} disconnected WebSocket clients")
    
    async def broadcast_game_update(self, game_id: str, update_type: str, data: dict = None):
        """Broadcast game update to all connected clients"""
        try:
            if data is None:
                data = {}
            
            message = {
                'type': 'game_update',
                'game_id': game_id,
                'update_type': update_type,
                'data': data,
                'timestamp': datetime.now().isoformat()
            }
            
            success = await self.broadcast_with_retry(message)
            if success:
                logger.info(f"📢 Broadcast {update_type} for game {game_id}")
            else:
                logger.warning(f"Failed to broadcast {update_type} for game {game_id}")
            
            return success
        except Exception as e:
            logger.error(f"Error in broadcast_game_update: {e}")
            return False
    
    async def send_to_user(self, user_id: str, message: dict) -> bool:
        """Send message to specific user with error handling"""
        try:
            websocket = self.user_connections.get(str(user_id))
            if websocket:
                return await self._safe_send(websocket, message)
            return False
        except Exception as e:
            logger.error(f"Error sending to user {user_id}: {e}")
            return False
    
    async def broadcast_game_state(self, game_id: str):
        """Broadcast game state to all clients"""
        try:
            game_state = await GameManager.get_game_status(game_id)
            
            await self.broadcast_with_retry({
                'type': 'game_state',
                'game_id': game_id,
                'data': game_state,
                'timestamp': datetime.now().isoformat()
            })
        except Exception as e:
            logger.error(f"Error broadcasting game state: {e}")
    
    async def broadcast_number_called(self, game_id: str, number: int, called_numbers: list):
        """Broadcast number called update"""
        try:
            # Get BINGO letter
            letter = self._get_bingo_letter(number)
            
            await self.broadcast_with_retry({
                'type': 'number_called',
                'game_id': game_id,
                'data': {
                    'number': number,
                    'letter': letter,
                    'total_called': len(called_numbers),
                    'called_numbers': called_numbers[-10:],  # Last 10 numbers
                    'timestamp': datetime.now().isoformat()
                }
            })
        except Exception as e:
            logger.error(f"Error broadcasting number called: {e}")
    
    def _get_bingo_letter(self, number: int) -> str:
        """Get BINGO letter for a number"""
        if 1 <= number <= 15:
            return 'B'
        elif 16 <= number <= 30:
            return 'I'
        elif 31 <= number <= 45:
            return 'N'
        elif 46 <= number <= 60:
            return 'G'
        else:  # 61-75
            return 'O'
    
    async def broadcast_winner_announcement(self, game_id: str, winner_data: dict):
        """Broadcast winner announcement to all clients"""
        try:
            # 1. Winner announcement (shows for 5 seconds)
            await self.broadcast_with_retry({
                'type': 'winner_announcement',
                'game_id': game_id,
                'data': winner_data,
                'timestamp': datetime.now().isoformat()
            })
            
            # Wait 5 seconds for announcement
            await asyncio.sleep(5)
            
            # 2. Game winner screen (shows for 3 seconds)
            await self.broadcast_with_retry({
                'type': 'game_winner_screen',
                'game_id': game_id,
                'data': winner_data,
                'timestamp': datetime.now().isoformat()
            })
            
            # Wait 3 seconds for winner screen
            await asyncio.sleep(3)
            
            logger.info(f"✅ Winner announced for game {game_id}")
            
        except Exception as e:
            logger.error(f"Error broadcasting winner announcement: {e}")
    
    async def broadcast_new_game_starting(self, game_id: str, round_number: int, card_price: float):
        """Broadcast new game starting"""
        try:
            # 1. New game starting message
            await self.broadcast_with_retry({
                'type': 'new_game_starting',
                'game_id': game_id,
                'data': {
                    'message': '🎮 NEW GAME STARTING! Buy cards now!',
                    'card_price': card_price,
                    'round_number': round_number,
                    'prize_pool': 0,
                    'countdown': 30,
                    'timestamp': datetime.now().isoformat()
                }
            })
            
            # 2. Start 30-second countdown
            await self._broadcast_countdown(game_id, 30)
            
        except Exception as e:
            logger.error(f"Error broadcasting new game starting: {e}")
    
    async def _broadcast_countdown(self, game_id: str, duration: int):
        """Broadcast countdown updates"""
        try:
            # Countdown start
            await self.broadcast_with_retry({
                'type': 'countdown_start',
                'game_id': game_id,
                'data': {
                    'duration': duration,
                    'remaining': duration,
                    'message': '⏰ Next round starting soon!'
                }
            })
            
            # Countdown updates
            for seconds_left in range(duration, 0, -1):
                await self.broadcast_with_retry({
                    'type': 'countdown_update',
                    'game_id': game_id,
                    'data': {
                        'remaining': seconds_left,
                        'message': f'Next round in {seconds_left} seconds...'
                    }
                })
                await asyncio.sleep(1)
            
            # Countdown end
            await self.broadcast_with_retry({
                'type': 'countdown_end',
                'game_id': game_id,
                'data': {
                    'message': '🎮 GAME STARTING NOW!'
                }
            })
            
        except Exception as e:
            logger.error(f"Error broadcasting countdown: {e}")
    
    async def broadcast_balance_updates(self, game_id: str):
        """Broadcast balance updates to all players"""
        try:
            players = await Database.get_game_players(game_id)
            
            for player in players:
                await self.broadcast_with_retry({
                    'type': 'balance_update',
                    'game_id': game_id,
                    'data': {
                        'user_id': player['user_id'],
                        'username': player.get('username', f"User {player['user_id']}"),
                        'balance': player['balance'],
                        'cards_owned': player.get('cards_owned', 0),
                        'has_bingo': player.get('has_bingo', False)
                    }
                })
            
            logger.info(f"✅ Balance updates broadcasted for game {game_id}")
            
        except Exception as e:
            logger.error(f"Error broadcasting balance updates: {e}")
    
    async def broadcast_game_started(self, game_id: str, prize_pool: float, total_players: int):
        """Broadcast game started"""
        try:
            await self.broadcast_with_retry({
                'type': 'game_started',
                'game_id': game_id,
                'data': {
                    'message': '🎯 Game has started! Mark your cards!',
                    'prize_pool': prize_pool,
                    'total_players': total_players,
                    'timestamp': datetime.now().isoformat()
                }
            })
            
            logger.info(f"✅ Game {game_id} started broadcasted")
            
        except Exception as e:
            logger.error(f"Error broadcasting game started: {e}")
    
    async def start_keep_alive(self):
        """Start periodic ping to keep connections alive"""
        while not self._shutting_down:
            try:
                await asyncio.sleep(self._ping_interval)
                
                if not self._shutting_down and self.connections:
                    ping_message = {
                        'type': 'ping',
                        'timestamp': datetime.now().isoformat()
                    }
                    
                    for websocket in list(self.connections):
                        try:
                            await websocket.send(json.dumps(ping_message))
                        except:
                            pass  # Connection will be cleaned up in main loop
                            
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in keep-alive task: {e}")
                await asyncio.sleep(5)  # Wait before retrying

# Global WebSocket server instance
websocket_server = GameWebSocketServer()

async def start_websocket_server():
    """Start the WebSocket server with improved error handling"""
    max_retries = 5
    retry_delay = 2
    
    for attempt in range(max_retries):
        try:
            server = await serve(
                websocket_server.handle_connection,
                "localhost",
                WEBSOCKET_PORT,
                ping_interval=None,  # We handle our own ping
                ping_timeout=None,
                close_timeout=1,
                max_size=2**20,  # 1MB max message size
                max_queue=32
            )
            
            logger.info(f"✅ WebSocket server started on ws://localhost:{WEBSOCKET_PORT}")
            
            # Start background tasks
            websocket_server._keep_alive_task = asyncio.create_task(
                websocket_server.start_keep_alive()
            )
            asyncio.create_task(periodic_game_state_updates())
            
            # Keep server running
            await server.wait_closed()
            break
            
        except OSError as e:
            if attempt == max_retries - 1:
                logger.error(f"Failed to start WebSocket server after {max_retries} attempts: {e}")
                raise
            
            logger.warning(f"Failed to start WebSocket server (attempt {attempt + 1}/{max_retries}): {e}")
            await asyncio.sleep(retry_delay * (attempt + 1))
            
        except Exception as e:
            logger.error(f"Unexpected error starting WebSocket server: {e}")
            raise

async def periodic_game_state_updates():
    """Send periodic game state updates to all clients with error handling"""
    try:
        await asyncio.sleep(5)  # Wait for server to start
        
        while not websocket_server._shutting_down:
            try:
                # Get active game
                active_game = await GameManager.get_active_continuous_game()
                if active_game:
                    game_id = active_game['game_id']
                    
                    # Broadcast game state
                    await websocket_server.broadcast_game_state(game_id)
                    
                    # Broadcast balances every minute
                    current_minute = datetime.now().minute
                    if current_minute % 1 == 0:  # Every minute
                        await websocket_server.broadcast_balance_updates(game_id)
                
                await asyncio.sleep(10)  # Update every 10 seconds
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in periodic game state updates: {e}")
                await asyncio.sleep(30)  # Wait longer on error
                
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error(f"Periodic game state updates stopped: {e}")

async def broadcast(message: dict):
    """Global broadcast function for other modules"""
    await websocket_server.broadcast_with_retry(message)

async def broadcast_game_update(game_id: str, update_type: str, data: dict = None):
    """Global broadcast game update function"""
    return await websocket_server.broadcast_game_update(game_id, update_type, data)

async def cleanup_websocket_server():
    """Cleanup WebSocket server resources"""
    await websocket_server.cleanup()

# Admin functions with improved error handling
async def admin_start_game(game_id: str):
    """Admin function to start a game"""
    try:
        await GameManager.start_continuous_game_numbers(game_id)
        logger.info(f"Admin started game {game_id}")
        return True
    except Exception as e:
        logger.error(f"Error starting game {game_id}: {e}")
        return False

async def admin_stop_game(game_id: str):
    """Admin function to stop a game"""
    try:
        await GameManager.stop_continuous_game(game_id)
        logger.info(f"Admin stopped game {game_id}")
        return True
    except Exception as e:
        logger.error(f"Error stopping game {game_id}: {e}")
        return False

async def admin_broadcast_message(game_id: str, message: str, message_type: str = "admin_message"):
    """Admin function to broadcast a message"""
    try:
        await websocket_server.broadcast_with_retry({
            'type': message_type,
            'game_id': game_id,
            'data': {
                'message': message,
                'timestamp': datetime.now().isoformat()
            }
        })
        logger.info(f"Admin broadcast: {message}")
        return True
    except Exception as e:
        logger.error(f"Error broadcasting admin message: {e}")
        return False

async def admin_send_to_user(user_id: str, message: str):
    """Admin function to send message to specific user"""
    try:
        success = await websocket_server.send_to_user(user_id, {
            'type': 'admin_message',
            'data': {
                'message': message,
                'timestamp': datetime.now().isoformat()
            }
        })
        
        if success:
            logger.info(f"Admin message sent to user {user_id}: {message}")
        else:
            logger.warning(f"Admin message failed to send to user {user_id}")
            
        return success
    except Exception as e:
        logger.error(f"Error sending admin message to user {user_id}: {e}")
        return False

async def admin_call_number(game_id: str, number: int):
    """Admin function to manually call a number"""
    try:
        game = await Database.get_game(game_id)
        if not game:
            logger.error(f"Game {game_id} not found")
            return False
        
        # Get current called numbers
        called_numbers = []
        if game.get('numbers_called'):
            try:
                called_numbers = json.loads(game['numbers_called'])
            except:
                pass
        
        # Add number
        if number not in called_numbers:
            called_numbers.append(number)
        
        # Update database
        await Database.update_current_number(game_id, number)
        await Database.update_numbers_called(game_id, called_numbers)
        
        # Broadcast to all players
        await websocket_server.broadcast_number_called(game_id, number, called_numbers)
        
        logger.info(f"Admin called number {number} for game {game_id}")
        return True
        
    except Exception as e:
        logger.error(f"Error in admin_call_number: {e}")
        return False

async def admin_end_game_and_restart(game_id: str):
    """Admin function to end current game and restart immediately"""
    try:
        # Get any winner (or simulate if none)
        winners = await Database.get_current_round_winners(game_id)
        
        if winners:
            winner = winners[0]
            winner_data = {
                'user_id': winner['user_id'],
                'username': winner.get('username', f"User {winner['user_id']}"),
                'card_id': winner['id'],
                'card_index': winner.get('card_index', 'N/A')
            }
        else:
            # Simulate a winner for restart
            winner_data = {
                'user_id': 0,
                'username': 'System',
                'card_id': 0,
                'card_index': 0
            }
        
        # Trigger game restart
        await GameManager.end_game_and_restart(game_id, winner_data)
        
        logger.info(f"Admin ended and restarted game {game_id}")
        return True
        
    except Exception as e:
        logger.error(f"Error in admin_end_game_and_restart: {e}")
        return False

async def admin_get_game_stats(game_id: str):
    """Admin function to get game statistics"""
    try:
        stats = await Database.get_game_statistics(game_id)
        return stats
    except Exception as e:
        logger.error(f"Error getting game stats: {e}")
        return {}

# Connection management utilities
async def get_connection_stats():
    """Get WebSocket connection statistics"""
    return {
        'total_connections': len(websocket_server.connections),
        'authenticated_users': len(websocket_server.user_connections),
        'active_games': len(websocket_server.active_games)
    }

async def disconnect_user(user_id: str):
    """Disconnect a specific user"""
    try:
        websocket = websocket_server.user_connections.get(str(user_id))
        if websocket:
            await websocket.close(code=1000, reason="Admin disconnect")
            return True
        return False
    except Exception as e:
        logger.error(f"Error disconnecting user {user_id}: {e}")
        return False

async def broadcast_to_game(game_id: str, message: dict):
    """Broadcast message to users in a specific game"""
    try:
        # Get all players in the game
        players = await Database.get_game_players(game_id)
        success_count = 0
        
        for player in players:
            if await websocket_server.send_to_user(str(player['user_id']), message):
                success_count += 1
        
        logger.info(f"Broadcast to game {game_id}: {success_count}/{len(players)} successful")
        return success_count
    except Exception as e:
        logger.error(f"Error broadcasting to game {game_id}: {e}")
        return 0