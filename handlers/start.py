from aiogram import Router, F, types
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from database.db import Database
from utils.card_generator import CardGenerator
from config import GAME_CONFIG
import logging
import html

logger = logging.getLogger(__name__)
router = Router()

def escape_html_safe(text):
    """Safely escape HTML characters"""
    if text is None:
        return ""
    return html.escape(str(text))

@router.message(Command("start"))
async def start_command(message: Message):
    """Register user and show main menu with 400-card system"""
    try:
        user_id = message.from_user.id
        username = message.from_user.username or ""
        full_name = message.from_user.full_name
        
        await Database.create_user(user_id, username, full_name)
        
        # Check card system status
        cards = CardGenerator.get_all_cards()
        card_count = len(cards) if cards else 0
        card_status = f"✅ {card_count}/400 Cards Loaded" if card_count == 400 else f"⚠️ {card_count}/400 Cards"
        
        welcome = f"""
🎉 <b>Welcome to Habesha Bingo!</b> 🎉

🏆 <b>The Ultimate Bingo Experience</b>

✨ <b>Features:</b>
• {card_status} - Fixed & Fair System
• 🎴 Card Preview - See before purchase
• 👥 Multiplayer Games - Real players
• 💰 Instant Payouts - Telebirr/Chapa
• 🔒 Secure Gameplay - Verified system

📊 <b>Game Info:</b>
• Card Price: <b>${GAME_CONFIG.get('card_price', 2.00):.2f}</b>
• Prize Pool: <b>{GAME_CONFIG.get('prize_pool_percent', 85)}%</b> of card sales
• Game Duration: <b>{GAME_CONFIG.get('countdown_duration', 60)}s</b> countdown

🚀 <b>Get Started:</b>
1. Check balance with /balance
2. Join game with /game
3. Buy card with /buy
4. Win prizes!

📋 <b>Commands:</b>
/game - Join current game
/cards - View your cards  
/balance - Check balance
/buy - Buy bingo card
/cardinfo - Card system info
/profile - Your stats
/help - Game instructions

<b>በደህና መጡ</b> 🎮
"""
        
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="🎮 Play Game", callback_data="play_game"),
                    InlineKeyboardButton(text="💰 Balance", callback_data="check_balance")
                ],
                [
                    InlineKeyboardButton(text="🎴 Buy Card", callback_data="buy_card_with_preview"),
                    InlineKeyboardButton(text="🃏 My Cards", callback_data="my_cards")
                ],
                [
                    InlineKeyboardButton(text="📊 Game Info", callback_data="game_info"),
                    InlineKeyboardButton(text="❓ Help", callback_data="help_menu")
                ]
            ]
        )
        
        await message.answer(welcome, parse_mode="HTML", reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"Error in start_command: {e}")
        await message.answer("❌ An error occurred. Please try again.")

@router.message(Command("help"))
async def help_command(message: Message):
    """Show help instructions with card system info"""
    try:
        cards = CardGenerator.get_all_cards()
        card_status = f"✅ {len(cards)}/400 cards loaded" if cards and len(cards) == 400 else "⚠️ Loading cards..."
        
        help_text = f"""
<b>📖 HOW TO PLAY HABESHA BINGO</b>

<b>🎯 Card System:</b>
{card_status}
• 400 unique pre-generated cards
• Fair random assignment
• Card preview before purchase

<b>🚀 Step-by-Step Guide:</b>
1. <b>Check Balance:</b> Use /balance or button below
2. <b>Join Game:</b> Use /game to see active games
3. <b>Buy Card:</b> Purchase card for ${GAME_CONFIG.get('card_price', 2.00):.2f}
4. <b>Play:</b> Numbers called automatically every 5s
5. <b>Win:</b> Complete line (row, column, diagonal)
6. <b>Prize:</b> {GAME_CONFIG.get('prize_pool_percent', 85)}% of card sales to winners

<b>🎯 Winning Patterns:</b>
• Horizontal line (5 in a row)
• Vertical line (5 in a column)
• Diagonal line (top-left to bottom-right or vice versa)
• Four corners (special games)

<b>💰 Prize Distribution:</b>
• {GAME_CONFIG.get('prize_pool_percent', 85)}% of card sales to prize pool
• {GAME_CONFIG.get('house_fee_percent', 15)}% house fee
• Multiple winners supported

<b>📞 Support:</b>
For game issues use /help
For payment issues contact admin
"""
        
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🎮 Join Game", callback_data="join_current_game")],
                [InlineKeyboardButton(text="💰 Check Balance", callback_data="check_balance")],
                [InlineKeyboardButton(text="🏠 Main Menu", callback_data="main_menu")]
            ]
        )
        
        await message.answer(help_text, parse_mode="HTML", reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"Error in help_command: {e}")
        await message.answer("❌ An error occurred. Please try again.")

