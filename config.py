# config.py
import os

# Telegram Bot Configuration
BOT_TOKEN = os.getenv('BOT_TOKEN', 'YOUR_BOT_TOKEN_HERE')

# Web Server Configuration
WEBSERVER_HOST = os.getenv('WEBSERVER_HOST', '0.0.0.0')
WEBSERVER_PORT = int(os.getenv('WEBSERVER_PORT', '8001'))
WEB_APP_URL = os.getenv('WEB_APP_URL', None)

# Admin IDs (Optional - for basic deposit approval)
ADMIN_IDS = []  # Add admin user IDs if needed

# Game Configuration
GAME_CONFIG = {
    'currency': 'birr',
    'card_price': 10.00,
    'telebirr_api_key': os.getenv('TELEBIRR_API_KEY', ''),  # Read from env
    'cbebirr_api_key': '',
}