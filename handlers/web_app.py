from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from database.db import Database
from config import NGROK_HTTPS_URL, WEBSERVER_HOST, WEBSERVER_PORT
import logging

logger = logging.getLogger(__name__)

router = Router()

@router.message(Command("play"))
async def play_command(message: types.Message):
    """Handle /play command to open Web App with user ID"""
    
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    
    # Create WebApp URL WITH user ID parameter
    if NGROK_HTTPS_URL:
        webapp_url = f"{NGROK_HTTPS_URL}/game.html?user_id={user_id}"
    else:
        webapp_url = f"http://{WEBSERVER_HOST}:{WEBSERVER_PORT}/game.html?user_id={user_id}"
    
    logger.info(f"🎮 Creating WebApp for user {user_id}: {webapp_url}")
    
    # Create inline keyboard
    builder = InlineKeyboardBuilder()
    
    # Web App button (HTTPS required by Telegram)
    builder.row(
        types.InlineKeyboardButton(
            text="🎮 Launch Telegram Mini App",
            web_app=types.WebAppInfo(url=webapp_url)
        )
    )
    
    # Add alternative browser button with user ID
    builder.row(
        types.InlineKeyboardButton(
            text="🌐 Open in Browser",
            url=webapp_url
        )
    )
    
    # Add game info buttons
    builder.row(
        types.InlineKeyboardButton(
            text="📋 Game Rules",
            callback_data="game_rules"
        ),
        types.InlineKeyboardButton(
            text="💰 Buy Cards",
            callback_data="buy_cards_web"
        )
    )
    
    builder.row(
        types.InlineKeyboardButton(
            text="🏆 My Cards",
            callback_data="my_cards_web"
        ),
        types.InlineKeyboardButton(
            text="📊 Live Stats",
            callback_data="game_stats"
        )
    )
    
    await message.answer(
        f"🎮 <b>Habesha Bingo - Telegram Mini App</b>\n\n"
        f"<b>User:</b> {username}\n"
        f"<b>ID:</b> <code>{user_id}</code>\n\n"
        "✨ <b>Features:</b>\n"
        "• Opens in Telegram\n"
        "• Real-time gameplay\n"
        "• Interactive cards\n"
        "• Auto-marking\n\n"
        "<i>Using secure HTTPS connection</i>\n"
        f"<i>URL: {webapp_url}</i>",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )

@router.callback_query(F.data == "game_rules")
async def game_rules_callback(callback: types.CallbackQuery):
    """Show game rules"""
    try:
        rules = """
<b>📋 GAME RULES</b>

<b>🎯 How to Play:</b>
1. Buy a bingo card (10 birr)
2. Join an active game
3. Numbers called automatically every 5s
4. Mark numbers on your card
5. Complete a line to win!

<b>🏆 Winning Patterns:</b>
• Horizontal line (5 in a row)
• Vertical line (5 in a column)
• Diagonal line (top-left to bottom-right or vice versa)

<b>💰 Prize Pool:</b>
• 80% of all card sales to prize pool
• First winner takes entire prize pool
• House fee: 20%

<b>🎫 Card System:</b>
• 400 unique pre-generated cards
• Fair random assignment
• Card preview available
"""
        await callback.message.answer(rules, parse_mode="HTML")
        await callback.answer()
    except Exception as e:
        logger.error(f"Error in game_rules_callback: {e}")
        await callback.answer("❌ Error showing rules", show_alert=True)

@router.callback_query(F.data == "buy_cards_web")
async def buy_cards_web_callback(callback: types.CallbackQuery):
    """Buy cards via WebApp"""
    try:
        user_id = callback.from_user.id
        user = await Database.get_user(user_id)
        
        if not user:
            await callback.answer("Please use /start first!", show_alert=True)
            return
        
        if NGROK_HTTPS_URL:
            webapp_url = f"{NGROK_HTTPS_URL}/game.html?user_id={user_id}#buy"
        else:
            webapp_url = f"http://{WEBSERVER_HOST}:{WEBSERVER_PORT}/game.html?user_id={user_id}#buy"
        
        builder = InlineKeyboardBuilder()
        builder.row(
            types.InlineKeyboardButton(
                text="🎴 Buy Card in WebApp",
                web_app=types.WebAppInfo(url=webapp_url)
            )
        )
        
        await callback.message.answer(
            f"💰 <b>Buy Bingo Cards</b>\n\n"
            f"<b>Your Balance:</b> {user['balance']:.2f} birr\n"
            f"<b>Card Price:</b> 10 birr\n"
            f"<b>Prize Pool:</b> 8 birr per card\n\n"
            f"Click below to open the card selection screen:",
            parse_mode="HTML",
            reply_markup=builder.as_markup()
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"Error in buy_cards_web_callback: {e}")
        await callback.answer("❌ Error showing buy cards", show_alert=True)