@router.message(Command("profile"))
async def profile_command(message: Message):
    """Show user profile"""
    try:
        user = await Database.get_user(message.from_user.id)
        
        if not user:
            await message.answer("Please use /start first!")
            return
        
        # Get user cards
        user_cards = await Database.get_user_cards(user['user_id'])
        total_cards = len(user_cards) if user_cards else 0
        
        win_rate = (user['games_won'] / user['total_games'] * 100) if user['total_games'] > 0 else 0
        avg_win = (user['total_winnings'] / user['games_won']) if user['games_won'] > 0 else 0
        
        created_date = user['created_at'].strftime('%Y-%m-%d') if user.get('created_at') else 'N/A'
        
        profile = f"""
<b>👤 PLAYER PROFILE</b>

<b>📊 Statistics:</b>
💰 Balance: <b>${user['balance']:.2f}</b>
🎮 Games Played: <b>{user['total_games']}</b>
🏆 Games Won: <b>{user['games_won']}</b>
💵 Total Winnings: <b>${user['total_winnings']:.2f}</b>
🎫 Cards Purchased: <b>{total_cards}</b>

<b>📈 Performance:</b>
Win Rate: <b>{win_rate:.1f}%</b>
Avg Win: <b>${avg_win:.2f}</b>

<b>Account Created:</b> {created_date}
"""
        
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Refresh", callback_data="refresh_profile")],
                [InlineKeyboardButton(text="🎴 My Cards", callback_data="my_cards")],
                [InlineKeyboardButton(text="📜 History", callback_data="transaction_history")],
                [InlineKeyboardButton(text="🏠 Main Menu", callback_data="main_menu")]
            ]
        )
        
        await message.answer(profile, parse_mode="HTML", reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"Error in profile_command: {e}")
        await message.answer("❌ An error occurred. Please try again.")

@router.callback_query(F.data == "check_balance")
async def check_balance_callback(callback: CallbackQuery):
    """Check balance from callback"""
    try:
        user = await Database.get_user(callback.from_user.id)
        if user:
            # Get user cards
            user_cards = await Database.get_user_cards(user['user_id'])
            total_cards = len(user_cards) if user_cards else 0
            
            balance_text = f"""
<b>💰 YOUR BALANCE</b>

Current Balance: <b>${user['balance']:.2f}</b>
Total Winnings: <b>${user['total_winnings']:.2f}</b>
Cards Purchased: <b>{total_cards}</b>

Card Price: <b>${GAME_CONFIG.get('card_price', 2.00):.2f}</b>
Need more funds? Use the buttons below!
"""
            
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="💳 Deposit Funds", callback_data="deposit_menu")],
                    [InlineKeyboardButton(text="🎮 Join Game", callback_data="join_current_game")],
                    [InlineKeyboardButton(text="🏠 Main Menu", callback_data="main_menu")]
                ]
            )
            
            await callback.message.answer(balance_text, parse_mode="HTML", reply_markup=keyboard)
        await callback.answer()
    except Exception as e:
        logger.error(f"Error in check_balance_callback: {e}")
        await callback.answer("❌ Error checking balance", show_alert=True)

@router.callback_query(F.data == "deposit_menu")
async def deposit_menu_callback(callback: CallbackQuery):
    """Show deposit menu"""
    try:
        user = await Database.get_user(callback.from_user.id)
        if not user:
            await callback.answer("Please use /start first!", show_alert=True)
            return
        
        deposit_text = f"""
<b>💳 DEPOSIT FUNDS</b>

<b>Your Current Balance:</b> <code>${user['balance']:.2f}</code>
<b>Card Price:</b> <code>${GAME_CONFIG.get('card_price', 2.00):.2f}</code>

<b>To deposit funds, use:</b>
<code>/deposit &lt;amount&gt; &lt;transaction_id&gt;</code>

<b>Example:</b>
<code>/deposit 100 TXN123456</code>

<b>Payment Methods:</b>
• <b>TeleBirr:</b> +251 9XX XXX XXX
• <b>Chapa:</b> Pay with Chapa App

<b>Minimum Deposit:</b> $10.00
<b>Card Price:</b> ${GAME_CONFIG.get('card_price', 2.00):.2f} each
"""
        
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📱 TeleBirr Info", callback_data="telebirr_info")],
                [InlineKeyboardButton(text="💰 Chapa Info", callback_data="chapa_info")],
                [InlineKeyboardButton(text="💵 Start Deposit", callback_data="start_deposit")],
                [InlineKeyboardButton(text="🎮 Back to Game", callback_data="join_current_game")]
            ]
        )
        
        await callback.message.answer(deposit_text, parse_mode="HTML", reply_markup=keyboard)
        await callback.answer()
    except Exception as e:
        logger.error(f"Error in deposit_menu_callback: {e}")
        await callback.answer("❌ Error showing deposit menu", show_alert=True)

