from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from database.db import Database
from config import WEBSERVER_HOST, WEBSERVER_PORT, ADMIN_IDS
import logging

logger = logging.getLogger(__name__)

router = Router()

def get_user_id_from_message(message: types.Message) -> int:
    """
    Safely get user ID from message, handling Telegram quirks.
    Returns the actual user ID, not bot ID.
    """
    user_id = message.from_user.id
    
    # DEBUG: Log what we're getting
    logger.info(f"🔍 RAW User ID: {user_id}, Username: {message.from_user.username}, Name: {message.from_user.full_name}")
    
    # Check if this is the bot's ID (8471833442)
    if user_id == 8471833442:
        logger.warning("⚠️ Bot ID detected, checking for real user...")
        
        # Method 1: Check if user is in chat (for groups/channels)
        if message.chat and message.chat.id != user_id:
            logger.info(f"📱 Chat ID is different: {message.chat.id}, using chat ID")
            return message.chat.id
        
        # Method 2: Check if there's a reply to another message
        if message.reply_to_message:
            original_sender = message.reply_to_message.from_user.id
            logger.info(f"↩️ Reply detected, using original sender ID: {original_sender}")
            return original_sender
        
        # Method 3: Use admin ID from config (you!)
        if ADMIN_IDS and len(ADMIN_IDS) > 0:
            admin_id = ADMIN_IDS[0]
            logger.info(f"👑 Using admin ID from config: {admin_id}")
            return admin_id
    
    return user_id

@router.message(Command("play"))
async def cmd_play(message: types.Message):
    """Play command - open game interface"""
    try:
        # Get the REAL user ID (not bot ID)
        user_id = get_user_id_from_message(message)
        
        logger.info(f"🎯 FINAL User ID for /play: {user_id}")
        
        # Ensure user exists in database
        user = await Database.get_user(user_id)
        if not user:
            # Create user if doesn't exist
            username = message.from_user.username or ""
            full_name = message.from_user.full_name or ""
            await Database.create_user(user_id, username, full_name)
            logger.info(f"✅ Created new user: {user_id}")
        
        active_game = await Database.get_active_game()
        
        if not active_game:
            await message.answer(
                "🎮 <b>No Active Game</b>\n\n"
                "There is no active game at the moment.\n"
                "Please wait for the admin to start a new game!"
            )
            return
        
        # Use HTTPS URL for Telegram Mini App
        NGROK_HTTPS_URL = "https://branden-bimotored-dakota.ngrok-free.dev"
        webapp_url = f"{NGROK_HTTPS_URL}/game.html?user_id={user_id}"
        
        # Create inline keyboard with Web App button
        builder = InlineKeyboardBuilder()
        
        builder.row(
            types.InlineKeyboardButton(
                text="🎮 Launch Game",
                web_app=types.WebAppInfo(url=webapp_url)
            )
        )
        
        # Add info buttons
        builder.row(
            types.InlineKeyboardButton(
                text="💰 Check Balance",
                callback_data=f"check_balance_{user_id}"
            ),
            types.InlineKeyboardButton(
                text="🎴 My Cards",
                callback_data=f"my_cards_{user_id}"
            )
        )
        
        # Get game info
        prize_pool = active_game.get('prize_pool', 0)
        player_count = active_game.get('total_players', 0)
        game_status = active_game.get('status', 'waiting').upper()
        
        # Send response
        await message.answer(
            f"🎮 <b>Habesha Bingo - Game Interface</b>\n\n"
            f"📊 <b>Game Status:</b> {game_status}\n"
            f"💰 <b>Prize Pool:</b> {prize_pool:.2f} birr\n"
            f"👥 <b>Players:</b> {player_count}\n"
            f"🎫 <b>Your ID:</b> <code>{user_id}</code>\n\n"
            f"Click the button below to launch the game!",
            reply_markup=builder.as_markup()
        )
        
        # Log the URL for debugging
        logger.info(f"🌐 Generated WebApp URL: {webapp_url}")
        
    except Exception as e:
        logger.error(f"Error in cmd_play: {e}", exc_info=True)
        await message.answer(
            "❌ Could not open the game interface right now. Please try again later."
        )

@router.callback_query(F.data.startswith("check_balance_"))
async def check_balance_callback(callback: types.CallbackQuery):
    """Check balance from callback"""
    try:
        # Extract user_id from callback data
        user_id_str = callback.data.replace("check_balance_", "")
        user_id = int(user_id_str)
        
        user = await Database.get_user(user_id)
        if user:
            await callback.message.answer(
                f"💰 <b>Your Balance</b>\n\n"
                f"Current Balance: <b>{user['balance']:.2f} birr</b>\n\n"
                f"Card Price: 2.00 birr\n"
                f"You can buy {int(user['balance'] // 2)} cards."
            )
        else:
            await callback.message.answer(
                "❌ User not found. Please use /start first."
            )
    except Exception as e:
        logger.error(f"Error in check_balance_callback: {e}")
        await callback.message.answer(
            "❌ Could not check balance. Please try again."
        )
    await callback.answer()

