# utils/card_generator.py
import json
import random
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

class CardGenerator:
    _all_cards = None
    
    @classmethod
    def load_all_cards(cls):
        """Load all cards from JSON file"""
        if cls._all_cards is None:
            try:
                cards_file = Path('data/bingo_cards.json')
                if cards_file.exists():
                    with open(cards_file, 'r') as f:
                        cls._all_cards = json.load(f)
                    logger.info(f"[OK] Loaded {len(cls._all_cards)} cards from JSON file")
                else:
                    logger.error("[ERROR] bingo_cards.json not found in data/ directory")
                    cls._all_cards = []
            except Exception as e:
                logger.error(f"[ERROR] Error loading cards: {e}")
                cls._all_cards = []
        
        return cls._all_cards
    
    @classmethod
    def get_all_cards(cls):
        """Alias for load_all_cards for compatibility"""
        return cls.load_all_cards()
    
    @classmethod
    def get_card_by_id(cls, card_id):
        """Get a specific card by ID (1-400)"""
        all_cards = cls.load_all_cards()
        if 1 <= card_id <= len(all_cards):
            return all_cards[card_id - 1]  # cards are 1-indexed
        logger.error(f"[ERROR] Invalid card_id: {card_id}, total cards: {len(all_cards)}")
        return None
    
    @classmethod
    def get_card_by_index(cls, index):
        """Get card by index (0-399) - for compatibility with GameManager"""
        all_cards = cls.load_all_cards()
        if 0 <= index < len(all_cards):
            return all_cards[index]  # 0-indexed
        logger.error(f"[ERROR] Invalid card index: {index}, total cards: {len(all_cards)}")
        
        # Fallback: generate a card if index is out of range
        logger.warning(f"[WARNING] Card index {index} out of range. Generating random card instead.")
        return cls.generate_card()
    
    @classmethod
    def get_random_card(cls):
        """Get a random card from available cards"""
        all_cards = cls.load_all_cards()
        if all_cards:
            return random.choice(all_cards)
        # Fallback: generate a card
        return cls.generate_card()
    
    @classmethod
    def generate_card(cls):
        """Generate a single bingo card (fallback)"""
        columns = {
            'B': list(range(1, 16)),
            'I': list(range(16, 31)),
            'N': list(range(31, 46)),
            'G': list(range(46, 61)),
            'O': list(range(61, 76))
        }
        
        card = []
        for col_idx, (col_name, col_numbers) in enumerate(columns.items()):
            # Randomly select 5 numbers for each column
            selected = random.sample(col_numbers, 5)
            
            # For column N (index 2), the middle is FREE
            if col_idx == 2:
                # Make the 3rd position (index 2) the FREE space
                for row_idx in range(5):
                    if row_idx == 2:  # Middle row
                        card.append(0)  # FREE space
                    else:
                        card.append(selected.pop())
            else:
                card.extend(selected)
        
        return card
    
    @classmethod
    def validate_card(cls, card):
        """Validate if a card is a proper bingo card"""
        if not isinstance(card, list) or len(card) != 25:
            return False
        
        # Check FREE space is in position 12 (index 12)
        if card[12] != 0:
            return False
        
        # Validate all numbers are between 1-75 (except FREE space)
        for i, num in enumerate(card):
            if i == 12:  # FREE space
                continue
            if not (1 <= num <= 75):
                return False
        
        return True
    
    @classmethod
    def format_card_for_display(cls, card):
        """Format card for display in text format"""
        if not card:
            return ""
        
        lines = []
        for row in range(5):
            row_numbers = []
            for col in range(5):
                idx = row * 5 + col
                num = card[idx]
                if num == 0:
                    row_numbers.append("[FREE]")
                else:
                    row_numbers.append(f"{num:2}")
            lines.append(" ".join(row_numbers))
        
        return "\n".join(lines)
    
    @classmethod
    def format_winning_card_with_pattern(cls, card_numbers, called_numbers, pattern):
        """Format card showing winning pattern"""
        if len(card_numbers) != 25:
            return "Invalid card"
        
        # Handle pattern - it could be string or dict
        if isinstance(pattern, str):
            # Convert string pattern name to positions
            pattern_positions = cls.get_pattern_positions(pattern)
        elif isinstance(pattern, dict):
            pattern_positions = pattern.get('positions', [])
        else:
            pattern_positions = []
        
        rows = []
        for row in range(5):
            row_text = ""
            for col in range(5):
                index = row * 5 + col
                num = card_numbers[index]
                
                # Mark winning positions
                if index in pattern_positions:
                    if num == 0:
                        row_text += " [FREE] "
                    else:
                        row_text += f" *{num:2d}*"
                else:
                    if num == 0:
                        row_text += " FREE"
                    elif num in called_numbers:
                        row_text += f" ({num:2d})"
                    else:
                        row_text += f" {num:3d}"
            rows.append(row_text)
        
        return "\n".join(rows)
    
    @staticmethod
    def get_pattern_positions(pattern_name):
        """Convert pattern name to list of positions"""
        patterns = {
            "row_1": [0, 1, 2, 3, 4],
            "row_2": [5, 6, 7, 8, 9],
            "row_3": [10, 11, 12, 13, 14],
            "row_4": [15, 16, 17, 18, 19],
            "row_5": [20, 21, 22, 23, 24],
            "column_1": [0, 5, 10, 15, 20],
            "column_2": [1, 6, 11, 16, 21],
            "column_3": [2, 7, 12, 17, 22],
            "column_4": [3, 8, 13, 18, 23],
            "column_5": [4, 9, 14, 19, 24],
            "diagonal_tl_br": [0, 6, 12, 18, 24],
            "diagonal_tr_bl": [4, 8, 12, 16, 20],
            "four_corners": [0, 4, 20, 24],
            "blackout": list(range(25))
        }
        
        # Remove center (12) from blackout since it's free
        if pattern_name == "blackout":
            blackout_positions = patterns["blackout"]
            if 12 in blackout_positions:
                blackout_positions.remove(12)
        
        return patterns.get(pattern_name, [])