@router.callback_query(F.data == "buy_card_with_preview")
async def buy_card_with_preview_callback(callback: CallbackQuery):
    """Show buy card with preview option"""
    try:
        user = await Database.get_user(callback.from_user.id)
        if not user:
            await callback.answer("Please use /start first!", show_alert=True)
            return
        
        card_price = GAME_CONFIG.get('card_price', 2.00)
        
        buy_text = f"""
<b>🎴 BUY BINGO CARD</b>

<b>Current Balance:</b> <code>${user['balance']:.2f}</code>
<b>Card Price:</b> <code>${card_price:.2f}</code>
<b>Cards Available:</b> 400 unique cards

<b>Features:</b>
• 🎯 Card preview before purchase
• 🔢 Fixed card system (no manipulation)
• 🏆 Fair random assignment
• 📊 See which numbers are called

Click below to see card preview!
"""
        
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=f"👀 Preview Card", callback_data="preview_random_card")],
                [InlineKeyboardButton(text=f"✅ Buy Now (${card_price:.2f})", callback_data="buy_card_now")],
                [InlineKeyboardButton(text="💰 Deposit Funds", callback_data="deposit_menu")],
                [InlineKeyboardButton(text="🏠 Main Menu", callback_data="main_menu")]
            ]
        )
        
        await callback.message.answer(buy_text, parse_mode="HTML", reply_markup=keyboard)
        await callback.answer()
    except Exception as e:
        logger.error(f"Error in buy_card_with_preview_callback: {e}")
        await callback.answer("❌ Error showing buy card menu", show_alert=True)

@router.callback_query(F.data == "preview_random_card")
async def preview_random_card_callback(callback: CallbackQuery):
    """Preview a random bingo card"""
    try:
        # Get a random card for preview
        card_index = CardGenerator.get_random_card_index()
        card_numbers = CardGenerator.get_card_by_index(card_index)
        card_preview = CardGenerator.format_card_display(card_numbers)
        
        preview_text = f"""
<b>🎴 CARD PREVIEW #{card_index}</b>

This is a sample of our 400-card system.
When you buy, you'll get a random card like this.

{card_preview}

<b>Card Price:</b> ${GAME_CONFIG.get('card_price', 2.00):.2f}
<b>Prize Pool:</b> {GAME_CONFIG.get('prize_pool_percent', 85)}% of sales
"""
        
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=f"✅ Buy This Card (${GAME_CONFIG.get('card_price', 2.00):.2f})", callback_data=f"buy_preview_card_{card_index}")],
                [InlineKeyboardButton(text="🔄 New Preview", callback_data="preview_random_card")],
                [InlineKeyboardButton(text="🎮 Join Game First", callback_data="join_current_game")]
            ]
        )
        
        await callback.message.answer(preview_text, parse_mode="Markdown", reply_markup=keyboard)
        await callback.answer()
    except Exception as e:
        logger.error(f"Error in preview_random_card_callback: {e}")
        await callback.answer("❌ Error showing card preview", show_alert=True)

@router.callback_query(F.data.startswith("buy_preview_card_"))
async def buy_preview_card_callback(callback: CallbackQuery):
    """Buy the previewed card"""
    try:
        card_index = int(callback.data.replace("buy_preview_card_", ""))
        
        # Check if user has joined a game first
        from handlers.game import cmd_game
        await cmd_game(callback.message)
        await callback.answer("Please join a game first!", show_alert=True)
        
    except Exception as e:
        logger.error(f"Error in buy_preview_card_callback: {e}")
        await callback.answer("❌ Error purchasing card", show_alert=True)

# Import the cmd_play function
from handlers.game_screen import cmd_play

