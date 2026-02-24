import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from utils.game_manager import GameManager
from utils.bingo_utils import BingoUtils
from utils.card_generator import CardGenerator
from database.db import Database
from config import ADMIN_IDS, GAME_CONFIG  # ADDED GAME_CONFIG import
import json
import html

logger = logging.getLogger(__name__)

# Create the router
router = Router()

# Helper function to escape HTML characters
def escape_html(text):
    """Escape special HTML characters"""
    if not isinstance(text, str):
        return str(text)
    return html.escape(text)

def safe_format(text):
    """Safely format text for HTML parsing"""
    return escape_html(text)

# Get card price from config
CARD_PRICE = GAME_CONFIG.get('card_price', 10.00)  # ADDED: Get price from config
CURRENCY = "birr"  # ADDED: Currency symbol

# HTML Templates
GAME_HEADER_TEMPLATE = """
🎮 <b>{status_emoji} HABESHA BINGO {status_text}</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

# UPDATE THIS TEMPLATE - CHANGE $ TO birr
GAME_INFO_TEMPLATE = """
🎲 <b>Game ID:</b> <code>#{game_id}</code>
👥 <b>Players:</b> {players_count}
💰 <b>Prize Pool:</b> <code>{prize_pool} {currency}</code>  # CHANGED
"""

COUNTDOWN_TEMPLATE = """
⏱️ <b>Countdown:</b> <code>{countdown}s</code> ⏳
"""

ACTIVE_GAME_TEMPLATE = """
🔢 <b>Current Number:</b> <code>{current_number}</code>
📊 <b>Numbers Called:</b> {numbers_called}/75
"""

WINNERS_TEMPLATE = """
🏆 <b>Winners:</b>
{winners_list}
"""

USER_CARD_STATUS = """
✅ <b>You have a card in this game!</b>
🎫 <b>Your Card:</b> #{card_index}
"""

NO_CARD_STATUS = """
🛒 <b>Ready to join?</b> Buy your first card!
"""

# Helper function to format bingo card with HTML styling
def format_card_display_html(card_data, is_winner=False):
    """Format card data with beautiful HTML styling"""
    if not card_data:
        return "<i>No card data available</i>"
    
    try:
        if isinstance(card_data, str):
            numbers = json.loads(card_data)
        else:
            numbers = card_data
        
        # Card header with BINGO letters
        card_header = """
<b>┌───────── B ───────── I ───────── N ───────── G ───────── O ────────┐</b>
"""
        
        # Card rows with styling
        rows = []
        for i in range(0, 25, 5):
            row = numbers[i:i+5]
            formatted_row = []
            
            for j, num in enumerate(row):
                cell_idx = i + j
                
                # Center is FREE with special styling
                if cell_idx == 12:
                    cell = "🎁<b>FREE</b>"
                else:
                    # Format number with padding
                    num_str = f"{num:>2}"
                    # Add emoji for different ranges
                    if 1 <= num <= 15:
                        cell = f"🔵{num_str}"  # Blue for B column
                    elif 16 <= num <= 30:
                        cell = f"🟢{num_str}"  # Green for I column
                    elif 31 <= num <= 45:
                        cell = f"🟡{num_str}"  # Yellow for N column
                    elif 46 <= num <= 60:
                        cell = f"🟠{num_str}"  # Orange for G column
                    elif 61 <= num <= 75:
                        cell = f"🔴{num_str}"  # Red for O column
                    else:
                        cell = f"⚫{num_str}"  # Black for invalid
                
                formatted_row.append(cell)
            
            # Join row with spacing
            row_str = " │ ".join(formatted_row)
            rows.append(f"<b>│</b> {row_str} <b>│</b>")
        
        # Card footer
        card_footer = """
<b>└───────────────────────────────────────────────────────────────────┘</b>
"""
        
        # Combine all parts
        card_lines = [card_header] + rows + [card_footer]
        
        # Add card legend
        legend = """
