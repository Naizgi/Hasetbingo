# utils/bingo_utils.py
import random
import json
from typing import List, Dict

class BingoUtils:
    """Bingo game utilities"""
    
    @staticmethod
    def generate_card() -> List[int]:
        """Generate a random bingo card (5x5 grid)"""
        # Bingo has numbers 1-75
        # Each column has specific ranges:
        # B: 1-15, I: 16-30, N: 31-45, G: 46-60, O: 61-75
        
        card = []
        ranges = [
            (1, 15),    # B
            (16, 30),   # I
            (31, 45),   # N
            (46, 60),   # G
            (61, 75)    # O
        ]
        
        for start, end in ranges:
            # Pick 5 unique numbers for each column
            column_numbers = random.sample(range(start, end + 1), 5)
            card.extend(column_numbers)
        
        # The center square is usually free (marked as 0)
        card[12] = 0  # Center position (row 3, col 3 in 5x5 grid)
        
        return card
    
    @staticmethod
    def string_to_card(card_data: str) -> List[int]:
        """Convert string to card list"""
        try:
            return json.loads(card_data)
        except:
            return []
    
    @staticmethod
    def check_bingo(card_numbers: List[int], called_numbers: List[int]) -> bool:
        """Check if card has bingo"""
        if len(card_numbers) != 25:
            return False
        
        # Convert to set for faster checking
        called_set = set(called_numbers)
        
        # Check rows
        for i in range(0, 25, 5):
            row = card_numbers[i:i+5]
            # Skip checking the center (free space)
            row_to_check = [num for num in row if num != 0]
            if all(num in called_set for num in row_to_check):
                return True
        
        # Check columns
        for col in range(5):
            column = [card_numbers[row*5 + col] for row in range(5)]
            column_to_check = [num for num in column if num != 0]
            if all(num in called_set for num in column_to_check):
                return True
        
        # Check diagonal top-left to bottom-right
        diag1 = [card_numbers[i] for i in [0, 6, 12, 18, 24]]
        diag1_to_check = [num for num in diag1 if num != 0]
        if all(num in called_set for num in diag1_to_check):
            return True
        
        # Check diagonal top-right to bottom-left
        diag2 = [card_numbers[i] for i in [4, 8, 12, 16, 20]]
        diag2_to_check = [num for num in diag2 if num != 0]
        if all(num in called_set for num in diag2_to_check):
            return True
        
        return False
    
    @staticmethod
    def check_bingo_with_pattern(card_numbers: List[int], called_numbers: List[int]):
        """Check if card has bingo and return pattern"""
        if len(card_numbers) != 25:
            return False, None
        
        # Convert to set for faster checking
        called_set = set(called_numbers)
        
        # Check rows
        for row in range(5):
            row_indices = [row*5 + col for col in range(5)]
            row_numbers = [card_numbers[i] for i in row_indices]
            row_to_check = [num for num in row_numbers if num != 0]
            if all(num in called_set for num in row_to_check):
                return True, f"row_{row+1}"
        
        # Check columns
        for col in range(5):
            col_indices = [row*5 + col for row in range(5)]
            col_numbers = [card_numbers[i] for i in col_indices]
            col_to_check = [num for num in col_numbers if num != 0]
            if all(num in called_set for num in col_to_check):
                return True, f"column_{col+1}"
        
        # Check diagonal top-left to bottom-right
        diag1_indices = [0, 6, 12, 18, 24]
        diag1_numbers = [card_numbers[i] for i in diag1_indices]
        diag1_to_check = [num for num in diag1_numbers if num != 0]
        if all(num in called_set for num in diag1_to_check):
            return True, "diagonal_tl_br"
        
        # Check diagonal top-right to bottom-left
        diag2_indices = [4, 8, 12, 16, 20]
        diag2_numbers = [card_numbers[i] for i in diag2_indices]
        diag2_to_check = [num for num in diag2_numbers if num != 0]
        if all(num in called_set for num in diag2_to_check):
            return True, "diagonal_tr_bl"
        
        # Check four corners
        corners = [0, 4, 20, 24]
        corners_numbers = [card_numbers[i] for i in corners]
        if all(num in called_set for num in corners_numbers):
            return True, "four_corners"
        
        # Check blackout (full card)
        card_to_check = [num for num in card_numbers if num != 0]
        if all(num in called_set for num in card_to_check):
            return True, "blackout"
        
        return False, None
    
    @staticmethod
    def format_card(card_numbers: List[int]) -> str:
        """Format card for display"""
        if len(card_numbers) != 25:
            return "Invalid card"
        
        # BINGO headers
        headers = ["B", "I", "N", "G", "O"]
        rows = []
        
        for row in range(5):
            row_text = ""
            for col in range(5):
                index = row * 5 + col
                num = card_numbers[index]
                if num == 0:
                    row_text += " FREE"
                else:
                    row_text += f" {num:3d}"
            rows.append(row_text)
        
        return "\n".join(rows)
    
    @staticmethod
    def get_number_emoji(number: int) -> str:
        """Get emoji for bingo number"""
        if 1 <= number <= 15:
            return "🅱️"  # B
        elif 16 <= number <= 30:
            return "ℹ️"   # I
        elif 31 <= number <= 45:
            return "🎌"   # N
        elif 46 <= number <= 60:
            return "🌀"   # G
        elif 61 <= number <= 75:
            return "🅾️"   # O
        else:
            return "❓"