@router.callback_query(F.data == "play_game")
async def play_game_callback(callback: CallbackQuery):
    """Start playing game - redirect to game screen"""
    try:
        # Get the REAL user ID
        user_id = callback.from_user.id
        
        # DEBUG: Log what we're getting
        logger.info(f"🎮 Play Game callback - User ID: {user_id}, Username: {callback.from_user.username}")
        
        # If Telegram is sending bot's ID, we need to get the real user ID differently
        if user_id == 8471833442:  # Bot's ID
            logger.warning("⚠️ Telegram sent bot ID in callback, need alternative method")
            
            # Method 1: Check if we can get from message
            if callback.message and callback.message.from_user:
                user_id = callback.message.from_user.id
                logger.info(f"✅ Using message sender ID: {user_id}")
            
            # Method 2: For new users, we need to create a session
            else:
                # Generate a temporary user ID based on chat
                chat_id = callback.message.chat.id if callback.message else 0
                user_id = chat_id if chat_id != 8471833442 else 241451670  # Fallback to admin ID
                logger.info(f"🔄 Generated user ID from chat: {user_id}")
        
        # FIXED: Use direct URL instead of importing from config
        web_app_url = "https://branden-bimotored-dakota.ngrok-free.dev/game.html"
        
        # Create the game URL with user ID
        game_url = f"{web_app_url}?user_id={user_id}"
        
        # FIXED: Create an inline keyboard with the Web App button
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(
                        text="🎮 Open Game Screen",
                        web_app=types.WebAppInfo(url=game_url)
                    )
                ],
                [
                    types.InlineKeyboardButton(
                        text="🔄 Refresh",
                        callback_data="play_game"
                    )
                ]
            ]
        )
        
        # Get game info for display
        from database.db import Database
        active_game = await Database.get_active_game()
        
        if active_game:
            prize_pool = active_game.get('prize_pool', 0)
            total_players = active_game.get('total_players', 0)
        else:
            prize_pool = 0
            total_players = 0
        
        # Edit the message with the Web App button
        await callback.message.edit_text(
            "🎮 *HABESHA BINGO - REAL BIRR GAME*\n\n"
            "Click the button below to open the game screen and play!\n"
            "• Buy cards for 2.00 birr each\n"
            "• Win real money prizes\n"
            "• Claim bingo to win!\n\n"
            f"💰 *Current Prize Pool:* {prize_pool:.2f} birr\n"
            f"👥 *Players in Game:* {total_players}\n"
            "🎫 *Card Price:* 2.00 birr\n\n"
            "📍 *Make sure you have enough balance to buy cards!*",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
        
        logger.info(f"✅ Sent game URL to user {user_id}: {game_url}")
        
        # Acknowledge the callback
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Error in play_game_callback: {e}", exc_info=True)
        
        # Try to send an error message
        try:
            await callback.message.answer(
                "❌ Error starting game. Please try again or use /play command directly.",
                parse_mode="Markdown"
            )
        except:
            pass
        
        await callback.answer("❌ Error starting game", show_alert=True)
@router.callback_query(F.data == "join_current_game")
async def join_current_game_callback(callback: CallbackQuery):
    """Join current game - redirect to game handler"""
    try:
        # Import the correct function
        from handlers.game_screen import cmd_game
        await cmd_game(callback.message)
        await callback.answer()
    except Exception as e:
        logger.error(f"Error in join_current_game_callback: {e}")
        await callback.answer("❌ Error joining game", show_alert=True)

@router.callback_query(F.data == "my_cards")
async def my_cards_callback(callback: CallbackQuery):
    """Show user's cards - redirect to cards handler"""
    try:
        # Import the correct function from user handler
        from handlers.user import view_cards_command
        await view_cards_command(callback.message)
        await callback.answer()
    except Exception as e:
        logger.error(f"Error in my_cards_callback: {e}")
        await callback.answer("❌ Error loading cards", show_alert=True)

@router.callback_query(F.data == "game_info")
async def game_info_callback(callback: CallbackQuery):
    """Show game info - redirect to game handler"""
    try:
        # Import the correct function
        from handlers.game_screen import cmd_game
        await cmd_game(callback.message)
        await callback.answer()
    except Exception as e:
        logger.error(f"Error in game_info_callback: {e}")
        await callback.answer("❌ Error loading game info", show_alert=True)

@router.callback_query(F.data == "my_stats")
async def my_stats_callback(callback: CallbackQuery):
    """Show user stats from callback"""
    try:
        user = await Database.get_user(callback.from_user.id)
        if not user:
            await callback.answer("Please use /start first!", show_alert=True)
            return
        
        # Get user cards
        user_cards = await Database.get_user_cards(user['user_id'])
        total_cards = len(user_cards) if user_cards else 0
        
        win_rate = (user['games_won'] / user['total_games'] * 100) if user['total_games'] > 0 else 0
        avg_win = (user['total_winnings'] / user['games_won']) if user['games_won'] > 0 else 0
        
        stats = f"""
<b>📊 YOUR STATISTICS</b>

<b>Balance:</b> ${user['balance']:.2f}
<b>Games Played:</b> {user['total_games']}
<b>Games Won:</b> {user['games_won']}
<b>Total Winnings:</b> ${user['total_winnings']:.2f}
<b>Cards Purchased:</b> {total_cards}

<b>Win Rate:</b> {win_rate:.1f}%
<b>Avg Win:</b> ${avg_win:.2f}
"""
        
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Refresh", callback_data="my_stats")],
                [InlineKeyboardButton(text="🎴 My Cards", callback_data="my_cards")],
                [InlineKeyboardButton(text="🏆 Leaderboard", callback_data="show_leaderboard")],
                [InlineKeyboardButton(text="🏠 Main Menu", callback_data="main_menu")]
            ]
        )
        
        await callback.message.answer(stats, parse_mode="HTML", reply_markup=keyboard)
        await callback.answer()
    except Exception as e:
        logger.error(f"Error in my_stats_callback: {e}")
        await callback.answer("❌ Error showing stats", show_alert=True)

