# web_server.py - Simplified version
# Only: User registration support, Deposit verification, Balance check
# All admin endpoints removed

from aiohttp import web
import json
import logging
import asyncio
import os
import random
import decimal
from datetime import datetime, date
from typing import Set, Dict
import sys
from database.db import Database

logger = logging.getLogger(__name__)

# Configuration
WEBSERVER_HOST = os.getenv('WEBSERVER_HOST', '0.0.0.0')
WEBSERVER_PORT = int(os.getenv('WEBSERVER_PORT', '8001'))
WEB_APP_URL = f"http://{WEBSERVER_HOST}:{WEBSERVER_PORT}"

# Fix for Windows socket issues
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


# ==================== GLOBAL BOT REFERENCE ====================
bot_instance = None

def set_bot_instance(bot):
    """Set the global bot instance for notifications"""
    global bot_instance
    bot_instance = bot
    logger.info("✅ Bot instance registered with web_server")


# ==================== THREAD-SAFE NOTIFICATION QUEUE ====================
import queue
import threading

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
        logger.info("📨 Notification queue processor thread started")
        
        while self._running:
            try:
                notification = self.queue.get(timeout=1)
                user_id = notification['user_id']
                message = notification['message']
                
                logger.info(f"📤 Processing queued notification for user {user_id}")
                
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
                    result = future.result(timeout=30)
                    logger.info(f"✅ Queued notification sent to user {user_id}")
                except TimeoutError:
                    logger.error(f"❌ Timeout sending queued notification to user {user_id}")
                except Exception as e:
                    logger.error(f"❌ Error sending queued notification: {e}")
                    
            except queue.Empty:
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
    return notification_queue.add_notification(user_id, message)


# ==================== WEBSOCKET SERVER (SIMPLIFIED) ====================
class SimpleWebSocketServer:
    def __init__(self):
        self.connections: Set[web.WebSocketResponse] = set()
        self.user_connections: Dict[str, web.WebSocketResponse] = {}
        self._shutting_down = False
        
    async def cleanup(self):
        """Cleanup resources on shutdown"""
        self._shutting_down = True
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
            await self._safe_send_async(ws, {
                'type': 'welcome',
                'message': 'Connected to Haset Bingo Server',
                'timestamp': datetime.now().isoformat(),
                'connection_id': connection_id
            })
            
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
                        logger.error(f"Error processing message: {e}")
                elif msg.type == web.WSMsgType.ERROR:
                    logger.error(f"WebSocket error: {ws.exception()}")
                    break
                    
        except asyncio.CancelledError:
            logger.debug(f"WebSocket connection {connection_id} cancelled")
        except ConnectionResetError:
            logger.debug(f"Connection reset for {connection_id}")
        except Exception as e:
            logger.error(f"WebSocket connection error: {e}")
        finally:
            self.connections.discard(ws)
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
            elif msg_type == 'ping':
                await self._handle_ping(ws)
            else:
                logger.debug(f"Unknown message type from {connection_id}: {msg_type}")
                
        except Exception as e:
            logger.error(f"Error handling message type {msg_type}: {e}")
    
    async def _handle_auth(self, ws: web.WebSocketResponse, data: dict, connection_id: str):
        """Handle authentication"""
        user_id = data.get('userId')
        if user_id:
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
            logger.info(f"User {user_id} authenticated via WebSocket")
    
    async def _handle_ping(self, ws: web.WebSocketResponse):
        """Handle ping request"""
        await self._safe_send_async(ws, {
            'type': 'pong',
            'timestamp': datetime.now().isoformat()
        })
    
    async def _safe_send_async(self, ws: web.WebSocketResponse, message: dict) -> bool:
        """Safely send message"""
        try:
            if ws.closed:
                return False
            message_json = json.dumps(self.convert_to_json_serializable(message))
            await ws.send_str(message_json)
            return True
        except Exception as e:
            logger.debug(f"Error sending message: {e}")
            return False
    
    async def broadcast_with_retry(self, message: dict, max_retries: int = 3):
        """Broadcast message to all connections"""
        if not self.connections:
            return True
    
        try:
            message_json = json.dumps(self.convert_to_json_serializable(message))
        except Exception as e:
            logger.error(f"Error converting message to JSON: {e}")
            return False
    
        async def send_to_one(ws):
            try:
                if not ws.closed:
                    await ws.send_str(message_json)
                    return None
                return ws
            except Exception as e:
                logger.debug(f"Individual send error: {e}")
                return ws

        tasks = [send_to_one(ws) for ws in list(self.connections)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
    
        disconnected = {res for res in results if res is not None}
    
        if disconnected:
            for ws in disconnected:
                if hasattr(ws, 'closed'):
                    self.connections.discard(ws)
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
        else:
            return obj


# Create global WebSocket server instance
websocket_server = SimpleWebSocketServer()


# ==================== CUSTOM JSON ENCODER ====================
class CustomJSONEncoder(json.JSONEncoder):
    """Custom JSON encoder that handles Decimal and Datetime objects"""
    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        if isinstance(obj, decimal.Decimal):
            return float(obj)
        return super(CustomJSONEncoder, self).default(obj)


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
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, *'
    response.headers['Access-Control-Allow-Credentials'] = 'true'
    response.headers['Access-Control-Max-Age'] = '86400'
    
    return response


# Create routes
routes = web.RouteTableDef()


# ==================== SIMPLE API ENDPOINTS ====================

@routes.get('/health')
async def health_check(request):
    """Health check endpoint"""
    return web.json_response({
        'status': 'healthy',
        'service': 'haset-bingo-server',
        'timestamp': datetime.now().isoformat()
    })


@routes.get('/api/user/balance/{user_id}')
async def get_user_balance(request):
    """Get user balance"""
    try:
        user_id_str = request.match_info['user_id']
        user_id = parse_user_id(user_id_str)
        
        user = await Database.get_user(user_id)
        
        if not user:
            await Database.create_user(
                user_id=user_id,
                username=f"User_{user_id}",
                full_name=f"User {user_id}"
            )
            user = await Database.get_user(user_id)
        
        if user:
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
                'balance': 10.00,
                'currency': 'birr'
            })
                
    except Exception as e:
        logger.error(f"Error getting balance: {e}")
        return web.json_response({
            'success': True,
            'balance': 10.00,
            'currency': 'birr',
            'user_id': 0,
            'username': 'Test User',
            'message': 'Using default balance'
        })