@router.callback_query(F.data == "my_cards_web")
async def my_cards_web_callback(callback: types.CallbackQuery):
    """View my cards via WebApp"""
    try:
        user_id = callback.from_user.id
        user = await Database.get_user(user_id)
        
        if not user:
            await callback.answer("Please use /start first!", show_alert=True)
            return
        
        # Get user's cards
        user_cards = await Database.get_user_cards(user_id)
        
        if NGROK_HTTPS_URL:
            webapp_url = f"{NGROK_HTTPS_URL}/game.html?user_id={user_id}"
        else:
            webapp_url = f"http://{WEBSERVER_HOST}:{WEBSERVER_PORT}/game.html?user_id={user_id}"
        
        builder = InlineKeyboardBuilder()
        builder.row(
            types.InlineKeyboardButton(
                text="🃏 View My Cards",
                web_app=types.WebAppInfo(url=webapp_url)
            )
        )
        
        if user_cards:
            card_count = len(user_cards)
            await callback.message.answer(
                f"🃏 <b>Your Bingo Cards</b>\n\n"
                f"<b>Total Cards:</b> {card_count}\n"
                f"<b>Last Game:</b> {user_cards[0]['game_id'][:8] if card_count > 0 else 'None'}\n\n"
                f"Click below to view your cards in the WebApp:",
                parse_mode="HTML",
                reply_markup=builder.as_markup()
            )
        else:
            await callback.message.answer(
                f"🃏 <b>Your Bingo Cards</b>\n\n"
                f"You don't have any cards yet!\n"
                f"<b>Card Price:</b> 10 birr\n\n"
                f"Click below to buy your first card:",
                parse_mode="HTML",
                reply_markup=builder.as_markup()
            )
        
        await callback.answer()
    except Exception as e:
        logger.error(f"Error in my_cards_web_callback: {e}")
        await callback.answer("❌ Error showing cards", show_alert=True)

@router.callback_query(F.data == "game_stats")
async def game_stats_callback(callback: types.CallbackQuery):
    """Show game stats"""
    try:
        # Get active game
        active_game = await Database.get_active_game()
        
        if active_game:
            prize_pool = active_game.get('prize_pool', 0)
            players = active_game.get('total_players', 0)
            game_id = active_game['game_id']
            
            stats = f"""
<b>📊 LIVE GAME STATS</b>

<b>Game ID:</b> {game_id[:8]}
<b>Status:</b> {active_game.get('status', 'waiting')}
<b>Prize Pool:</b> {prize_pool:.2f} birr
<b>Players:</b> {players}
<b>Cards Sold:</b> {active_game.get('total_cards_sold', 0)}
"""
        else:
            stats = """
<b>📊 GAME STATS</b>

No active game at the moment.
Use /game to create or join a game!

<b>Next Game:</b> Starting soon
<b>Card Price:</b> 10 birr
"""
        
        await callback.message.answer(stats, parse_mode="HTML")
        await callback.answer()
    except Exception as e:
        logger.error(f"Error in game_stats_callback: {e}")
        await callback.answer("❌ Error showing stats", show_alert=True)

@router.callback_query(F.data == "refresh_webapp_test")
async def refresh_webapp_test_callback(callback: types.CallbackQuery):
    """Refresh Web App test"""
    await play_command(callback.message)
    await callback.answer()

@router.message(Command("webapp"))
async def webapp_debug_command(message: types.Message):
    """Debug WebApp URL"""
    user_id = message.from_user.id
    
    if NGROK_HTTPS_URL:
        webapp_url = f"{NGROK_HTTPS_URL}/game.html?user_id={user_id}"
    else:
        webapp_url = f"http://{WEBSERVER_HOST}:{WEBSERVER_PORT}/game.html?user_id={user_id}"
    
    await message.answer(
        f"🔗 <b>WebApp Debug Info</b>\n\n"
        f"<b>User ID:</b> <code>{user_id}</code>\n"
        f"<b>WebApp URL:</b>\n<code>{webapp_url}</code>\n\n"
        f"<b>Test Links:</b>\n"
        f"• <a href='{webapp_url}'>Open in browser</a>\n"
        f"• <a href='{webapp_url.replace('game.html', 'health')}'>Health check</a>\n"
        f"• <a href='{webapp_url.replace('game.html', 'api/game/active')}'>Active game API</a>\n\n"
        f"Use /play to get the WebApp button.",
        parse_mode="HTML",
        disable_web_page_preview=True
    )