<code>🎲 B(1-15) 🎯 I(16-30) ⭐ N(31-45) 🏆 G(46-60) 🎪 O(61-75)</code>
"""
        
        return "\n".join(card_lines) + legend
        
    except Exception as e:
        logger.error(f"Error formatting card: {e}")
        return "<i>Error displaying card</i>"

# Helper function to format game status with emojis
def get_game_status_emoji(status):
    """Get emoji for game status"""
    status_emojis = {
        'waiting': '🟡',
        'starting': '🔴',
        'active': '🟢',
        'finished': '✅',
        'cancelled': '❌'
    }
    return status_emojis.get(status, '⚪')

def get_game_status_text(status):
    """Get formatted text for game status"""
    status_texts = {
        'waiting': 'WAITING FOR PLAYERS',
        'starting': 'STARTING SOON',
        'active': 'GAME IN PROGRESS',
        'finished': 'GAME FINISHED',
        'cancelled': 'GAME CANCELLED'
    }
    return status_texts.get(status, status.upper())

# Command handlers with enhanced HTML styling
@router.message(Command("start"))
async def cmd_start(message: Message):
    """Start command handler with beautiful styling"""
    # Register/update user
    user_id = message.from_user.id
    username = message.from_user.username or ""
    full_name = message.from_user.full_name
    
    await Database.create_user(user_id, username, full_name)
    
    # Create beautiful keyboard
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎮 Join Game", callback_data="join_current_game"),
            InlineKeyboardButton(text="ℹ️ Game Info", callback_data="game_info")
        ],
        [
            InlineKeyboardButton(text="🃏 My Cards", callback_data="my_cards"),
            InlineKeyboardButton(text="💰 Balance", callback_data="balance_info")
        ],
        [
            InlineKeyboardButton(text="🎯 How to Play", callback_data="how_to_play"),
            InlineKeyboardButton(text="⭐️ Buy Card", callback_data="buy_card_direct")
        ]
    ])
    
    # UPDATE WELCOME TEXT - CHANGE PRICE TO 10 birr
    welcome_text = f"""
🎉 <b>WELCOME TO HABESHA BINGO!</b> 🎉

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🌟 <b>Your Ultimate Bingo Experience</b>
• 🎰 400 Unique Pre-generated Cards
• 🏆 Fair & Transparent Gameplay
• 💰 Instant Prize Distribution
• 🎯 Real-time Number Calling

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

<b>🚀 QUICK ACTIONS:</b>
• /start - Show this menu
• /game - View current game
• /buy - Buy bingo card ({CARD_PRICE:.0f} {CURRENCY})  # CHANGED
• /cards - Your bingo cards
• /balance - Check balance

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

<b>🎮 READY TO PLAY?</b>
Tap the buttons below to get started!
"""
    
    await message.answer(
        welcome_text,
        reply_markup=keyboard,
        parse_mode="HTML"
    )

@router.message(Command("game"))
async def cmd_game(message: Message):
    """Show current game information with beautiful styling"""
    game_info = await GameManager.get_active_game_info()
    
    if not game_info:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🆕 Create Game", callback_data="create_game"),
                InlineKeyboardButton(text="🔄 Refresh", callback_data="refresh_games")
            ]
        ])
        
        no_game_text = """
📭 <b>NO ACTIVE GAMES</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

😔 No active bingo games at the moment.

✨ <b>What's next?</b>
• Check back soon for new games
• Create your own game (admins)
• A game starts automatically when players join