@routes.post('/api/user/deposit')
async def deposit_notification(request):
    """Notify user about deposit status (for webhook use)"""
    try:
        data = await request.json()
        user_id = data.get('user_id')
        amount = data.get('amount')
        status = data.get('status')
        payment_id = data.get('payment_id')
        
        if not user_id or not amount:
            return web.json_response({
                'success': False,
                'message': 'user_id and amount are required'
            }, status=400)
        
        user_id = parse_user_id(str(user_id))
        
        if status == 'approved':
            message = (
                f"✅ *የገንዘብ ክፍያ ፈቅዷል!*\n\n"
                f"*💰 መጠን:* {amount:.2f} birr\n"
                f"*📋 የፒሜንት መታወቂያ:* {payment_id or 'N/A'}\n\n"
                f"🎉 እንኳን ደስ አሎት! ገንዘብዎ በቀሪ ሒሳብዎ ላይ ታክሏል።\n"
                f"💰 ቀሪ ሒሳብ ለማየት: /balance"
            )
        else:
            message = (
                f"❌ *የገንዘብ ክፍያ ተቀብሏል*\n\n"
                f"*💰 መጠን:* {amount:.2f} birr\n"
                f"*📋 የፒሜንት መታወቂያ:* {payment_id or 'N/A'}\n\n"
                f"⚠️ የገንዘብ ክፍያ ጥያቄዎ ተቀብሏል።\n"
                f"🔄 እባክዎ እውነተኛ የቴሌብር ማረጋገጫ SMS ይላኩ።"
            )
        
        await send_notification_to_user(user_id, message)
        
        return web.json_response({
            'success': True,
            'message': 'Notification sent'
        })
        
    except Exception as e:
        logger.error(f"Error sending deposit notification: {e}")
        return web.json_response({
            'success': False,
            'message': str(e)
        }, status=500)


