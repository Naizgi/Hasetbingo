import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command, CommandObject
from database.db import Database
from utils.game_manager import game_manager
from config import ADMIN_IDS, GAME_CONFIG
import shortuuid
import json

logger = logging.getLogger(__name__)
router = Router()

def is_admin(user_id: int) -> bool:
    """Check if user is admin"""
    return user_id in ADMIN_IDS

# ==================== ADMIN MAIN MENU ====================
@router.message(Command("admin"))
async def admin_command(message: Message):
    """Admin main menu"""
    try:
        if not is_admin(message.from_user.id):
            await message.answer("❌ Admin only command")
            return
        
        admin_menu = """
<b>👑 ADMIN PANEL</b>

<b>🎮 Game Management:</b>
• /creategame - Create new game
• /startgame - Start game countdown
• /stopgame - Stop current game
• /listgames - List all games
• /gameinfo - Game details

<b>💰 Payment Management:</b>
• /pendingpayments - View pending deposits
• /approvepayment - Approve payment
• /rejectpayment - Reject payment

<b>👥 User Management:</b>
• /allusers - List all users
• /userinfo - User details
• /addbalance - Add balance to user
• /searchuser - Search users

<b>📊 Statistics:</b>
• /stats - System statistics
• /leaderboard - Top players
• /gamehistory - Game history

<b>⚙️ System:</b>
• /broadcast - Send message to all users
• /maintenance - Toggle maintenance mode
• /logs - View recent logs
"""
        
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="🎮 Create Game", callback_data="admin_create_game"),
                    InlineKeyboardButton(text="⏹️ Stop Game", callback_data="admin_stop_game")
                ],
                [
                    InlineKeyboardButton(text="💰 Pending Payments", callback_data="admin_pending_payments"),
                    InlineKeyboardButton(text="👥 All Users", callback_data="admin_all_users")
                ],
                [
                    InlineKeyboardButton(text="📊 Statistics", callback_data="admin_stats"),
                    InlineKeyboardButton(text="⚙️ Settings", callback_data="admin_settings")
                ],
                [
                    InlineKeyboardButton(text="🔄 Refresh", callback_data="admin_refresh"),
                    InlineKeyboardButton(text="❌ Close", callback_data="admin_close")
                ]
            ]
        )
        
        await message.answer(admin_menu, parse_mode="HTML", reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"Error in admin_command: {e}")
        await message.answer("❌ Admin error occurred")

# ==================== GAME MANAGEMENT ====================
@router.message(Command("creategame"))
async def create_game_command(message: Message):
    """Create a new bingo game"""
    try:
        if not is_admin(message.from_user.id):
            await message.answer("❌ Admin only command")
            return
        
        # Generate unique game ID
        game_id = f"c{shortuuid.uuid()[:4]}"
        
        # Create game
        success = await Database.create_game(game_id, message.from_user.id)
        
        if success:
            await message.answer(
                f"✅ <b>Game Created Successfully!</b>\n\n"
                f"🎮 <b>Game ID:</b> <code>{game_id}</code>\n"
                f"📊 <b>Status:</b> Waiting\n"
                f"💰 <b>Card Price:</b> {GAME_CONFIG['card_price']:.2f} birr\n"
                f"👤 <b>Created by:</b> Admin\n\n"
                f"Use /startgame to begin countdown",
                parse_mode="HTML"
            )
            
            # Start the game automatically if using game_manager
            if hasattr(game_manager, 'create_continuous_game'):
                await game_manager.create_continuous_game(game_id)
                logger.info(f"Continuous game {game_id} created")
        else:
            await message.answer("❌ Failed to create game")
            
    except Exception as e:
        logger.error(f"Error creating game: {e}")
        await message.answer("❌ Error creating game")

