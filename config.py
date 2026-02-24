import os
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# ========================
# Bot Configuration
# ========================
BOT_TOKEN = os.getenv("BOT_TOKEN")  # Must be set in your .env
ADMIN_IDS = [
    int(id.strip()) for id in os.getenv("ADMIN_IDS", "").split(",") if id.strip()
]

# ========================
# Game Configuration
# ========================
GAME_CONFIG = {
    "card_price": float(os.getenv("CARD_PRICE", 10.0)),
    "min_deposit": float(os.getenv("MIN_DEPOSIT", 10.0)),
    "min_withdrawal": float(os.getenv("MIN_WITHDRAWAL", 100.0)),
    "house_fee_percent": int(os.getenv("HOUSE_FEE_PERCENT", 20)),
    "prize_pool_percent": int(os.getenv("PRIZE_POOL_PERCENT", 80)),
    "countdown_duration": int(os.getenv("COUNTDOWN_DURATION", 30)),
    "max_players": int(os.getenv("MAX_PLAYERS", 400)),
    "numbers_range": (1, 75),
    "card_rows": 5,
    "card_cols": 5,
    "prize_distribution": [100],      # 100% to first winner
    "number_call_interval": 3,        # seconds between numbers
    "max_numbers": 75,
    "free_space_position": 12,        # Center of 5x5 grid (0-indexed)
    'telebirr_api_key': os.getenv('TELEBIRR_API_KEY', ''),
    'cbebirr_api_key': os.getenv('CBE_BIRR_API_KEY', ''),
}

# ========================
# Database Configuration (SQLite)
# ========================
DB_CONFIG = {
    "type": "sqlite",
    "path": os.getenv("DB_PATH", "habesha_bingo.db"),  # SQLite DB file
}

# ========================
# Payment Configuration
# ========================
PAYMENT_CONFIG = {
    "providers": ["TeleBirr", "Chapa", "CBE"],
    "telebirr_number": os.getenv("TELEBIRR_NUMBER", "+251900000000"),
    "cbe_account": os.getenv("CBE_ACCOUNT", "1000 2345 6789"),
}

# ========================
# Card System Configuration
# ========================
CARD_SYSTEM_CONFIG = {
    "total_cards": 400,
    "cards_per_game": 400,
    "card_validation": True,
    "preview_enabled": True,
}

# ========================
# Currency
# ========================
CURRENCY = "birr"
CURRENCY_SYMBOL = "birr"

# ========================
# Web server configuration
# ========================
WEBSERVER_HOST = "0.0.0.0"        # Listen on all interfaces in Docker/VPS
WEBSERVER_PORT = int(os.getenv("WEBSERVER_PORT", 80))
WEBSOCKET_PORT = int(os.getenv("WEBSOCKET_PORT", 8765))

# ========================
# Web App (Mini App) configuration
# ========================
WEB_APP_TITLE = "Habesha Bingo"
WEB_APP_DESCRIPTION = "Real-time Bingo Game"



# Use your **public VPS URL** (replace with your domain or VPS IP + HTTPS)
WEB_APP_URL = os.getenv(
    "WEB_APP_URL",
    "https://habeshabingoclean-production.up.railway.app"
)

# Admin panel URL
WEB_APP_ADMIN_URL = os.getenv(
    "WEB_APP_ADMIN_URL",
    "https://habeshabingoclean-production.up.railway.app/admin.html"
)

# Remove NGROK_HTTPS_URL if it exists, or set it to None
NGROK_HTTPS_URL = None  # Add this to explicitly disable ngrok