# ==================== WEBSOCKET HANDLER ====================
@routes.get('/ws')
async def websocket_handler(request):
    """WebSocket handler"""
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    await websocket_server.handle_connection(ws)
    return ws


# ==================== SIMPLE HTML PAGES ====================
@routes.get('/')
async def home(request):
    """Home page"""
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>🎮 Haset Bingo Server</title>
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
            .status {
                background: #d4edda;
                color: #155724;
                padding: 10px;
                border-radius: 5px;
                margin: 20px 0;
            }
            .commands {
                background: #e7f3ff;
                padding: 15px;
                border-radius: 5px;
                margin: 20px 0;
            }
            .commands h3 {
                margin-top: 0;
                color: #2c3e50;
            }
            .commands ul {
                margin-bottom: 0;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🎮 Haset Bingo Server</h1>
            <div class="status">
                ✅ Server is running successfully!
            </div>
            <p>Welcome to Haset Bingo Bot. Use the Telegram bot to:</p>
            <div class="commands">
                <h3>📋 Available Commands:</h3>
                <ul>
                    <li><strong>/start</strong> - Register and see menu</li>
                    <li><strong>/balance</strong> - Check your balance</li>
                    <li><strong>/deposit</strong> - Deposit money with SMS verification</li>
                    <li><strong>/instructions</strong> - View instructions</li>
                    <li><strong>/support</strong> - Get support</li>
                </ul>
            </div>
            <div class="status">
                🔗 WebSocket endpoint: <code>ws://{WEBSERVER_HOST}:{WEBSERVER_PORT}/ws</code>
            </div>
        </div>
    </body>
    </html>
    """
    return web.Response(text=html_content, content_type='text/html')


@routes.get('/game.html')
async def game_html(request):
    """Serve game HTML page"""
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Haset Bingo - Game</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {
                font-family: Arial, sans-serif;
                margin: 0;
                padding: 20px;
                background-color: #f0f0f0;
            }
            .container {
                max-width: 600px;
                margin: 0 auto;
                background: white;
                padding: 20px;
                border-radius: 10px;
                text-align: center;
            }
            h1 { color: #2c3e50; }
            .info {
                background: #e8f4f8;
                padding: 10px;
                border-radius: 5px;
                margin: 10px 0;
            }
            .message {
                background: #d4edda;
                color: #155724;
                padding: 10px;
                border-radius: 5px;
                margin: 10px 0;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🎮 Haset Bingo</h1>
            <div class="info">
                <p>📱 To play, open the Telegram bot and use:</p>
                <p><strong>/play</strong> - Start playing</p>
                <p><strong>/balance</strong> - Check balance</p>
                <p><strong>/deposit</strong> - Add funds</p>
            </div>
            <div class="message">
                ✅ Game is ready! Open Telegram to start playing.
            </div>
        </div>
    </body>
    </html>
    """
    return web.Response(text=html_content, content_type='text/html')


# ==================== MAIN APPLICATION SETUP ====================
app = web.Application(middlewares=[cors_middleware])
app.add_routes(routes)

if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('web_server.log')
        ]
    )
    
    logger.info(f"Starting Haset Bingo Web Server on {WEBSERVER_HOST}:{WEBSERVER_PORT}")
    logger.info(f"Web App URL: {WEB_APP_URL}")
    
    web.run_app(app, host=WEBSERVER_HOST, port=WEBSERVER_PORT)


# ==================== SERVER START FUNCTION ====================
async def run_server():
    """Run the web server - main entry point"""
    app = web.Application(middlewares=[cors_middleware])
    app.add_routes(routes)
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    site = web.TCPSite(runner, WEBSERVER_HOST, WEBSERVER_PORT)
    await site.start()
    
    logger.info(f"✅ Web server started on http://{WEBSERVER_HOST}:{WEBSERVER_PORT}")
    logger.info(f"✅ WebSocket server ready on ws://{WEBSERVER_HOST}:{WEBSERVER_PORT}/ws")
    logger.info("Press Ctrl+C to stop the server")
    
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        logger.info("Server shutdown requested")
    finally:
        await runner.cleanup()
        await websocket_server.cleanup()


# Function name that the bot expects
start_web_server = run_server