@router.message(Command("startgame"))
async def start_game_command(message: Message, command: CommandObject):
    """Start game countdown"""
    try:
        if not is_admin(message.from_user.id):
            await message.answer("❌ Admin only command")
            return
        
        game_id = command.args
        
        if not game_id:
            # Get current active game
            game = await Database.get_active_game()
            if not game:
                await message.answer("❌ No active game found. Use /creategame first")
                return
            game_id = game['game_id']
        
        # Start countdown using game_manager instance
        if hasattr(game_manager, 'start_game_countdown'):
            success = await game_manager.start_game_countdown(game_id)
        else:
            # Fallback to direct database update
            await Database.update_game_status(game_id, 'active')
            success = True
        
        if success:
            await message.answer(
                f"✅ <b>Game Countdown Started!</b>\n\n"
                f"🎮 <b>Game ID:</b> <code>{game_id}</code>\n"
                f"⏱️ <b>Status:</b> Active\n\n"
                f"Game is now active",
                parse_mode="HTML"
            )
        else:
            await message.answer(f"❌ Failed to start game {game_id}")
            
    except Exception as e:
        logger.error(f"Error starting game: {e}")
        await message.answer(f"❌ Error starting game: {str(e)}")

@router.message(Command("stopgame"))
async def stop_game_command(message: Message, command: CommandObject):
    """Stop a game"""
    try:
        if not is_admin(message.from_user.id):
            await message.answer("❌ Admin only command")
            return
        
        game_id = command.args
        
        if not game_id:
            # Get current active game
            game = await Database.get_active_game()
            if not game:
                await message.answer("❌ No active game found")
                return
            game_id = game['game_id']
        
        # Stop game using game_manager instance
        if hasattr(game_manager, 'stop_game'):
            success, message_text = await game_manager.stop_game(game_id)
        else:
            # Fallback to direct database update
            await Database.update_game_status(game_id, 'cancelled')
            success = True
            message_text = "Game stopped"
        
        if success:
            await message.answer(
                f"🛑 <b>Game Stopped!</b>\n\n"
                f"🎮 <b>Game ID:</b> <code>{game_id}</code>\n"
                f"📊 <b>Status:</b> Cancelled\n"
                f"⏹️ <b>Stopped by:</b> Admin\n\n"
                f"{message_text}",
                parse_mode="HTML"
            )
        else:
            await message.answer(f"❌ Failed to stop game {game_id}: {message_text}")
            
    except Exception as e:
        logger.error(f"Error stopping game: {e}")
        await message.answer(f"❌ Error stopping game: {str(e)}")

@router.message(Command("listgames"))
async def list_games_command(message: Message):
    """List all games"""
    try:
        if not is_admin(message.from_user.id):
            await message.answer("❌ Admin only command")
            return
        
        games = await Database.get_active_games()
        history = await Database.get_game_history(limit=5)
        
        response = "<b>🎮 GAME LIST</b>\n\n"
        
        if games:
            response += "<b>Active Games:</b>\n"
            for game in games:
                players = await Database.count_game_players(game['game_id'])
                response += f"• {game['game_id']} - {game['status']} - {players} players\n"
        else:
            response += "No active games\n"
        
        response += "\n<b>Recent Games:</b>\n"
        if history:
            for game in history:
                response += f"• {game['game_id']} - {game['status']} - {game.get('total_players', 0)} players - {game.get('prize_pool', 0):.2f} birr\n"
        else:
            response += "No game history\n"
        
        await message.answer(response, parse_mode="HTML")
        
    except Exception as e:
        logger.error(f"Error listing games: {e}")
        await message.answer(f"❌ Error listing games: {str(e)}")

# ==================== PAYMENT MANAGEMENT ====================
@router.message(Command("pendingpayments"))
async def pending_payments_command(message: Message):
    """View pending payments - SIMPLIFIED VERSION"""
    try:
        if not is_admin(message.from_user.id):
            await message.answer("❌ Admin only command")
            return
        
        # For now, show a simplified version
        response = "<b>💰 PAYMENT MANAGEMENT</b>\n\n"
        response += "Payment system is being implemented.\n"
        response += "Use /addbalance to manually add balance to users."
        
        await message.answer(response, parse_mode="HTML")
        
    except Exception as e:
        logger.error(f"Error showing pending payments: {e}")
        await message.answer("❌ Error showing payments")

@router.message(Command("approvepayment"))
async def approve_payment_command(message: Message, command: CommandObject):
    """Approve a payment - SIMPLIFIED"""
    try:
        if not is_admin(message.from_user.id):
            await message.answer("❌ Admin only command")
            return
        
        if not command.args:
            await message.answer("Usage: /approvepayment &lt;payment_id&gt;")
            return
        
        await message.answer("✅ Payment approval system coming soon")
            
    except Exception as e:
        logger.error(f"Error approving payment: {e}")
        await message.answer("❌ Error approving payment")