@router.callback_query(F.data == "show_leaderboard")
async def show_leaderboard_callback(callback: CallbackQuery):
    """Show leaderboard from callback"""
    try:
        leaderboard = await Database.get_leaderboard(limit=10)
        
        if not leaderboard:
            await callback.message.answer("📊 <b>No leaderboard data available yet!</b>", parse_mode="HTML")
            await callback.answer()
            return
        
        leaderboard_text = "<b>🏆 TOP PLAYERS</b>\n\n"
        
        for i, player in enumerate(leaderboard, 1):
            if i == 1:
                medal = "🥇"
            elif i == 2:
                medal = "🥈"
            elif i == 3:
                medal = "🥉"
            else:
                medal = f"{i}."
            
            username = player['username'] or player['full_name'] or f"User {player['user_id']}"
            leaderboard_text += f"{medal} {escape_html_safe(username)}\n"
            leaderboard_text += f"   Winnings: <b>${player['total_winnings']:.2f}</b>\n"
            leaderboard_text += f"   Games Won: {player['games_won']}\n\n"
        
        leaderboard_text += "<i>Keep playing to climb the ranks!</i> 🎮"
        
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Refresh", callback_data="show_leaderboard")],
                [InlineKeyboardButton(text="📊 My Stats", callback_data="my_stats")],
                [InlineKeyboardButton(text="🎮 Play Now", callback_data="join_current_game")],
                [InlineKeyboardButton(text="🏠 Main Menu", callback_data="main_menu")]
            ]
        )
        
        await callback.message.answer(leaderboard_text, parse_mode="HTML", reply_markup=keyboard)
        await callback.answer()
    except Exception as e:
        logger.error(f"Error in show_leaderboard_callback: {e}")
        await callback.message.answer("❌ Error loading leaderboard.", parse_mode="HTML")
        await callback.answer()

