# utils/game_cache.py
import asyncio
import json
from datetime import datetime
from typing import Dict, List, Set
import logging

logger = logging.getLogger(__name__)

class GameCache:
    """Cache system for tracking game state and sold cards"""
    
    def __init__(self):
        self.active_games: Dict[str, Dict] = {}
        self.sold_cards: Dict[str, Set[int]] = {}  # game_id -> set of sold card IDs
        self.game_start_times: Dict[str, datetime] = {}
    
    async def create_game_cache(self, game_id: str, prize_pool: float = 50.0):
        """Initialize cache for a new game"""
        self.active_games[game_id] = {
            'game_id': game_id,
            'status': 'waiting',
            'prize_pool': prize_pool,
            'cards_sold': 0,
            'players': set(),
            'called_numbers': [],
            'created_at': datetime.now()
        }
        
        # Reset sold cards for this game
        self.sold_cards[game_id] = set()
        
        logger.info(f"Created game cache for {game_id}")
        return True
    
    async def start_game(self, game_id: str):
        """Mark game as started"""
        if game_id in self.active_games:
            self.active_games[game_id]['status'] = 'active'
            self.active_games[game_id]['started_at'] = datetime.now()
            self.game_start_times[game_id] = datetime.now()
            logger.info(f"Game {game_id} started")
            return True
        return False
    
    async def end_game(self, game_id: str):
        """Mark game as ended"""
        if game_id in self.active_games:
            self.active_games[game_id]['status'] = 'ended'
            self.active_games[game_id]['ended_at'] = datetime.now()
            
            # Clear cache after some time
            await self._cleanup_game(game_id)
            logger.info(f"Game {game_id} ended")
            return True
        return False
    
    async def mark_card_sold(self, game_id: str, card_id: int, user_id: int):
        """Mark a card as sold for a specific game"""
        if game_id in self.sold_cards:
            self.sold_cards[game_id].add(card_id)
            
            # Update game stats
            if game_id in self.active_games:
                self.active_games[game_id]['cards_sold'] += 1
                self.active_games[game_id]['players'].add(user_id)
            
            logger.info(f"Card {card_id} marked as sold for game {game_id}")
            return True
        return False
    
    async def get_available_cards(self, game_id: str) -> List[int]:
        """Get list of available card IDs (1-400)"""
        from utils.card_generator import CardGenerator
        all_cards_count = len(CardGenerator.load_all_cards())
        
        if game_id in self.sold_cards:
            sold = self.sold_cards[game_id]
            # Return all cards 1-400 that are not sold
            return [i for i in range(1, all_cards_count + 1) if i not in sold]
        
        # If game not in cache, all cards are available
        return list(range(1, all_cards_count + 1))
    
    async def get_sold_cards(self, game_id: str) -> List[int]:
        """Get list of sold card IDs"""
        if game_id in self.sold_cards:
            return list(self.sold_cards[game_id])
        return []
    
    async def is_card_available(self, game_id: str, card_id: int) -> bool:
        """Check if a card is available for purchase"""
        if game_id in self.sold_cards:
            return card_id not in self.sold_cards[game_id]
        return True
    
    async def add_called_number(self, game_id: str, number: int):
        """Add a called number to game cache"""
        if game_id in self.active_games:
            if number not in self.active_games[game_id]['called_numbers']:
                self.active_games[game_id]['called_numbers'].append(number)
                return True
        return False
    
    async def get_called_numbers(self, game_id: str) -> List[int]:
        """Get called numbers for a game"""
        if game_id in self.active_games:
            return self.active_games[game_id]['called_numbers']
        return []
    
    async def get_game_state(self, game_id: str) -> Dict:
        """Get complete game state"""
        if game_id in self.active_games:
            game = self.active_games[game_id].copy()
            game['players_count'] = len(game['players'])
            game['sold_cards_count'] = len(self.sold_cards.get(game_id, set()))
            return game
        return None
    
    async def _cleanup_game(self, game_id: str):
        """Clean up game cache after it ends"""
        # Remove from cache after 1 hour
        await asyncio.sleep(3600)
        if game_id in self.active_games:
            del self.active_games[game_id]
        if game_id in self.sold_cards:
            del self.sold_cards[game_id]
        if game_id in self.game_start_times:
            del self.game_start_times[game_id]
        logger.info(f"Cleaned up cache for game {game_id}")

# Global game cache instance
game_cache = GameCache()