# ==================== USER MANAGEMENT ====================
@router.message(Command("allusers"))
async def all_users_command(message: Message):
    """List all users - SIMPLIFIED VERSION"""
    try:
        if not is_admin(message.from_user.id):
            await message.answer("❌ Admin only command")
            return
        
        # Get recent users from database
        from database.db import Database
        # We'll need to implement get_recent_users method or use a workaround
        # For now, just show a message
        
        response = "<b>👥 USER MANAGEMENT</b>\n\n"
        response += "Use /userinfo &lt;user_id&gt; to view specific user details.\n"
        response += "Use /addbalance to adjust user balance."
        
        await message.answer(response, parse_mode="HTML")
        
    except Exception as e:
        logger.error(f"Error listing users: {e}")
        await message.answer("❌ Error listing users")

@router.message(Command("userinfo"))
async def user_info_command(message: Message, command: CommandObject):
    """Get user information"""
    try:
        if not is_admin(message.from_user.id):
            await message.answer("❌ Admin only command")
            return
        
        if not command.args:
            await message.answer("Usage: /userinfo &lt;user_id&gt;")
            return
        
        user_id = int(command.args)
        user = await Database.get_user(user_id)
        
        if not user:
            await message.answer(f"❌ User {user_id} not found")
            return
        
        response = f"<b>👤 USER INFORMATION</b>\n\n"
        response += f"<b>User ID:</b> {user['user_id']}\n"
        response += f"<b>Username:</b> {user.get('username', 'N/A')}\n"
        response += f"<b>Full Name:</b> {user.get('full_name', 'N/A')}\n"
        response += f"<b>Balance:</b> {user.get('balance', 0):.2f} birr\n"
        response += f"<b>Status:</b> {user.get('status', 'active')}\n"
        response += f"<b>Created:</b> {user.get('created_at', 'N/A')}\n"
        response += f"<b>Last Active:</b> {user.get('last_active', 'N/A')}\n"
        
        # Get user cards
        user_cards = await Database.get_user_cards(user_id)
        response += f"<b>Cards Purchased:</b> {len(user_cards) if user_cards else 0}\n"
        
        # Get user transactions
        transactions = await Database.get_user_transactions(user_id, limit=5)
        response += f"<b>Recent Transactions:</b> {len(transactions) if transactions else 0}\n"
        
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="💰 Add Balance", callback_data=f"add_balance_{user_id}"),
                ]
            ]
        )
        
        await message.answer(response, parse_mode="HTML", reply_markup=keyboard)
        
    except ValueError:
        await message.answer("❌ Invalid user ID")
    except Exception as e:
        logger.error(f"Error getting user info: {e}")
        await message.answer("❌ Error getting user info")

@router.message(Command("addbalance"))
async def add_balance_command(message: Message, command: CommandObject):
    """Add balance to user"""
    try:
        if not is_admin(message.from_user.id):
            await message.answer("❌ Admin only command")
            return
        
        if not command.args:
            await message.answer("Usage: /addbalance &lt;user_id&gt; &lt;amount&gt; [reason]")
            return
        
        args = command.args.split()
        if len(args) < 2:
            await message.answer("Usage: /addbalance &lt;user_id&gt; &lt;amount&gt; [reason]")
            return
        
        user_id = int(args[0])
        amount = float(args[1])
        reason = " ".join(args[2:]) if len(args) > 2 else "Admin adjustment"
        
        # Check if user exists
        user = await Database.get_user(user_id)
        if not user:
            await message.answer(f"❌ User {user_id} not found")
            return
        
        # Update balance
        success = await Database.update_balance_with_transaction(
            user_id=user_id,
            amount=amount,
            transaction_type='admin_adjustment',
            description=f"Admin: {reason}"
        )
        
        if success:
            # Get updated user info
            user = await Database.get_user(user_id)
            await message.answer(
                f"✅ <b>Balance Added!</b>\n\n"
                f"<b>User:</b> {user.get('username', f'User {user_id}')}\n"
                f"<b>Amount Added:</b> +{amount:.2f} birr\n"
                f"<b>New Balance:</b> {user['balance']:.2f} birr\n"
                f"<b>Reason:</b> {reason}",
                parse_mode="HTML"
            )
        else:
            await message.answer("❌ Failed to add balance")
            
    except ValueError:
        await message.answer("❌ Invalid user ID or amount")
    except Exception as e:
        logger.error(f"Error adding balance: {e}")
        await message.answer("❌ Error adding balance")