@router.callback_query(F.data == "refresh_profile")
async def refresh_profile_callback(callback: CallbackQuery):
    """Refresh profile from callback"""
    try:
        user = await Database.get_user(callback.from_user.id)
        
        if not user:
            await callback.answer("Please use /start first!", show_alert=True)
            return
        
        # Get user cards
        user_cards = await Database.get_user_cards(user['user_id'])
        total_cards = len(user_cards) if user_cards else 0
        
        win_rate = (user['games_won'] / user['total_games'] * 100) if user['total_games'] > 0 else 0
        avg_win = (user['total_winnings'] / user['games_won']) if user['games_won'] > 0 else 0
        
        created_date = user['created_at'].strftime('%Y-%m-%d') if user.get('created_at') else 'N/A'
        
        profile = f"""
<b>👤 PLAYER PROFILE</b>

<b>📊 Statistics:</b>
💰 Balance: <b>${user['balance']:.2f}</b>
🎮 Games Played: <b>{user['total_games']}</b>
🏆 Games Won: <b>{user['games_won']}</b>
💵 Total Winnings: <b>${user['total_winnings']:.2f}</b>
🎫 Cards Purchased: <b>{total_cards}</b>

<b>📈 Performance:</b>
Win Rate: <b>{win_rate:.1f}%</b>
Avg Win: <b>${avg_win:.2f}</b>

<b>Account Created:</b> {created_date}
"""
        
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Refresh", callback_data="refresh_profile")],
                [InlineKeyboardButton(text="🎴 My Cards", callback_data="my_cards")],
                [InlineKeyboardButton(text="📜 History", callback_data="transaction_history")],
                [InlineKeyboardButton(text="🏠 Main Menu", callback_data="main_menu")]
            ]
        )
        
        await callback.message.edit_text(profile, parse_mode="HTML", reply_markup=keyboard)
        await callback.answer("✅ Profile refreshed!")
    except Exception as e:
        logger.error(f"Error in refresh_profile_callback: {e}")
        await callback.answer("❌ Error refreshing profile", show_alert=True)

@router.callback_query(F.data == "transaction_history")
async def transaction_history_callback(callback: CallbackQuery):
    """Show transaction history"""
    try:
        user_id = callback.from_user.id
        transactions = await Database.get_user_transactions(user_id, limit=5)
        
        if not transactions:
            history = """
<b>💳 TRANSACTION HISTORY</b>

No transactions yet.
Make your first deposit or buy a card!

<b>Card Price:</b> ${card_price:.2f}
<b>Join a game first with /game</b>
""".format(card_price=GAME_CONFIG.get('card_price', 2.00))
        else:
            history = "<b>💳 TRANSACTION HISTORY</b>\n\n"
            history += "<b>Recent Transactions:</b>\n\n"
            
            for i, tx in enumerate(transactions, 1):
                emoji = "📥" if tx['amount'] > 0 else "📤"
                sign = "+" if tx['amount'] > 0 else "-"
                color = "🟢" if tx['amount'] > 0 else "🔴"
                
                history += f"{color} <b>{tx['type'].title()}</b>\n"
                history += f"   {emoji} {sign}${abs(tx['amount']):.2f}\n"
                history += f"   📝 {escape_html_safe(tx['description'] or 'No description')}\n"
                history += f"   🕒 {tx['created_at'].strftime('%Y-%m-%d %H:%M')}\n\n"
        
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Refresh", callback_data="transaction_history")],
                [InlineKeyboardButton(text="💳 Deposit", callback_data="deposit_menu")],
                [InlineKeyboardButton(text="🎮 Play Game", callback_data="join_current_game")],
                [InlineKeyboardButton(text="🏠 Main Menu", callback_data="main_menu")]
            ]
        )
        
        await callback.message.answer(history, parse_mode="HTML", reply_markup=keyboard)
        await callback.answer()
    except Exception as e:
        logger.error(f"Error in transaction_history_callback: {e}")
        await callback.answer("❌ Error showing history", show_alert=True)

@router.callback_query(F.data == "telebirr_info")
async def telebirr_info_callback(callback: CallbackQuery):
    """Show Telebirr instructions"""
    try:
        info = """
<b>📱 TELEBIRR PAYMENT</b>

<b>Steps to deposit:</b>
1. Open Telebirr App
2. Go to <b>Send Money</b>
3. Send to: <code>+251 9XX XXX XXX</code>
4. Reference: <code>BINGO-{user_id}</code>
5. Use /deposit command after sending

<b>Note:</b> Include your user ID in the reference.
Your user ID: <code>{user_id}</code>

<b>Minimum Deposit:</b> $10.00
<b>Card Price:</b> ${card_price:.2f}
""".format(user_id=callback.from_user.id, card_price=GAME_CONFIG.get('card_price', 2.00))
        
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="💵 Start Deposit", callback_data="start_deposit")],
                [InlineKeyboardButton(text="🎮 Back to Game", callback_data="join_current_game")],
                [InlineKeyboardButton(text="🏠 Main Menu", callback_data="main_menu")]
            ]
        )
        
        await callback.message.answer(info, parse_mode="HTML", reply_markup=keyboard)
        await callback.answer()
    except Exception as e:
        logger.error(f"Error in telebirr_info_callback: {e}")
        await callback.answer("❌ Error showing Telebirr info", show_alert=True)

