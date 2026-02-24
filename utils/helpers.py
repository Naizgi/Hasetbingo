from aiogram.types import Message
from datetime import datetime

def format_money(amount: int) -> str:
    """Format money nicely"""
    return f"{amount} Birr"

def get_username(message: Message) -> str:
    """Safe username getter"""
    if message.from_user.username:
        return f"@{message.from_user.username}"
    return message.from_user.full_name

def now():
    """Return current datetime"""
    return datetime.utcnow()

def chunk_list(data, size):
    """Split list into chunks"""
    for i in range(0, len(data), size):
        yield data[i:i + size]