# ==================== STATISTICS ====================
@router.message(Command("stats"))
async def stats_command(message: Message):
    """Show system statistics"""
    try:
        if not is_admin(message.from_user.id):
            await message.answer("❌ Admin only command")
            return
        
        response = "<b>📊 SYSTEM STATISTICS</b>\n\n"
        
        # Get active games
        games = await Database.get_active_games()
        response += f"<b>🎮 Active Games:</b> {len(games) if games else 0}\n"
        
        # Get total house balance
        house_balance = await Database.get_total_house_balance()
        response += f"<b>💰 House Balance:</b> {house_balance:.2f} birr\n"
        
        # Get recent completed games
        completed_games = await Database.get_recent_completed_games(limit=5)
        response += f"<b>🏆 Recent Games:</b> {len(completed_games) if completed_games else 0}\n"
        
        # Card system stats
        try:
            from utils.card_generator import CardGenerator
            cards = CardGenerator.get_all_cards()
            response += f"<b>🃏 Card System:</b> {len(cards) if cards else 0}/400 cards loaded\n"
        except:
            response += "<b>🃏 Card System:</b> Not loaded\n"
        
        # Active connections
        try:
            from web_server import active_connections
            response += f"<b>🌐 Active Connections:</b> {len(active_connections) if 'active_connections' in locals() else 0}\n"
        except:
            response += "<b>🌐 Web Server:</b> Running\n"
        
        await message.answer(response, parse_mode="HTML")
        
    except Exception as e:
        logger.error(f"Error showing stats: {e}")
        await message.answer("❌ Error showing statistics")

@router.message(Command("gamehistory"))
async def game_history_command(message: Message):
    """Show game history"""
    try:
        if not is_admin(message.from_user.id):
            await message.answer("❌ Admin only command")
            return
        
        history = await Database.get_game_history(limit=10)
        
        if not history:
            await message.answer("📜 No game history found")
            return
        
        response = "<b>📜 GAME HISTORY (Last 10)</b>\n\n"
        
        for i, game in enumerate(history, 1):
            response += f"<b>{i}. {game['game_id']}</b>\n"
            response += f"   Status: {game['status']}\n"
            response += f"   Players: {game.get('total_players', 0)}\n"
            if game.get('winner_username'):
                response += f"   Winner: {game['winner_username']}\n"
                response += f"   Prize: {game.get('winner_payout', 0):.2f} birr\n"
            response += f"   Created: {game.get('created_at', 'N/A')[:19] if game.get('created_at') else 'N/A'}\n"
            response += "   ────────────────────\n"
        
        await message.answer(response, parse_mode="HTML")
        
    except Exception as e:
        logger.error(f"Error showing game history: {e}")
        await message.answer(f"❌ Error showing game history: {str(e)}")

