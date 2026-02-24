from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from database.db import Database
from config import GAME_CONFIG
import logging

logger = logging.getLogger(__name__)

router = Router()

# ADD CONSTANTS FOR CURRENCY
CURRENCY = "birr"  # ADDED: Currency symbol
CARD_PRICE = GAME_CONFIG.get('card_price', 10.00)  # ADDED: Get price from config

@router.message(Command("buy"))
async def buy_card_command(message: types.Message):
    """Buy bingo cards command"""
    try:
        # Get number of cards to buy (default 1)
        text = message.text or ""
        parts = text.split()
        
        if len(parts) > 1:
            try:
                quantity = int(parts[1])
                if quantity < 1 or quantity > 10:
                    await message.answer("❌ Please enter a number between 1 and 10.")
                    return
            except ValueError:
                await message.answer("❌ Please enter a valid number.")
                return
        else:
            quantity = 1
        
        user_id = message.from_user.id
        active_game = await Database.get_active_game()
        
        if not active_game:
            await message.answer(
                "🎮 <b>No Active Game</b>\n\n"
                "There's no active game at the moment.\n"
                "Please wait for admin to start a game!"
            )
            return
        
        # Check user balance
        user_data = await Database.get_user(user_id)
        if not user_data:
            await Database.create_user(user_id, message.from_user.username or f"user_{user_id}", 
                                      message.from_user.full_name or "Player")
            user_data = await Database.get_user(user_id)
        
        # CHANGED: Use CARD_PRICE constant instead of hardcoded value
        total_cost = CARD_PRICE * quantity
        
        if user_data.get('balance', 0) < total_cost:
            await message.answer(
                f"❌ <b>Insufficient Balance</b>\n\n"
                f"💰 <b>Your balance:</b> {user_data.get('balance', 0):.0f} {CURRENCY}\n"  # CHANGED
                f"💳 <b>Required:</b> {total_cost:.0f} {CURRENCY}\n"  # CHANGED
                f"🎫 <b>Cards:</b> {quantity} × {CARD_PRICE:.0f} {CURRENCY}\n\n"  # CHANGED
                "Please deposit funds using /deposit command."
            )
            return
        
        # Show confirmation
        builder = InlineKeyboardBuilder()
        builder.row(
            types.InlineKeyboardButton(
                text=f"✅ Confirm Purchase ({total_cost:.0f} {CURRENCY})",  # CHANGED
                callback_data=f"confirm_buy:{quantity}"
            )
        )
        builder.row(
            types.InlineKeyboardButton(
                text="❌ Cancel",
                callback_data="cancel_buy"
            )
        )
        
        # CHANGED: Update all currency displays
        await message.answer(
            f"🛒 <b>Purchase Confirmation</b>\n\n"
            f"🎫 <b>Quantity:</b> {quantity} card{'s' if quantity > 1 else ''}\n"
            f"💰 <b>Price per card:</b> {CARD_PRICE:.0f} {CURRENCY}\n"  # CHANGED
            f"💵 <b>Total cost:</b> {total_cost:.0f} {CURRENCY}\n"  # CHANGED
            f"🏦 <b>Your balance:</b> {user_data.get('balance', 0):.0f} {CURRENCY}\n\n"  # CHANGED
            f"🎮 <b>Game:</b> {active_game['game_id'][:8]}...\n"
            f"🏆 <b>Prize Pool:</b> {active_game.get('prize_pool', 0):.0f} {CURRENCY}\n\n"  # CHANGED
            "Click confirm to purchase:",
            reply_markup=builder.as_markup()
        )
        
    except Exception as e:
        logger.error(f"Error in buy_card_command: {e}")
        await message.answer(
            "❌ Could not process purchase request.\n"
            "Please try again or contact admin."
        )