🏆 <b>Be the first to join next game!</b>
"""
        
        await message.answer(
            no_game_text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        return
    
    # Get formatted status
    game_id = game_info['game_id']
    status = game_info['status']
    status_emoji = get_game_status_emoji(status)
    status_text = get_game_status_text(status)
    
    # Build response with beautiful formatting
    response_parts = []
    
    # Header
    response_parts.append(GAME_HEADER_TEMPLATE.format(
        status_emoji=status_emoji,
        status_text=status_text
    ))
    
    # Game Info - CHANGED: Use birr instead of $
    response_parts.append(GAME_INFO_TEMPLATE.format(
        game_id=safe_format(game_id[:8]),
        players_count=safe_format(game_info.get('players', 0)),
        prize_pool=safe_format(f"{game_info.get('prize_pool', 0):.0f}"),  # CHANGED: Remove $, use 0 decimal
        currency=CURRENCY  # ADDED
    ))
    
    # Status-specific info
    if status == 'starting':
        countdown = game_info.get('countdown', 0)
        response_parts.append(COUNTDOWN_TEMPLATE.format(
            countdown=safe_format(countdown)
        ))
        
        # Progress bar for countdown
        progress = min(100, int((countdown / 60) * 100))
        progress_bar = "━" * (progress // 10) + "○" + "─" * (10 - (progress // 10))
        response_parts.append(f"📈 <b>Progress:</b> <code>[{progress_bar}] {progress}%</code>")
        
    elif status == 'active':
        response_parts.append(ACTIVE_GAME_TEMPLATE.format(
            current_number=safe_format(game_info.get('current_number', 'N/A')),
            numbers_called=safe_format(game_info.get('numbers_called', 0))
        ))
        
        # Progress bar for numbers called
        numbers_called = game_info.get('numbers_called', 0)
        progress = int((numbers_called / 75) * 100)
        progress_bar = "▓" * (progress // 10) + "░" * (10 - (progress // 10))
        response_parts.append(f"📈 <b>Progress:</b> <code>[{progress_bar}] {progress}%</code>")
        
        if game_info.get('winners'):
            winners_lines = []
            for i, w in enumerate(game_info['winners'][:3]):
                medal = ["🥇", "🥈", "🥉"][i] if i < 3 else "🏅"
                user_id_safe = safe_format(w['user_id'])
                prize_formatted = f"{w['prize']:.0f}"  # CHANGED: 0 decimal for birr
                prize_safe = safe_format(prize_formatted)
                winners_lines.append(f"{medal} <b>User {user_id_safe}:</b> <code>{prize_safe} {CURRENCY}</code>")  # CHANGED
            
            winners_text = "\n".join(winners_lines)
            response_parts.append(WINNERS_TEMPLATE.format(winners_list=winners_text))
    
    # Check if user has a card
    user_id = message.from_user.id
    user_cards = await Database.get_user_cards(user_id, game_id)
    
    if user_cards:
        # User has cards
        card = user_cards[0]
        response_parts.append(USER_CARD_STATUS.format(
            card_index=safe_format(card['card_index'])
        ))
        
        if card['has_bingo']:
            prize_won = card.get('prize_won', 0)
            response_parts.append(f"🎊 <b>CONGRATULATIONS!</b> You won <code>{prize_won:.0f} {CURRENCY}</code>")  # CHANGED
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="👁️ View Card", callback_data=f"view_card_{game_id}"),
                InlineKeyboardButton(text="📊 Game Stats", callback_data=f"refresh_{game_id}")
            ],
            [
                InlineKeyboardButton(text="⭐ Buy Another", callback_data=f"buy_card_{game_id}"),
                InlineKeyboardButton(text="🔄 Refresh", callback_data=f"refresh_{game_id}")
            ]
        ])
    else:
        # User doesn't have a card
        response_parts.append(NO_CARD_STATUS)
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                # CHANGED: Button text to show 10 birr
                InlineKeyboardButton(text=f"🎫 Buy Card ({CARD_PRICE:.0f} {CURRENCY})", callback_data=f"buy_card_{game_id}"),
                InlineKeyboardButton(text="📊 Game Info", callback_data=f"refresh_{game_id}")
            ],
            [
                InlineKeyboardButton(text="ℹ️ How to Play", callback_data="how_to_play"),
                InlineKeyboardButton(text="🔄 Refresh", callback_data=f"refresh_{game_id}")
            ]
        ])
    
    # Footer
    response_parts.append(f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
<b>🎯 TIP:</b> The more players, the bigger the prize pool!
<b>💰 Card Price:</b> <code>{CARD_PRICE:.0f} {CURRENCY}</code>  # ADDED
    """)
    
    response = "\n".join(response_parts)
    
    await message.answer(
        response,
        reply_markup=keyboard,
        parse_mode="HTML"
    )