@router.callback_query(F.data == "chapa_info")
async def chapa_info_callback(callback: CallbackQuery):
    """Show Chapa instructions"""
    try:
        info = """
<b>💰 CHAPA PAYMENT</b>

<b>Steps to deposit:</b>
1. Visit: <b>https://chapa.com</b>
2. Merchant: <b>Habesha Bingo</b>
3. Amount: Enter desired amount
4. Include your user ID in reference
5. Use /deposit command after payment

<b>Note:</b> Payments may take 1-24 hours to verify.
Your user ID: <code>{user_id}</code>

<b>Minimum Deposit:</b> $10.00
<b>Card Price:</b> ${card_price:.2f}
""".format(user_id=callback.from_user.id, card_price=GAME_CONFIG.get('card_price', 2.00))
        
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="💵 Start Deposit", callback_data="start_deposit")],
                [InlineKeyboardButton(text="🎮 Back to Game", callback_data="join_current_game")],
                [InlineKeyboardButton(text="🏠 Main Menu", callback_data="main_menu")]
            ]
        )
        
        await callback.message.answer(info, parse_mode="HTML", reply_markup=keyboard)
        await callback.answer()
    except Exception as e:
        logger.error(f"Error in chapa_info_callback: {e}")
        await callback.answer("❌ Error showing Chapa info", show_alert=True)

@router.callback_query(F.data == "start_deposit")
async def start_deposit_callback(callback: CallbackQuery):
    """Start deposit process"""
    try:
        await callback.message.answer(
            "<b>💳 START DEPOSIT</b>\n\n"
            "Use the command:\n\n"
            "<code>/deposit &lt;amount&gt; &lt;transaction_id&gt;</code>\n\n"
            "<b>Example:</b>\n"
            "<code>/deposit 100 TXN123456</code>\n\n"
            "<b>Card Price:</b> ${card_price:.2f}\n"
            "<b>Join game first:</b> Use /game\n\n"
            "After sending money, use this command with the transaction ID."
            .format(card_price=GAME_CONFIG.get('card_price', 2.00)),
            parse_mode="HTML"
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"Error in start_deposit_callback: {e}")
        await callback.answer("❌ Error starting deposit", show_alert=True)

@router.message(Command("history"))
async def history_command(message: Message):
    """Show game history"""
    try:
        games = await Database.get_game_history(limit=5)
        
        if not games:
            await message.answer("📜 <b>No game history available yet!</b>", parse_mode="HTML")
            return
        
        history_text = "<b>📜 GAME HISTORY</b>\n\n"
        history_text += "<b>Recent Games:</b>\n\n"
        
        for game in games:
            history_text += f"🎮 <b>Game {escape_html_safe(game['game_id'])}</b>\n"
            history_text += f"   Status: {game['status'].title()}\n"
            history_text += f"   Players: {game.get('total_players', 0)}\n"
            history_text += f"   Prize Pool: <b>${game.get('prize_pool', 0):.2f}</b>\n"
            history_text += f"   Winners: {game.get('winner_count', 0)}\n\n"
        
        history_text += "Use /game to join current game!"
        
        await message.answer(history_text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error in history_command: {e}")
        await message.answer("❌ Error loading game history.", parse_mode="HTML")

@router.message(Command("leaderboard"))
async def leaderboard_command(message: Message):
    """Show leaderboard"""
    try:
        leaderboard = await Database.get_leaderboard(limit=10)
        
        if not leaderboard:
            await message.answer("🏆 <b>No leaderboard data available yet!</b>", parse_mode="HTML")
            return
        
        leaderboard_text = "<b>🏆 TOP PLAYERS</b>\n\n"
        
        for i, player in enumerate(leaderboard, 1):
            if i == 1:
                medal = "🥇"
            elif i == 2:
                medal = "🥈"
            elif i == 3:
                medal = "🥉"
            else:
                medal = f"{i}."
            
            username = player['username'] or player['full_name'] or f"User {player['user_id']}"
            leaderboard_text += f"{medal} {escape_html_safe(username)}\n"
            leaderboard_text += f"   Winnings: <b>${player['total_winnings']:.2f}</b>\n"
            leaderboard_text += f"   Games Won: {player['games_won']}\n\n"
        
        leaderboard_text += "<i>Keep playing to climb the ranks!</i> 🎮"
        
        await message.answer(leaderboard_text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error in leaderboard_command: {e}")
        await message.answer("❌ Error loading leaderboard.", parse_mode="HTML")

@router.callback_query(F.data == "main_menu")
async def main_menu_callback(callback: CallbackQuery):
    """Return to main menu"""
    try:
        # Check card system status
        cards = CardGenerator.get_all_cards()
        card_count = len(cards) if cards else 0
        card_status = f"✅ {card_count}/400 Cards" if card_count == 400 else f"⚠️ {card_count}/400"
        
        welcome = f"""
<b>🏠 MAIN MENU</b>

<b>Card System:</b> {card_status}
<b>Card Price:</b> ${GAME_CONFIG.get('card_price', 2.00):.2f}

Choose an option below:
"""
        
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="🎮 Play Game", callback_data="play_game"),
                    InlineKeyboardButton(text="💰 Balance", callback_data="check_balance")
                ],
                [
                    InlineKeyboardButton(text="🎴 Buy Card", callback_data="buy_card_with_preview"),
                    InlineKeyboardButton(text="🃏 My Cards", callback_data="my_cards")
                ],
                [
                    InlineKeyboardButton(text="📊 My Stats", callback_data="my_stats"),
                    InlineKeyboardButton(text="🏆 Leaderboard", callback_data="show_leaderboard")
                ],
                [
                    InlineKeyboardButton(text="❓ Help", callback_data="help_menu")
                ]
            ]
        )
        
        await callback.message.edit_text(welcome, parse_mode="HTML", reply_markup=keyboard)
        await callback.answer("🏠 Main menu")
    except Exception as e:
        logger.error(f"Error in main_menu_callback: {e}")
        await callback.answer("❌ Error returning to main menu", show_alert=True)

