from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

def main_menu():
    # Buttons that always appear below the text input
    keyboard = ReplyKeyboardMarkup(
        resize_keyboard=True,      # Makes buttons smaller and neat
        one_time_keyboard=False    # Keep the keyboard persistent
    )

    # Add your menu buttons
    keyboard.add(KeyboardButton("🎲 Play Bingo"))
    keyboard.add(KeyboardButton("💰 My Balance"), KeyboardButton("📊 Stats"))
    keyboard.add(KeyboardButton("ℹ️ Help"))

    return keyboard