@router.message(Command("broadcast"))
async def broadcast_command(message: Message, command: CommandObject):
    """Broadcast message to all users - SIMPLIFIED"""
    try:
        if not is_admin(message.from_user.id):
            await message.answer("❌ Admin only command")
            return
        
        if not command.args:
            await message.answer("Usage: /broadcast &lt;message&gt;")
            return
        
        await message.answer(
            f"📢 <b>Broadcast Preview:</b>\n\n{command.args}\n\n"
            f"<i>Broadcast feature will be implemented soon</i>",
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Error broadcasting: {e}")
        await message.answer("❌ Error broadcasting")

# ==================== CALLBACK HANDLERS ====================
@router.callback_query(F.data == "admin_create_game")
async def admin_create_game_callback(callback: CallbackQuery):
    """Create game from callback"""
    try:
        await create_game_command(callback.message)
        await callback.answer()
    except Exception as e:
        logger.error(f"Error in admin_create_game_callback: {e}")
        await callback.answer("❌ Error", show_alert=True)

@router.callback_query(F.data == "admin_stop_game")
async def admin_stop_game_callback(callback: CallbackQuery):
    """Stop game from callback"""
    try:
        game = await Database.get_active_game()
        if game:
            if hasattr(game_manager, 'stop_game'):
                success, msg = await game_manager.stop_game(game['game_id'])
                if success:
                    await callback.message.answer(f"✅ Stopped game: {game['game_id']}")
                else:
                    await callback.message.answer(f"❌ Failed: {msg}")
            else:
                await Database.update_game_status(game['game_id'], 'cancelled')
                await callback.message.answer(f"✅ Stopped game: {game['game_id']}")
        else:
            await callback.message.answer("❌ No active game")
        await callback.answer()
    except Exception as e:
        logger.error(f"Error in admin_stop_game_callback: {e}")
        await callback.answer("❌ Error", show_alert=True)

@router.callback_query(F.data == "admin_pending_payments")
async def admin_pending_payments_callback(callback: CallbackQuery):
    """Show pending payments from callback"""
    try:
        await pending_payments_command(callback.message)
        await callback.answer()
    except Exception as e:
        logger.error(f"Error in admin_pending_payments_callback: {e}")
        await callback.answer("❌ Error", show_alert=True)

@router.callback_query(F.data == "admin_all_users")
async def admin_all_users_callback(callback: CallbackQuery):
    """Show all users from callback"""
    try:
        await all_users_command(callback.message)
        await callback.answer()
    except Exception as e:
        logger.error(f"Error in admin_all_users_callback: {e}")
        await callback.answer("❌ Error", show_alert=True)

@router.callback_query(F.data == "admin_stats")
async def admin_stats_callback(callback: CallbackQuery):
    """Show stats from callback"""
    try:
        await stats_command(callback.message)
        await callback.answer()
    except Exception as e:
        logger.error(f"Error in admin_stats_callback: {e}")
        await callback.answer("❌ Error", show_alert=True)

@router.callback_query(F.data.startswith("add_balance_"))
async def add_balance_callback(callback: CallbackQuery):
    """Add balance from callback"""
    try:
        user_id = int(callback.data.replace("add_balance_", ""))
        
        # Ask for amount
        await callback.message.answer(
            f"Please enter the amount to add for user {user_id}:\n"
            f"Format: /addbalance {user_id} &lt;amount&gt; [reason]"
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"Error in add_balance_callback: {e}")
        await callback.answer("❌ Error", show_alert=True)

@router.callback_query(F.data.startswith("approve_"))
async def approve_payment_callback(callback: CallbackQuery):
    """Approve payment from callback"""
    try:
        payment_id = int(callback.data.replace("approve_", ""))
        await callback.message.answer(f"Payment approval system coming soon")
        await callback.answer("✅ Feature coming soon")
    except Exception as e:
        logger.error(f"Error approving payment: {e}")
        await callback.answer("❌ Error", show_alert=True)

@router.callback_query(F.data.startswith("reject_"))
async def reject_payment_callback(callback: CallbackQuery):
    """Reject payment from callback"""
    try:
        payment_id = int(callback.data.replace("reject_", ""))
        await callback.message.answer(f"Payment rejection system coming soon")
        await callback.answer("✅ Feature coming soon")
    except Exception as e:
        logger.error(f"Error rejecting payment: {e}")
        await callback.answer("❌ Error", show_alert=True)

@router.callback_query(F.data == "admin_refresh")
async def admin_refresh_callback(callback: CallbackQuery):
    """Refresh admin panel"""
    try:
        await admin_command(callback.message)
        await callback.answer("🔄 Refreshed!")
    except Exception as e:
        logger.error(f"Error in admin_refresh_callback: {e}")
        await callback.answer("❌ Error", show_alert=True)

@router.callback_query(F.data == "admin_close")
async def admin_close_callback(callback: CallbackQuery):
    """Close admin panel"""
    try:
        await callback.message.delete()
        await callback.answer("✅ Closed")
    except Exception as e:
        logger.error(f"Error in admin_close_callback: {e}")
        await callback.answer("❌ Error", show_alert=True)

# ==================== ERROR HANDLER ====================
@router.errors()
async def admin_error_handler(event, error):
    """Handle admin errors"""
    logger.error(f"Admin error: {error}")
    return True