@router.message(Command("buy"))
async def cmd_buy(message: Message):
    """Buy a bingo card with beautiful styling"""
    game_info = await GameManager.get_active_game_info()
    
    if not game_info:
        await message.answer(
            """
❌ <b>NO ACTIVE GAME</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Sorry, there's no active game to join right now.

Please check back soon or use <code>/game</code> to see game status.
            """,
            parse_mode="HTML"
        )
        return
    
    if game_info['status'] not in ['waiting', 'starting']:
        status_title = game_info['status'].title()
        status_safe = safe_format(status_title)
        
        await message.answer(
            f"""
⛔ <b>CANNOT JOIN GAME</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Game Status: <code>{status_safe}</code>

You can only join games that are:
✅ <b>Waiting for players</b>
✅ <b>Starting soon</b>

Current game is already in progress or finished.
            """,
            parse_mode="HTML"
        )
        return
    
    # Beautiful purchase confirmation
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Confirm Purchase", callback_data=f"confirm_buy_{game_info['game_id']}"),
            InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_buy")
        ]
    ])
    
    # UPDATE PURCHASE TEXT - CHANGE TO 10 birr
    purchase_text = f"""
🛒 <b>PURCHASE BINGO CARD</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🎮 <b>Game Info:</b>
• 🆔 Game ID: <code>#{safe_format(game_info['game_id'][:8])}</code>
• 👥 Players: <code>{safe_format(game_info.get('players', 0))}</code>
• 💰 Prize Pool: <code>{safe_format(f"{game_info.get('prize_pool', 0):.0f}")} {CURRENCY}</code>  # CHANGED

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

💵 <b>Price:</b> <code>{CARD_PRICE:.0f} {CURRENCY}</code> per card  # CHANGED

🎯 <b>Features:</b>
• 🎰 400 unique pre-generated cards
• 👁️ Card preview before purchase
• ⚖️ Fair and transparent system
• 🏆 {GAME_CONFIG.get('prize_pool_percentage', 0.80)*100:.0f}% of sales go to prize pool ({CARD_PRICE * GAME_CONFIG.get('prize_pool_percentage', 0.80):.0f} {CURRENCY})  # CHANGED
• ⚡ Instant card delivery

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

<b>Click below to purchase your card:</b>
"""
    
    await message.answer(
        purchase_text,
        reply_markup=keyboard,
        parse_mode="HTML"
    )

# Enhanced card display callback
@router.callback_query(F.data.startswith("confirm_buy_"))
async def confirm_buy_callback(callback: CallbackQuery):
    """Confirm card purchase with beautiful card display"""
    game_id = callback.data.replace("confirm_buy_", "")
    user_id = callback.from_user.id
    
    # Check if user already has a card
    existing_cards = await Database.get_user_cards(user_id, game_id)
    if existing_cards:
        # Show existing card beautifully
        card = existing_cards[0]
        card_numbers = json.loads(card['card_data'])
        card_display = format_card_display_html(card_numbers)
        
        await callback.message.edit_text(
            f"""
🎫 <b>YOU ALREADY HAVE A CARD!</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✅ <b>Card #{card['card_index']}</b>
🎮 <b>Game:</b> <code>#{game_id[:8]}</code>

{card_display}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

<b>🎮 GAME STATUS:</b>
• ⏳ Wait for numbers to be called
• 🔢 Numbers called automatically
• 🏆 First to complete line wins!

<b>🎯 TIP:</b> Watch for number announcements!
            """,
            parse_mode="HTML"
        )
        await callback.answer("You already have a card in this game! ✅", show_alert=True)
        return
    
    # Join game and get card
    result = await GameManager.player_join_game(user_id, game_id)
    
    if result['success']:
        # Get card data
        card_index = result.get('card_index', 0)
        card_numbers = result.get('card_numbers', [])
        game_id_short = game_id[:8]
        
        # Format beautiful card display
        card_display = format_card_display_html(card_numbers)
        
        # UPDATE SUCCESS TEXT - CHANGE TO 10 birr
        success_text = f"""
🎉 <b>CARD PURCHASED SUCCESSFULLY!</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✅ <b>Transaction Complete</b>
• 💰 Price: <code>{CARD_PRICE:.0f} {CURRENCY}</code>  # CHANGED
• 🎫 Card ID: <code>#{card_index}</code>
• 🎮 Game: <code>#{game_id_short}</code>
• ⏰ Time: <code>{datetime.now().strftime('%H:%M:%S')}</code>

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

<b>🎲 YOUR BINGO CARD:</b>

{card_display}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

<b>📋 WHAT'S NEXT?</b>
1. ⏳ Wait for game to start
2. 🔢 Numbers will be called automatically
3. ✅ Mark your card when numbers match
4. 🏆 First to complete line WINS!

<b>🎯 GOOD LUCK!</b> 🍀
"""
        
        await callback.message.edit_text(
            success_text,
            parse_mode="HTML"
        )
        
        # Send game status update
        game_info = await GameManager.get_active_game_info()
        if game_info:
            players = game_info.get('players', 0)
            prize_pool = game_info.get('prize_pool', 0)
            
            # UPDATE GAME UPDATE TEXT
            update_text = f"""
🔔 <b>GAME UPDATE</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📊 <b>Updated Stats:</b>
• 👥 Players: <code>{players}</code>
• 💰 Prize Pool: <code>{prize_pool:.0f} {CURRENCY}</code>  # CHANGED

🎮 <b>Game will start automatically when enough players join!</b>

🏆 <b>Current Prize Pool:</b> <code>{prize_pool:.0f} {CURRENCY}</code>  # CHANGED
            """
            
            await callback.message.answer(
                update_text,
                parse_mode="HTML"
            )
    else:
        # Error handling with beautiful message
        error_msg = result.get('message', 'Unknown error')
        
        error_text = f"""
❌ <b>PURCHASE FAILED</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

😔 <b>Could not complete purchase:</b>
<code>{safe_format(error_msg)}</code>

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

<b>💡 TROUBLESHOOTING:</b>
• Check your balance with <code>/balance</code>
• Ensure game is still joinable
• Try again in a moment

<b>📞 Need help?</b> Contact support.
"""
        
        await callback.message.edit_text(
            error_text,
            parse_mode="HTML"
        )
    
    await callback.answer()

