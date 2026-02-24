# utils/bingo_checker.py
import asyncio
import random
from datetime import datetime, timedelta  # Add this import
from typing import Dict, List, Optional, Tuple, Set, Any
import json
import logging

logger = logging.getLogger(__name__)

class BingoChecker:
    """Bingo card checking and verification system"""
    
    @staticmethod
    def is_bingo(card_numbers: List[int], called_numbers: List[int]) -> bool:
        """Check if a bingo card has bingo with the called numbers"""
        try:
            if len(card_numbers) != 25:
                logger.error(f"Invalid card length: {len(card_numbers)}")
                return False
            
            # Create a grid from the card numbers
            grid = [card_numbers[i:i+5] for i in range(0, 25, 5)]
            
            # Convert called numbers to set for faster lookup
            called_set = set(called_numbers)
            
            # Check all possible bingo patterns
            patterns = BingoChecker.get_winning_patterns()
            
            for pattern in patterns:
                if BingoChecker.check_pattern(grid, pattern, called_set):
                    return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error checking bingo: {e}")
            return False
    
    @staticmethod
    def check_pattern(grid: List[List[int]], pattern: List[Tuple[int, int]], called_set: Set[int]) -> bool:
        """Check if a specific pattern is completed"""
        for row, col in pattern:
            if grid[row][col] not in called_set:
                return False
        return True
    
    @staticmethod
    def get_winning_patterns() -> List[List[Tuple[int, int]]]:
        """Get all possible winning patterns in bingo"""
        patterns = []
        
        # Rows (5 horizontal lines)
        for row in range(5):
            pattern = [(row, col) for col in range(5)]
            patterns.append(pattern)
        
        # Columns (5 vertical lines)
        for col in range(5):
            pattern = [(row, col) for row in range(5)]
            patterns.append(pattern)
        
        # Diagonals (2 diagonal lines)
        diagonal1 = [(i, i) for i in range(5)]
        diagonal2 = [(i, 4 - i) for i in range(5)]
        patterns.extend([diagonal1, diagonal2])
        
        # Four corners
        corners = [(0, 0), (0, 4), (4, 0), (4, 4)]
        patterns.append(corners)
        
        # Center cross (includes free space at (2,2))
        center_cross = [(1, 2), (2, 1), (2, 2), (2, 3), (3, 2)]
        patterns.append(center_cross)
        
        # Full house (all 25 numbers)
        full_house = [(row, col) for row in range(5) for col in range(5)]
        patterns.append(full_house)
        
        # Letter patterns
        # Letter B
        letter_b = [(0, 0), (0, 1), (0, 2), (0, 3), (0, 4),
                    (1, 0), (1, 2), (1, 4),
                    (2, 0), (2, 2), (2, 4),
                    (3, 0), (3, 2), (3, 4),
                    (4, 0), (4, 1), (4, 2), (4, 3), (4, 4)]
        patterns.append(letter_b)
        
        # Letter I
        letter_i = [(0, 2), (1, 2), (2, 2), (3, 2), (4, 2)]
        patterns.append(letter_i)
        
        # Letter N
        letter_n = [(0, 0), (1, 0), (2, 0), (3, 0), (4, 0),
                    (1, 1), (2, 2), (3, 3),
                    (0, 4), (1, 4), (2, 4), (3, 4), (4, 4)]
        patterns.append(letter_n)
        
        # Letter G
        letter_g = [(0, 1), (0, 2), (0, 3),
                    (1, 0), (1, 4),
                    (2, 0), (2, 2), (2, 3), (2, 4),
                    (3, 0), (3, 4),
                    (4, 1), (4, 2), (4, 3)]
        patterns.append(letter_g)
        
        # Letter O
        letter_o = [(0, 1), (0, 2), (0, 3),
                    (1, 0), (1, 4),
                    (2, 0), (2, 4),
                    (3, 0), (3, 4),
                    (4, 1), (4, 2), (4, 3)]
        patterns.append(letter_o)
        
        return patterns
    
    @staticmethod
    def get_winning_pattern_name(pattern: List[Tuple[int, int]]) -> str:
        """Get the name of a winning pattern"""
        pattern_set = set(pattern)
        
        # Check for specific patterns
        if len(pattern) == 5:
            # Check if it's a row
            rows = set([pos[0] for pos in pattern])
            if len(rows) == 1:
                row_num = list(rows)[0] + 1
                return f"Row {row_num}"
            
            # Check if it's a column
            cols = set([pos[1] for pos in pattern])
            if len(cols) == 1:
                col_num = list(cols)[0] + 1
                return f"Column {col_num}"
            
            # Check if it's diagonal
            if all(pos[0] == pos[1] for pos in pattern):
                return "Diagonal (Top-Left to Bottom-Right)"
            if all(pos[0] + pos[1] == 4 for pos in pattern):
                return "Diagonal (Top-Right to Bottom-Left)"
        
        # Four corners
        corners = [(0, 0), (0, 4), (4, 0), (4, 4)]
        if set(corners).issubset(pattern_set):
            return "Four Corners"
        
        # Center cross
        center_cross = [(1, 2), (2, 1), (2, 2), (2, 3), (3, 2)]
        if set(center_cross).issubset(pattern_set):
            return "Center Cross"
        
        # Full house
        if len(pattern) == 25:
            return "Full House"
        
        # Letter patterns
        letter_patterns = {
            "Letter B": [(0, 0), (0, 1), (0, 2), (0, 3), (0, 4),
                         (1, 0), (1, 2), (1, 4),
                         (2, 0), (2, 2), (2, 4),
                         (3, 0), (3, 2), (3, 4),
                         (4, 0), (4, 1), (4, 2), (4, 3), (4, 4)],
            "Letter I": [(0, 2), (1, 2), (2, 2), (3, 2), (4, 2)],
            "Letter N": [(0, 0), (1, 0), (2, 0), (3, 0), (4, 0),
                         (1, 1), (2, 2), (3, 3),
                         (0, 4), (1, 4), (2, 4), (3, 4), (4, 4)],
            "Letter G": [(0, 1), (0, 2), (0, 3),
                         (1, 0), (1, 4),
                         (2, 0), (2, 2), (2, 3), (2, 4),
                         (3, 0), (3, 4),
                         (4, 1), (4, 2), (4, 3)],
            "Letter O": [(0, 1), (0, 2), (0, 3),
                         (1, 0), (1, 4),
                         (2, 0), (2, 4),
                         (3, 0), (3, 4),
                         (4, 1), (4, 2), (4, 3)]
        }
        
        for name, letter_pattern in letter_patterns.items():
            if set(letter_pattern).issubset(pattern_set):
                return name
        
        return "Custom Pattern"
    
    @staticmethod
    def find_winning_pattern(card_numbers: List[int], called_numbers: List[int]) -> Optional[List[Tuple[int, int]]]:
        """Find which pattern completed the bingo"""
        try:
            if len(card_numbers) != 25:
                return None
            
            # Create a grid from the card numbers
            grid = [card_numbers[i:i+5] for i in range(0, 25, 5)]
            
            # Convert called numbers to set for faster lookup
            called_set = set(called_numbers)
            
            # Check all possible bingo patterns
            patterns = BingoChecker.get_winning_patterns()
            
            for pattern in patterns:
                if BingoChecker.check_pattern(grid, pattern, called_set):
                    return pattern
            
            return None
            
        except Exception as e:
            logger.error(f"Error finding winning pattern: {e}")
            return None
    
    @staticmethod
    def validate_bingo_claim(card_numbers: List[int], called_numbers: List[int], 
                           claimed_pattern: Optional[str] = None) -> Dict[str, Any]:
        """Validate a bingo claim and return detailed information"""
        try:
            is_valid = BingoChecker.is_bingo(card_numbers, called_numbers)
            
            if not is_valid:
                return {
                    'valid': False,
                    'reason': 'No bingo pattern found',
                    'pattern': None,
                    'pattern_name': None,
                    'winning_numbers': []
                }
            
            # Find the winning pattern
            pattern = BingoChecker.find_winning_pattern(card_numbers, called_numbers)
            pattern_name = BingoChecker.get_winning_pattern_name(pattern) if pattern else None
            
            # Get winning numbers in the pattern
            winning_numbers = []
            if pattern:
                grid = [card_numbers[i:i+5] for i in range(0, 25, 5)]
                winning_numbers = [grid[row][col] for row, col in pattern]
            
            # Check if claimed pattern matches actual pattern
            pattern_matches = True
            if claimed_pattern and pattern_name:
                pattern_matches = (claimed_pattern.lower() in pattern_name.lower() or 
                                  pattern_name.lower() in claimed_pattern.lower())
            
            return {
                'valid': is_valid,
                'reason': 'Valid bingo' if is_valid else 'No bingo pattern found',
                'pattern': pattern,
                'pattern_name': pattern_name,
                'winning_numbers': winning_numbers,
                'pattern_matches_claim': pattern_matches
            }
            
        except Exception as e:
            logger.error(f"Error validating bingo claim: {e}")
            return {
                'valid': False,
                'reason': f'Error: {str(e)}',
                'pattern': None,
                'pattern_name': None,
                'winning_numbers': [],
                'pattern_matches_claim': False
            }
    
    @staticmethod
    def get_card_grid(card_numbers: List[int], called_numbers: List[int] = None) -> List[List[Dict[str, Any]]]:
        """Get card grid with marked status"""
        try:
            if len(card_numbers) != 25:
                return []
            
            called_set = set(called_numbers) if called_numbers else set()
            
            grid = []
            for i in range(5):
                row = []
                for j in range(5):
                    number = card_numbers[i * 5 + j]
                    is_called = number in called_set
                    row.append({
                        'number': number,
                        'called': is_called,
                        'row': i,
                        'col': j
                    })
                grid.append(row)
            
            return grid
            
        except Exception as e:
            logger.error(f"Error getting card grid: {e}")
            return []
    
    @staticmethod
    def get_bingo_verification_details(card_numbers: List[int], called_numbers: List[int]) -> Dict[str, Any]:
        """Get detailed bingo verification information"""
        try:
            validation = BingoChecker.validate_bingo_claim(card_numbers, called_numbers)
            grid = BingoChecker.get_card_grid(card_numbers, called_numbers)
            
            return {
                'validation': validation,
                'grid': grid,
                'card_numbers': card_numbers,
                'called_numbers': called_numbers,
                'called_count': len(called_numbers),
                'timestamp': datetime.now().isoformat(),  # This line was causing the error
                'checked_at': datetime.now().isoformat()   # Added for backward compatibility
            }
            
        except Exception as e:
            logger.error(f"Error getting bingo verification details: {e}")
            return {
                'validation': {'valid': False, 'reason': str(e)},
                'grid': [],
                'card_numbers': card_numbers,
                'called_numbers': called_numbers,
                'called_count': len(called_numbers) if called_numbers else 0,
                'timestamp': datetime.now().isoformat(),
                'checked_at': datetime.now().isoformat(),
                'error': str(e)
            }
    
    @staticmethod
    def simulate_bingo_check(num_cards: int = 10, num_called: int = 35) -> Dict[str, Any]:
        """Simulate bingo checking for testing"""
        try:
            from utils.card_generator import CardGenerator  # Import here to avoid circular imports
            
            results = {
                'total_cards': num_cards,
                'called_numbers_count': num_called,
                'bingo_cards': [],
                'timestamp': datetime.now().isoformat()
            }
            
            # Generate called numbers (1-75)
            all_numbers = list(range(1, 76))
            called_numbers = random.sample(all_numbers, min(num_called, 75))
            
            # Generate cards and check for bingo
            for i in range(num_cards):
                card = CardGenerator.generate_card()
                card_numbers = CardGenerator.extract_numbers(card)
                
                is_bingo = BingoChecker.is_bingo(card_numbers, called_numbers)
                validation = BingoChecker.validate_bingo_claim(card_numbers, called_numbers)
                
                card_result = {
                    'card_id': i + 1,
                    'card_numbers': card_numbers,
                    'has_bingo': is_bingo,
                    'pattern_name': validation.get('pattern_name'),
                    'winning_numbers': validation.get('winning_numbers', [])
                }
                
                results['bingo_cards'].append(card_result)
            
            # Count bingos
            bingo_count = sum(1 for card in results['bingo_cards'] if card['has_bingo'])
            results['bingo_count'] = bingo_count
            results['bingo_percentage'] = (bingo_count / num_cards * 100) if num_cards > 0 else 0
            
            return results
            
        except Exception as e:
            logger.error(f"Error simulating bingo check: {e}")
            return {
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }

# Create a singleton instance
bingo_checker = BingoChecker()