@router.message(Command("cards"))
async def view_cards_command(message: types.Message):
    """View user's cards command"""
    try:
        user_id = message.from_user.id
        user_cards = await Database.get_user_cards(user_id)
        
        if not user_cards:
            # CHANGED: Update price display
            await message.answer(
                f"🎫 <b>No Bingo Cards</b>\n\n"
                f"You don't have any bingo cards yet.\n"
                f"Buy cards using <code>/buy</code> command!\n\n"
                f"💰 <b>Price per card:</b> {CARD_PRICE:.0f} {CURRENCY}\n"  # CHANGED
                f"🎯 <b>Tip:</b> More cards = better chances!"
            )
            return
        
        # Group cards by game
        cards_by_game = {}
        for card in user_cards:
            game_id = card['game_id']
            if game_id not in cards_by_game:
                game = await Database.get_game(game_id)
                cards_by_game[game_id] = {
                    'game': game,
                    'cards': []
                }
            cards_by_game[game_id]['cards'].append(card)
        
        # Display cards
        response = "🎫 <b>Your Bingo Cards</b>\n\n"
        
        for game_id, game_data in cards_by_game.items():
            game = game_data['game']
            cards = game_data['cards']
            
            response += f"🎮 <b>Game:</b> {game_id[:8]}...\n"
            response += f"📊 <b>Status:</b> {game.get('status', 'unknown').upper()}\n"
            response += f"🎫 <b>Your Cards:</b> {len(cards)}\n\n"
            
            for i, card in enumerate(cards[:3], 1):  # Show first 3 cards
                card_index = card.get('card_index', i)
                has_bingo = "✅" if card.get('has_bingo') else "⏳"
                # CHANGED: Update prize display
                prize = f"{card.get('prize_won', 0):.0f} {CURRENCY}" if card.get('prize_won') else "Playing"
                
                response += f"{has_bingo} <b>Card #{card_index}:</b> {prize}\n"
            
            if len(cards) > 3:
                response += f"... and {len(cards) - 3} more cards\n"
            
            response += "\n"
        
        response += "🎮 <b>Use /play to view cards in game interface!</b>"
        
        await message.answer(response)
        
    except Exception as e:
        logger.error(f"Error in view_cards_command: {e}")
        await message.answer(
            "🎫 <b>My Cards</b>\n\n"
            "Use command: <code>/cards</code>\n\n"
            "Shows all your bingo cards\n"
            "across different games."
        )

# Add callback handlers for the buy confirmation
@router.callback_query(F.data.startswith("confirm_buy:"))
async def confirm_buy_callback(callback: types.CallbackQuery):
    """Confirm card purchase"""
    try:
        quantity = int(callback.data.split(":")[1])
        user_id = callback.from_user.id
        
        # Process purchase
        from utils.game_manager import GameManager
        active_game = await Database.get_active_game()
        
        if not active_game:
            await callback.message.answer("❌ No active game found.")
            await callback.answer()
            return
        
        # Process purchase for each card
        purchased_cards = []
        for i in range(quantity):
            result = await GameManager.player_join_game(user_id, active_game['game_id'])
            if result.get('success'):
                purchased_cards.append(result)
        
        if purchased_cards:
            # Success message
            total_cost = CARD_PRICE * quantity  # CHANGED: Use constant
            
            response = f"✅ <b>Purchase Successful!</b>\n\n"
            response += f"🎫 <b>Cards Purchased:</b> {quantity}\n"
            response += f"💰 <b>Total Cost:</b> {total_cost:.0f} {CURRENCY}\n"  # CHANGED
            response += f"🎮 <b>Game:</b> {active_game['game_id'][:8]}...\n\n"
            
            if len(purchased_cards) == 1:
                response += f"🎯 <b>Your Card #:</b> {purchased_cards[0].get('card_index', 1)}\n"
            
            response += "🎮 <b>Use /play to start playing!</b>"
            
            await callback.message.answer(response)
        else:
            await callback.message.answer("❌ Failed to purchase cards. Please try again.")
        
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Error in confirm_buy_callback: {e}")
        await callback.message.answer("❌ Error processing purchase.")
        await callback.answer()

@router.callback_query(F.data == "cancel_buy")
async def cancel_buy_callback(callback: types.CallbackQuery):
    """Cancel purchase"""
    await callback.message.answer("❌ Purchase cancelled.")
    await callback.answer()