# Beautiful card view callback
@router.callback_query(F.data.startswith("view_card_"))
async def view_card_callback(callback: CallbackQuery):
    """View existing card with beautiful display"""
    game_id = callback.data.replace("view_card_", "")
    user_id = callback.from_user.id
    
    # Get user's card
    existing_cards = await Database.get_user_cards(user_id, game_id)
    if not existing_cards:
        await callback.answer("❌ No card found", show_alert=True)
        return
    
    card = existing_cards[0]
    card_numbers = json.loads(card['card_data'])
    card_display = format_card_display_html(card_numbers)
    
    # Get game info
    game = await Database.get_game(game_id)
    game_status = game['status'] if game else 'unknown'
    
    # Get status emoji
    status_emoji = get_game_status_emoji(game_status)
    
    view_text = f"""
🎫 <b>YOUR BINGO CARD</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

<b>Card Details:</b>
• 🆔 Card ID: <code>#{card['card_index']}</code>
• 🎮 Game: <code>#{game_id[:8]}</code>
• 📊 Status: {status_emoji} <code>{game_status.upper()}</code>

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{card_display}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

<b>🎮 GAME STATUS:</b>
• 🔢 Numbers called automatically
• ✅ Mark matching numbers
• 🏆 Complete a line to win!

<b>🎯 TIP:</b> Watch closely for number calls!
"""
    
    # Create keyboard with options
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔄 Refresh", callback_data=f"refresh_{game_id}"),
            InlineKeyboardButton(text="📊 Game Info", callback_data=f"game_info_{game_id}")
        ],
        [
            InlineKeyboardButton(text="⭐ Buy Another", callback_data=f"buy_card_{game_id}"),
            InlineKeyboardButton(text="🏠 Main Menu", callback_data="main_menu")
        ]
    ])
    
    await callback.message.edit_text(
        view_text,
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    
    await callback.answer()

# Add this import at the top
from datetime import datetime

# Enhanced join game callback
@router.callback_query(F.data == "join_current_game")
async def join_current_game_callback(callback: CallbackQuery):
    """Join current game with beautiful display"""
    await cmd_game(callback.message)
    await callback.answer("Loading game info... ⏳")

# Add these missing callback handlers
@router.callback_query(F.data == "game_info")
async def game_info_callback(callback: CallbackQuery):
    """Show game info"""
    await cmd_game(callback.message)
    await callback.answer()

@router.callback_query(F.data == "my_cards")
async def my_cards_callback(callback: CallbackQuery):
    """Show my cards"""
    from handlers.user import cmd_my_cards
    await cmd_my_cards(callback.message)
    await callback.answer()

@router.callback_query(F.data == "balance_info")
async def balance_info_callback(callback: CallbackQuery):
    """Show balance info"""
    from handlers.user import cmd_balance
    await cmd_balance(callback.message)
    await callback.answer()

@router.callback_query(F.data == "how_to_play")
async def how_to_play_callback(callback: CallbackQuery):
    """Show how to play"""
    # UPDATE HOW TO PLAY TEXT - CHANGE TO 10 birr
    how_to_text = f"""
🎯 <b>HOW TO PLAY HABESHA BINGO</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

<b>🎮 STEP 1: Join a Game</b>
• Use <code>/game</code> to see active games
• Click "Buy Card" to join
• Each card costs <code>{CARD_PRICE:.0f} {CURRENCY}</code>  # CHANGED

<b>🃏 STEP 2: Get Your Card</b>
• Receive a unique 5x5 bingo card
• Center square is <b>FREE</b> 🎁
• Cards are from 400 pre-generated set

<b>🔢 STEP 3: Game Play</b>
• Numbers are called automatically (1-75)
• Mark numbers on your card
• Watch for B (1-15), I (16-30), N (31-45), G (46-60), O (61-75)

<b>🏆 STEP 4: Win!</b>
• Complete a row, column, or diagonal
• First to complete wins the prize
• Multiple winners supported

<b>💰 PRIZES:</b>
• {GAME_CONFIG.get('prize_pool_percentage', 0.80)*100:.0f}% of card sales go to prize pool ({CARD_PRICE * GAME_CONFIG.get('prize_pool_percentage', 0.80):.0f} {CURRENCY})  # CHANGED
• {GAME_CONFIG.get('house_fee_percentage', 0.20)*100:.0f}% house fee ({CARD_PRICE * GAME_CONFIG.get('house_fee_percentage', 0.20):.0f} {CURRENCY})  # CHANGED
• Instant distribution to winners

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

<b>🎲 CARD LEGEND:</b>
• 🔵 B: 1-15
• 🟢 I: 16-30
• 🟡 N: 31-45
• 🟠 G: 46-60
• 🔴 O: 61-75
• 🎁 Center: FREE

<b>🎯 GOOD LUCK!</b> 🍀
"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎮 Join Game", callback_data="join_current_game")],
        [InlineKeyboardButton(text="💰 Check Balance", callback_data="balance_info")],
        [InlineKeyboardButton(text="🏠 Main Menu", callback_data="main_menu")]
    ])
    
    await callback.message.edit_text(
        how_to_text,
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data == "buy_card_direct")
async def buy_card_direct_callback(callback: CallbackQuery):
    """Direct buy card"""
    await cmd_buy(callback.message)
    await callback.answer()

@router.callback_query(F.data == "main_menu")
async def main_menu_callback(callback: CallbackQuery):
    """Return to main menu"""
    await cmd_start(callback.message)
    await callback.answer()

# Keep other handlers as they are...
@router.callback_query(F.data.startswith("refresh_"))
async def refresh_callback(callback: CallbackQuery):
    """Refresh game info"""
    await cmd_game(callback.message)
    await callback.answer()

@router.callback_query(F.data == "cancel")
async def cancel_callback(callback: CallbackQuery):
    """Cancel action"""
    await callback.message.edit_text(
        """
❌ <b>ACTION CANCELLED</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

No changes were made.

Use <code>/start</code> to return to main menu.
        """,
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data == "cancel_buy")
async def cancel_buy_callback(callback: CallbackQuery):
    """Cancel purchase"""
    await callback.message.edit_text(
        """
❌ <b>PURCHASE CANCELLED</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

No charges were made to your account.

Use <code>/game</code> to see current games or try again later.
        """,
        parse_mode="HTML"
    )
    await callback.answer()

# Add this handler for game_info with game_id
@router.callback_query(F.data.startswith("game_info_"))
async def game_info_with_id_callback(callback: CallbackQuery):
    """Show specific game info"""
    await cmd_game(callback.message)
    await callback.answer()

# Error handler
@router.error()
async def error_handler(event, exception):
    """Handle errors in game handlers"""
    logger.error(f"Error in game handler: {exception}")
    
    # If this is a callback query, answer it to avoid hanging
    if hasattr(event, 'callback_query') and event.callback_query:
        try:
            await event.callback_query.answer("❌ An error occurred. Please try again.", show_alert=True)
        except:
            pass
    
    return True