@router.callback_query(F.data.startswith("my_cards_"))
async def my_cards_callback(callback: types.CallbackQuery):
    """View user's cards from callback"""
    try:
        user_id_str = callback.data.replace("my_cards_", "")
        user_id = int(user_id_str)
        
        # Get active game
        active_game = await Database.get_active_game()
        if not active_game:
            await callback.message.answer("🎮 No active game found.")
            await callback.answer()
            return
        
        # Get user cards
        user_cards = await Database.get_user_cards(user_id, active_game['game_id'])
        
        if user_cards:
            card_count = len(user_cards)
            await callback.message.answer(
                f"🎫 <b>Your Cards</b>\n\n"
                f"You have <b>{card_count}</b> card(s) in the current game:\n\n"
                f"Game: {active_game['game_id'][:8]}...\n"
                f"Status: {active_game['status'].upper()}\n"
                f"Prize Pool: {active_game.get('prize_pool', 0):.2f} birr\n\n"
                f"Click the card numbers in the game to mark them!"
            )
        else:
            await callback.message.answer(
                "🎴 <b>No Cards Yet</b>\n\n"
                "You don't have any cards in the current game.\n\n"
                "Use <code>/buy 1</code> to buy a card for 2.00 birr!"
            )
    except Exception as e:
        logger.error(f"Error in my_cards_callback: {e}")
        await callback.message.answer(
            "❌ Could not load your cards. Please try again."
        )
    await callback.answer()

@router.message(Command("myid"))
async def cmd_myid(message: types.Message):
    """Show user's REAL Telegram ID"""
    try:
        # Get the REAL user ID using our function
        real_user_id = get_user_id_from_message(message)
        raw_user_id = message.from_user.id
        
        username = message.from_user.username or "No username"
        full_name = message.from_user.full_name or "No name"
        
        response = (
            f"👤 <b>Your Telegram Info</b>\n\n"
            f"🆔 <b>Real User ID:</b> <code>{real_user_id}</code>\n"
            f"🤖 <b>Raw Sender ID:</b> <code>{raw_user_id}</code>\n"
            f"👤 <b>Username:</b> @{username}\n"
            f"📛 <b>Full Name:</b> {full_name}\n\n"
        )
        
        # Check if IDs are different
        if real_user_id != raw_user_id:
            response += f"⚠️ <i>Note: Telegram is sending bot's ID. Using your real ID: {real_user_id}</i>\n\n"
        
        # Check if user exists in database
        user = await Database.get_user(real_user_id)
        if user:
            response += f"💰 <b>Database Balance:</b> {user['balance']:.2f} birr"
        else:
            response += "📝 <i>User not found in database. Use /start to register.</i>"
        
        await message.answer(response)
        
    except Exception as e:
        logger.error(f"Error in cmd_myid: {e}")
        await message.answer("❌ Could not get user info.")

@router.message(Command("forceplay"))
async def cmd_forceplay(message: types.Message):
    """Force open game with your admin ID"""
    try:
        # Always use YOUR admin ID (241451670)
        admin_id = 241451670
        
        active_game = await Database.get_active_game()
        
        if not active_game:
            await message.answer("🎮 No active game found.")
            return
        
        # Ensure admin user exists
        admin_user = await Database.get_user(admin_id)
        if not admin_user:
            await Database.create_user(admin_id, "admin", "Admin User")
            logger.info(f"✅ Created admin user: {admin_id}")
        
        NGROK_HTTPS_URL = "https://branden-bimotored-dakota.ngrok-free.dev"
        webapp_url = f"{NGROK_HTTPS_URL}/game.html?user_id={admin_id}"
        
        builder = InlineKeyboardBuilder()
        builder.row(
            types.InlineKeyboardButton(
                text="🎮 Open Game (Admin)",
                web_app=types.WebAppInfo(url=webapp_url)
            )
        )
        
        await message.answer(
            f"🛠️ <b>Admin Game Access</b>\n\n"
            f"This will open the game with Admin ID:\n"
            f"• User ID: <code>{admin_id}</code>\n"
            f"• Game: {active_game['game_id'][:8]}...\n"
            f"• Prize Pool: {active_game.get('prize_pool', 0):.2f} birr\n\n"
            f"<i>For testing your personal account.</i>",
            reply_markup=builder.as_markup()
        )
        
        # Also show the direct URL
        await message.answer(
            f"🔗 <b>Direct Game URL:</b>\n"
            f"<code>{webapp_url}</code>\n\n"
            f"Copy and paste this in your browser."
        )
        
    except Exception as e:
        logger.error(f"Error in cmd_forceplay: {e}")
        await message.answer("❌ Could not open admin game.")

