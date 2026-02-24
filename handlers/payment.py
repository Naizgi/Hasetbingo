from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command, CommandObject
from database.db import Database
from config import GAME_CONFIG, PAYMENT_CONFIG
import logging

logger = logging.getLogger(__name__)
router = Router()

@router.message(Command("deposit"))
async def deposit_command(message: Message, command: CommandObject):
    """Deposit funds"""
    args = command.args
    
    if not args:
        await message.answer(
            f"<b>💳 DEPOSIT FUNDS</b>\n\n"
            f"<b>Payment Methods:</b>\n"
            f"• TeleBirr: {PAYMENT_CONFIG['telebirr_number']}\n"
            f"• CBE: {PAYMENT_CONFIG['cbe_account']}\n\n"
            f"<b>Minimum Deposit:</b> ${GAME_CONFIG['min_deposit']:.2f}\n\n"
            f"<b>Usage:</b> /deposit &lt;amount&gt; &lt;transaction_id&gt;\n"
            f"<b>Example:</b> /deposit 100 TXN123456\n\n"
            f"After sending money, use this command with transaction ID.",
            parse_mode="HTML"
        )
        return
    
    try:
        parts = args.split()
        if len(parts) < 2:
            await message.answer(
                "❌ <b>Invalid format!</b>\n\n"
                "Correct format: /deposit &lt;amount&gt; &lt;transaction_id&gt;\n"
                "Example: /deposit 100 TXN123456",
                parse_mode="HTML"
            )
            return
        
        amount = float(parts[0])
        transaction_id = parts[1]
        
        if amount < GAME_CONFIG['min_deposit']:
            await message.answer(
                f"❌ <b>Minimum deposit is ${GAME_CONFIG['min_deposit']:.2f}</b>",
                parse_mode="HTML"
            )
            return
        
        # Create payment record
        payment_id = await Database.create_payment(
            user_id=message.from_user.id,
            amount=amount,
            provider='TeleBirr',
            transaction_id=transaction_id
        )
        
        await message.answer(
            f"✅ <b>Deposit request submitted!</b>\n\n"
            f"Amount: <b>${amount:.2f}</b>\n"
            f"Transaction ID: <code>{transaction_id}</code>\n"
            f"Payment ID: <code>{payment_id}</code>\n\n"
            "Please wait for admin approval. You will be notified.",
            parse_mode="HTML"
        )
        
    except ValueError:
        await message.answer(
            "❌ <b>Invalid amount!</b>\n\n"
            "Amount must be a number.\n"
            "Example: /deposit 100 TXN123456",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Error in deposit_command: {e}")
        await message.answer("❌ An error occurred. Please try again.")

@router.message(Command("withdraw"))
async def withdraw_command(message: Message, command: CommandObject):
    """Withdraw funds"""
    args = command.args
    
    if not args:
        user = await Database.get_user(message.from_user.id)
        
        if not user:
            await message.answer("Please use /start first!")
            return
        
        await message.answer(
            f"<b>💸 WITHDRAW FUNDS</b>\n\n"
            f"Your Balance: <b>${user['balance']:.2f}</b>\n"
            f"Minimum Withdrawal: <b>${GAME_CONFIG['min_withdrawal']:.2f}</b>\n\n"
            f"<b>Methods:</b> TeleBirr, BankTransfer\n\n"
            f"<b>Usage:</b> /withdraw &lt;amount&gt; &lt;method&gt;\n"
            f"<b>Example:</b> /withdraw 100 TeleBirr\n\n"
            f"Note: Withdrawals take 24 hours to process.",
            parse_mode="HTML"
        )
        return
    
    await message.answer(
        "⚠️ <b>Withdrawal feature coming soon!</b>\n\n"
        "For now, contact admin for withdrawals.",
        parse_mode="HTML"
    )

@router.message(Command("payments"))
async def view_payments_command(message: Message):
    """View pending payments (admin only)"""
    from handlers.admin import is_admin
    
    if not is_admin(message.from_user.id):
        await message.answer("❌ You are not authorized.")
        return
    
    pending_payments = await Database.get_pending_payments()
    
    if not pending_payments:
        await message.answer("✅ No pending payments.", parse_mode="HTML")
        return
    
    payments_text = f"<b>💰 PENDING PAYMENTS ({len(pending_payments)})</b>\n\n"
    
    for payment in pending_payments[:5]:
        payments_text += f"ID: <code>{payment['id']}</code>\n"
        payments_text += f"User: {payment['full_name']} (@{payment['username']})\n"
        payments_text += f"Amount: <b>${payment['amount']:.2f}</b>\n"
        payments_text += f"Transaction: <code>{payment['transaction_id']}</code>\n"
        payments_text += f"Date: {payment['created_at'].strftime('%Y-%m-%d %H:%M')}\n"
        payments_text += f"Provider: {payment.get('provider', 'N/A')}\n\n"
    
    keyboard = InlineKeyboardMarkup(row_width=2)
    buttons = []
    
    for payment in pending_payments[:4]:
        buttons.append(
            InlineKeyboardButton(
                text=f"✅ ${payment['amount']}",
                callback_data=f"approve_payment_{payment['id']}"
            )
        )
    
    keyboard.add(*buttons)
    keyboard.add(InlineKeyboardButton(text="🔄 Refresh", callback_data="refresh_payments"))
    
    await message.answer(payments_text, parse_mode="HTML", reply_markup=keyboard)

@router.callback_query(F.data.startswith("approve_payment_"))
async def approve_payment_callback(callback: CallbackQuery):
    """Approve payment"""
    from handlers.admin import is_admin
    
    if not is_admin(callback.from_user.id):
        await callback.message.answer("❌ You are not authorized.")
        await callback.answer()
        return
    
    payment_id = int(callback.data.split("_")[-1])
    
    success = await Database.approve_payment(payment_id, callback.from_user.id)
    
    if success:
        await callback.message.answer(f"✅ Payment {payment_id} approved!", parse_mode="HTML")
        # Refresh payments list
        await view_payments_command(callback.message)
    else:
        await callback.message.answer(f"❌ Failed to approve payment {payment_id}", parse_mode="HTML")
    
    await callback.answer()

@router.callback_query(F.data == "refresh_payments")
async def refresh_payments_callback(callback: CallbackQuery):
    """Refresh payments"""
    await view_payments_command(callback.message)
    await callback.answer("✅ Refreshed!")