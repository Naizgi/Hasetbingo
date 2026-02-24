# web_server_runner.py
import asyncio
import threading
import logging
import sys
from web_server import run_server

logger = logging.getLogger(__name__)

class WebServerRunner:
    def __init__(self):
        self.server_thread = None
        self.loop = None
        self.running = False
    
    def start(self):
        """Start the web server in a separate thread"""
        if self.running:
            logger.warning("Web server is already running")
            return
        
        logger.info("Starting web server in background thread...")
        
        def run_in_thread():
            """Run the web server in its own event loop"""
            try:
                # Create a new event loop for this thread
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                logger.info("Web server event loop created")
                
                # Run the server
                loop.run_until_complete(run_server())
                
            except Exception as e:
                logger.error(f"Web server error: {e}", exc_info=True)
            finally:
                logger.info("Web server thread finished")
        
        # Start the thread
        self.server_thread = threading.Thread(target=run_in_thread, daemon=True)
        self.server_thread.start()
        self.running = True
        
        logger.info("✅ Web server started in background thread")
        return self.server_thread
    
    def stop(self):
        """Stop the web server"""
        if not self.running:
            return
        
        logger.info("Stopping web server...")
        # The thread is daemon=True, so it will exit when main program exits
        self.running = False
        logger.info("Web server marked for shutdown")

# Global instance
web_server_runner = WebServerRunner()

def start_web_server():
    """Simple function to start the web server - matches what bot expects"""
    return web_server_runner.start()