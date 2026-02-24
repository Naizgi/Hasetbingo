import requests
import logging

logger = logging.getLogger(__name__)

def get_ngrok_url():
    """Get the current ngrok HTTPS URL"""
    try:
        response = requests.get("http://localhost:4040/api/tunnels")
        data = response.json()
        
        for tunnel in data['tunnels']:
            if tunnel['proto'] == 'https':
                return tunnel['public_url']
        
        return None
    except:
        return None

async def get_webapp_url():
    """Get the Web App URL, using ngrok if available"""
    from config import WEBSERVER_HOST, WEBSERVER_PORT
    
    # Try to get ngrok URL first
    ngrok_url = get_ngrok_url()
    if ngrok_url:
        logger.info(f"✅ Using ngrok URL: {ngrok_url}")
        return ngrok_url + "/game.html"
    
    # Fallback to local URL (for development only)
    local_url = f"http://{WEBSERVER_HOST}:{WEBSERVER_PORT}/game.html"
    logger.warning(f"⚠️  Using local URL (Telegram may reject HTTP): {local_url}")
    return local_url