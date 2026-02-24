import random
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def generate_board():
    numbers = list(range(1, 26))
    random.shuffle(numbers)
    board = [numbers[i*5:(i+1)*5] for i in range(5)]
    return board

def board_to_keyboard(board, marked=None):
    kb = InlineKeyboardMarkup(row_width=5)
    for i, row in enumerate(board):
        buttons = []
        for j, num in enumerate(row):
            text = str(num)
            if marked and marked[i][j]:
                text = f"✅{num}"
            buttons.append(InlineKeyboardButton(text=text, callback_data=f"mark_{num}"))
        kb.row(*buttons)
    return kb

def check_win(marked):
    # Rows
    for row in marked:
        if all(row):
            return True
    # Columns
    for col in range(5):
        if all(marked[row][col] for row in range(5)):
            return True
    # Diagonals
    if all(marked[i][i] for i in range(5)) or all(marked[i][4-i] for i in range(5)):
        return True
    return False
