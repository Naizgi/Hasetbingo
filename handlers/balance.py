from aiogram import Router, types
from aiogram.filters import Command
from database.db import Database

router = Router()

@router.message(Command("balance"))
async def cmd_balance(message: types.Message):
    """Check user balance"""
    user_id = message.from_user.id
    
    # Get user balance
    user_data = await Database.get_user_with_balance(user_id)
    
    if user_data:
        balance = user_data.get('balance', 0)
        await message.answer(
            f"💰 **Your Balance:** {balance:.2f} birr\n\n"
            f"💳 **To Deposit:**\n"
            f"Contact admin with:\n"
            f"• Your user ID: `{user_id}`\n"
            f"• Deposit amount\n"
            f"• Screenshot of payment",
            parse_mode="Markdown"
        )
    else:
        await message.answer("❌ User not found. Please use /start first.")