@router.message(Command("game"))
async def cmd_game(message: types.Message):
    """Join current game"""
    try:
        # Get real user ID
        user_id = get_user_id_from_message(message)
        
        active_game = await Database.get_active_game()
        
        if not active_game:
            await message.answer(
                "🎮 <b>No Active Game</b>\n\n"
                "There is no active game at the moment.\n"
                "Please wait for the admin to start a new game!"
            )
            return
        
        # Check if user already has a card
        user_cards = await Database.get_user_cards(user_id, active_game['game_id'])
        
        if user_cards:
            # User already has cards
            card_count = len(user_cards)
            await message.answer(
                f"✅ <b>You're already in the game!</b>\n\n"
                f"🎮 <b>Game:</b> {active_game['game_id'][:8]}...\n"
                f"📊 <b>Status:</b> {active_game['status'].upper()}\n"
                f"🎫 <b>Your Cards:</b> {card_count}\n"
                f"💰 <b>Prize Pool:</b> {active_game.get('prize_pool', 0):.2f} birr\n\n"
                f"Use <code>/play</code> to open the game interface\n"
                f"or <code>/cards</code> to view your cards."
            )
        else:
            # User needs to buy a card
            await message.answer(
                f"🎮 <b>Join Game: {active_game['game_id'][:8]}...</b>\n\n"
                f"📊 <b>Status:</b> {active_game['status'].upper()}\n"
                f"💰 <b>Prize Pool:</b> {active_game.get('prize_pool', 0):.2f} birr\n"
                f"👥 <b>Players:</b> {active_game.get('total_players', 0)}\n\n"
                "To join this game, you need to buy a bingo card.\n"
                "Each card costs <b>2.00 birr</b>\n\n"
                "Use <code>/buy 1</code> to buy 1 card\n"
                "or <code>/buy 3</code> to buy 3 cards\n\n"
                "After buying cards, use <code>/play</code> to start playing!"
            )
            
    except Exception as e:
        logger.error(f"Error in cmd_game: {e}")
        await message.answer(
            "❌ Could not process game join request.\n"
            "Please try again or contact admin."
        )

@router.message(Command("cardinfo"))
async def cmd_cardinfo(message: types.Message):
    """Show card system information"""
    try:
        from utils.card_generator import CardGenerator
        
        total_cards = CardGenerator.get_total_cards()
        
        card_info = "🃏 <b>Bingo Card System Info</b>\n\n"
        card_info += f"📊 <b>Total Cards:</b> {total_cards}\n"
        card_info += f"🎯 <b>Card Format:</b> 5x5 grid (25 squares)\n"
        card_info += f"🎁 <b>Center Square:</b> FREE\n"
        card_info += f"🔢 <b>Number Range:</b> 1-75\n\n"
        
        card_info += "<b>Column Distribution:</b>\n"
        card_info += "• B: 1-15\n"
        card_info += "• I: 16-30\n"
        card_info += "• N: 31-45\n"
        card_info += "• G: 46-60\n"
        card_info += "• O: 61-75\n\n"
        
        card_info += "💡 <b>Note:</b> Every card is unique!\n"
        card_info += "No two players get the same card in a game."
        
        await message.answer(card_info)
        
    except Exception as e:
        logger.error(f"Error in cmd_cardinfo: {e}")
        await message.answer(
            "🃏 <b>Card System Info</b>\n\n"
            "• Total Cards: 400 unique cards\n"
            "• Card Format: 5x5 grid\n"
            "• Center: FREE\n"
            "• Numbers: 1-75\n"
            "• All cards are unique!"
        )

# Direct URL test command
@router.message(Command("testurl"))
async def cmd_testurl(message: types.Message):
    """Get direct game URL with correct user ID"""
    try:
        # Get real user ID
        user_id = get_user_id_from_message(message)
        
        NGROK_HTTPS_URL = "https://branden-bimotored-dakota.ngrok-free.dev"
        game_url = f"{NGROK_HTTPS_URL}/game.html?user_id={user_id}"
        
        await message.answer(
            f"🔗 <b>Your Game URL</b>\n\n"
            f"User ID: <code>{user_id}</code>\n\n"
            f"Direct Link:\n"
            f"<code>{game_url}</code>\n\n"
            f"Click or copy this URL to open the game directly."
        )
        
    except Exception as e:
        logger.error(f"Error in cmd_testurl: {e}")
        await message.answer("❌ Could not generate game URL.")