class AntiCheat:
    """Anti-cheat measures for bingo"""
    
    @staticmethod
    def validate_card(card_numbers: List[int]) -> bool:
        """Validate if card is legitimate"""
        if len(card_numbers) != 25:
            return False
        
        # Check center is free
        if card_numbers[12] != 0:
            return False
        
        # Check columns have valid ranges
        column_ranges = [
            (1, 15),    # B
            (16, 30),   # I
            (31, 45),   # N
            (46, 60),   # G
            (61, 75)    # O
        ]
        
        for col in range(5):
            numbers_in_col = []
            for row in range(5):
                index = row * 5 + col
                num = card_numbers[index]
                if num != 0:  # Skip free space
                    numbers_in_col.append(num)
            
            # Check each column has numbers in correct range
            start, end = column_ranges[col]
            for num in numbers_in_col:
                if not (start <= num <= end):
                    return False
            
            # Check no duplicates in column
            if len(set(numbers_in_col)) != len(numbers_in_col):
                return False
        
        return True
    
    @staticmethod
    async def log_suspicious_activity(user_id: int, game_id: str, reason: str, admin_id: int = None):
        """Log suspicious activity"""
        try:
            from database.db import Database  # Add import here
            import logging
            logger = logging.getLogger(__name__)
            
            await Database.log_cheat_attempt(user_id, game_id, reason, admin_id)
        except Exception as e:
            logger.error(f"Error logging cheat attempt: {e}")


class GameUIBuilder:
    """Build game UI"""
    
    @staticmethod
    def create_game_screen(game: Dict, card_data: Dict, called_numbers: List[int]) -> str:
        """Create game screen"""
        game_id = game.get('game_id', 'N/A')
        status = game.get('status', 'waiting').title()
        prize_pool = game.get('prize_pool', 0)
        players = game.get('total_players', 0)
        
        text = f"🎮 <b>BINGO GAME {game_id}</b>\n\n"
        text += f"Status: <b>{status}</b>\n"
        text += f"Players: <b>{players}</b>\n"
        text += f"Prize Pool: <b>${prize_pool:.2f}</b>\n\n"
        
        if status == 'Starting' and game.get('current_number'):
            text += f"⏰ Starting in: <b>{game['current_number']} seconds</b>\n\n"
        
        if called_numbers:
            text += f"Numbers Called: <b>{len(called_numbers)}</b>\n"
            text += f"Last 5: {', '.join(str(n) for n in called_numbers[-5:])}\n\n"
        
        text += "Use /card to view your bingo card."
        
        return text