@router.callback_query(F.data == "help_menu")
async def help_menu_callback(callback: CallbackQuery):
    """Show help menu"""
    try:
        cards = CardGenerator.get_all_cards()
        card_status = f"✅ {len(cards)}/400 cards loaded" if cards and len(cards) == 400 else "⚠️ Loading cards..."
        
        help_text = f"""
<b>❓ HELP & SUPPORT</b>

<b>Card System:</b> {card_status}
• 400 unique pre-generated cards
• Fair random assignment
• Card preview before purchase

<b>Quick Commands:</b>
• /start - Show main menu
• /game - Join current game
• /cards - View your cards
• /balance - Check balance
• /buy - Buy bingo card
• /cardinfo - Card system info

<b>Need Help?</b>
• Game Issues: Use the commands above
• Payment Issues: Contact admin
• Card System: Use /cardinfo

<b>Game Rules:</b>
• Join game before countdown ends
• Numbers called every 5 seconds
• Complete line to win (row/column/diagonal)
• {GAME_CONFIG.get('prize_pool_percent', 85)}% to prize pool
"""
        
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🎮 Join Game", callback_data="join_current_game")],
                [InlineKeyboardButton(text="💰 Check Balance", callback_data="check_balance")],
                [InlineKeyboardButton(text="🏠 Main Menu", callback_data="main_menu")]
            ]
        )
        
        await callback.message.answer(help_text, parse_mode="HTML", reply_markup=keyboard)
        await callback.answer()
    except Exception as e:
        logger.error(f"Error in help_menu_callback: {e}")
        await callback.answer("❌ Error showing help", show_alert=True)

@router.message(Command("commands"))
async def commands_command(message: Message):
    """List all available commands"""
    try:
        cards = CardGenerator.get_all_cards()
        card_status = f"✅ {len(cards)}/400 cards" if cards and len(cards) == 400 else "⚠️ Loading..."
        
        commands_list = f"""
<b>📋 AVAILABLE COMMANDS</b>

<b>Card System:</b> {card_status}

<b>Basic Commands:</b>
• /start - Start the bot
• /help - Show help information
• /commands - This command list

<b>Account Commands:</b>
• /balance - Check your balance
• /profile - View your profile
• /history - Game history

<b>Game Commands:</b>
• /game - Join current game
• /cards - View your cards
• /buy - Buy bingo card
• /cardinfo - Card system info

<b>Payment Commands:</b>
• /deposit - Deposit funds
• /withdraw - Withdraw winnings

<b>Admin Commands:</b>
• /admin - Admin panel (admin only)
• /creategame - Create new game
• /stopgame - Stop current game
"""
        
        await message.answer(commands_list, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error in commands_command: {e}")
        await message.answer("❌ Error showing commands.", parse_mode="HTML")

# Error handler
@router.errors()
async def error_handler(event, error):
    """Handle errors"""
    logger.error(f"Error in start handler: {error}")
    return True