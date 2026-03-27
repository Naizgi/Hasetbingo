# utils/number_caller.py - Server-controlled number calling system

import asyncio
import logging
import random
from datetime import datetime
from typing import Dict, List, Optional, Set
import json
from database.db import Database
from utils.game_manager import game_manager

logger = logging.getLogger(__name__)

class NumberCaller:
    """Server-controlled number calling system"""
    
    def __init__(self):
        self.active_games = {}
        self.calling_tasks = {}
        self.countdown_tasks = {}
        self._active_games = {}  # NEW: Track which games are actively calling numbers
        self.called_numbers = {}  # Track called numbers per game
        logger.info("NumberCaller initialized")
    
    # NEW: Add this method to track active number calling
    def is_calling_numbers_for_game(self, game_id: str) -> bool:
        """Check if number calling is active for a specific game"""
        return game_id in self._active_games and self._active_games[game_id]
    
    async def start_number_calling_for_game(self, game_id: str):
        """Start number calling for a game"""
        try:
            # Check if game exists
            game = await Database.get_game(game_id)
            if not game:
                logger.error(f"Game {game_id} not found")
                return False
            
            # Reset called numbers for this game (if restarting)
            self.called_numbers[game_id] = await Database.get_drawn_numbers(game_id)
            logger.info(f"Loaded {len(self.called_numbers[game_id])} existing numbers for game {game_id}")
            
            # Check if already calling
            if game_id in self.calling_tasks and not self.calling_tasks[game_id].done():
                logger.info(f"Already calling numbers for game {game_id}")
                # Update tracking
                self._active_games[game_id] = True
                return True
            
            # Stop any existing task
            if game_id in self.calling_tasks:
                self.calling_tasks[game_id].cancel()
                try:
                    await self.calling_tasks[game_id]
                except:
                    pass
            
            # Start number calling task
            task = asyncio.create_task(self._call_numbers_for_game(game_id))
            self.calling_tasks[game_id] = task
            
            # Update tracking
            self._active_games[game_id] = True
            
            # # Start countdown task for winner display
            # if game_id not in self.countdown_tasks or self.countdown_tasks[game_id].done():
            #     countdown_task = asyncio.create_task(self._manage_game_countdown(game_id))
            #     self.countdown_tasks[game_id] = countdown_task
            
            logger.info(f"Started number calling for game {game_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error starting number calling: {e}")
            return False
    
    async def stop_number_calling_for_game(self, game_id: str):
        """Stop number calling for a game"""
        try:
            # Update tracking
            if game_id in self._active_games:
                self._active_games[game_id] = False
            
            # Cancel calling task
            if game_id in self.calling_tasks:
                task = self.calling_tasks.pop(game_id)
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            
            # Cancel countdown task
            if game_id in self.countdown_tasks:
                task = self.countdown_tasks.pop(game_id)
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            
            logger.info(f"Stopped number calling for game {game_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error stopping number calling: {e}")
            return False
    
    async def _call_numbers_for_game(self, game_id: str):
        """Call numbers for a game"""
        try:
            from database.db import Database
            from web_server import websocket_server
            
            logger.info(f"Starting number calling loop for game {game_id}")
            
            # ⏳ Wait 3 seconds before calling the first number
            await asyncio.sleep(3)
            
            # Initialize called numbers set for this game
            if game_id not in self.called_numbers:
                self.called_numbers[game_id] = await Database.get_drawn_numbers(game_id)
            
            called_stack = self.called_numbers[game_id]
            
            while True:
                try:
                    # Check if game is still active - FIXED: Check both status and phase
                    game = await Database.get_game(game_id)
                    if not game:
                        logger.info(f"Game {game_id} not found, stopping number calling")
                        break
                    
                    # Get current status and phase
                    status = game.get('status', '').lower()
                    phase = game.get('current_phase', '').lower()
                    
                    # Debug log to help diagnose
                    logger.debug(f"Game {game_id} - status: {status}, phase: {phase}")
                    
                    # Game is considered active for number calling if:
                    # 1. Status is 'active' or 'game_play'
                    # 2. AND NOT in winner_display phase
                    # 3. AND numbers haven't all been called
                    is_active = (status in ['active', 'game_play'] and 
                                phase not in ['winner_display', 'completed'])
                    
                    if not is_active:
                        logger.info(f"Game {game_id} is not active for number calling (status: {status}, phase: {phase}), stopping number calling")
                        # Update tracking
                        if game_id in self._active_games:
                            self._active_games[game_id] = False
                        break
                    
                    # Check if all numbers have been called
                    if len(called_stack) >= 75:
                        logger.info(f"All 75 numbers have been called for game {game_id}")
                        
                        # Check if there's a winner
                        winners_count = await game_manager.get_winners_count(game_id)
                        
                        if winners_count == 0:
                            # No winner after all numbers - force game completion
                            logger.warning(f"Game {game_id} has no winner after all numbers called. Forcing completion...")
                            
                            # Mark game as completed with no winner
                            await Database.update_game_status(game_id, 'completed')
                            await Database.update_game_phase(game_id, 'completed')
                            
                            # Broadcast game ended with no winner
                            await websocket_server.broadcast_with_retry({
                                'type': 'game_completed_no_winner',
                                'game_id': game_id,
                                'message': 'Game ended - no winner',
                                'timestamp': datetime.now().isoformat()
                            })
                            
                            # Schedule next round
                            asyncio.create_task(game_manager._schedule_next_round_after_winner_display(game_id))
                        
                        # Update tracking
                        if game_id in self._active_games:
                            self._active_games[game_id] = False
                        break
                    
                    # Generate new number (1-75)
                    all_numbers = list(range(1, 76))
                    available_numbers = [n for n in all_numbers if n not in called_stack]
                    
                    if not available_numbers:
                        logger.info(f"No available numbers for game {game_id}")
                        # Update tracking
                        if game_id in self._active_games:
                            self._active_games[game_id] = False
                        break
                    
                    # Randomly select next number
                    next_number = random.choice(available_numbers)
                    
                    # Record drawn number
                    success = await Database.record_drawn_number(game_id, next_number)
                    
                    if not success:
                        logger.error(f"Failed to record drawn number {next_number}")
                        await asyncio.sleep(4)
                        continue
                    
                    # Add to called set
                    called_stack.append(next_number)
                    self.called_numbers[game_id] = called_stack
                    
                    # Get bingo letter
                    bingo_letter = self._get_bingo_letter(next_number)
                    
                    # Broadcast new number
                    await websocket_server.broadcast_with_retry({
                        'type': 'number_called',
                        'game_id': game_id,
                        'number': next_number,
                        'letter': bingo_letter,
                        'called_numbers': called_stack,
                        # 'fake_winners': fake_winners,
                        'timestamp': datetime.now().isoformat()
                    })
                    
                    # Mark number on all cards (real and fake)
                    fake_winners = await game_manager.mark_number_on_all_cards(game_id, next_number)
                    
                    # Check if game should be stopped (first winner)
                    game = await Database.get_game(game_id)
                    if game and game.get('status') == 'winner_display':
                        logger.info(f"Game {game_id} entered winner display phase, stopping number calling")
                        break
                    
                    logger.info(f"Called number {next_number} ({bingo_letter}) for game {game_id} (fake winners: {fake_winners})")
                    
                    # Wait before next number (4 seconds)
                    await asyncio.sleep(4)
                    
                except asyncio.CancelledError:
                    logger.info(f"Number calling cancelled for game {game_id}")
                    # Update tracking
                    if game_id in self._active_games:
                        self._active_games[game_id] = False
                    break
                except Exception as e:
                    logger.error(f"Error in number calling loop: {e}")
                    await asyncio.sleep(4.5)
            
            # Cleanup
            # if game_id in self.calling_tasks:
            #     self.calling_tasks.pop(game_id, None)
            
            # # Update tracking
            # if game_id in self._active_games:
            #     self._active_games[game_id] = False
            
            logger.info(f"Number calling loop ended for game {game_id}")
            
        except Exception as e:
            logger.error(f"Error in _call_numbers_for_game: {e}")
            # Update tracking on error
            if game_id in self._active_games:
                self._active_games[game_id] = False
    
    async def _manage_game_countdown(self, game_id: str):
        """Manage game countdown"""
        try:
            from database.db import Database
            from web_server import websocket_server
            
            while True:
                try:
                    # Get game status
                    game = await Database.get_game(game_id)
                    if not game:
                        logger.info(f"Game {game_id} not found, stopping countdown")
                        break
                    
                    status = game.get('status', 'unknown')
                    phase = game.get('current_phase', 'unknown')
                    
                    if status == 'card_purchase' or phase == 'card_purchase':
                        # Calculate purchase countdown
                        purchase_end = game.get('purchase_end_time')
                        if purchase_end:
                            if isinstance(purchase_end, str):
                                from dateutil.parser import parse
                                try:
                                    purchase_end = parse(purchase_end)
                                except:
                                    purchase_end = datetime.fromisoformat(purchase_end.replace('Z', '+00:00'))
                            
                            now = datetime.now()
                            remaining = (purchase_end - now).total_seconds()
                            countdown = max(0, int(remaining))
                            
                            # Update countdown in database
                            await Database.update_game_countdown(game_id, countdown)
                            
                            # Broadcast countdown update
                            await websocket_server.broadcast_with_retry({
                                'type': 'countdown_update',
                                'game_id': game_id,
                                'countdown': countdown,
                                'phase': 'card_purchase',
                                'timestamp': datetime.now().isoformat()
                            })
                            
                            # Check if purchase time expired
                            if countdown <= 0:
                                # Auto-start game play
                                from utils.game_manager import game_manager
                                await game_manager.start_game_play(game_id)
                    
                    elif status == 'winner_display' or phase == 'winner_display':
                        # Calculate winner display countdown
                        winner_display_end = game.get('winner_display_end')
                        if winner_display_end:
                            if isinstance(winner_display_end, str):
                                try:
                                    winner_display_end = datetime.fromisoformat(winner_display_end.replace('Z', '+00:00'))
                                except:
                                    winner_display_end = datetime.fromisoformat(winner_display_end)
                            
                            now = datetime.now()
                            if winner_display_end > now:
                                countdown = int((winner_display_end - now).total_seconds())
                            else:
                                countdown = 0
                            
                            # Update countdown
                            await Database.update_game_countdown(game_id, countdown)
                            
                            # Broadcast countdown update
                            await websocket_server.broadcast_with_retry({
                                'type': 'countdown_update',
                                'game_id': game_id,
                                'countdown': countdown,
                                'phase': 'winner_display',
                                'timestamp': datetime.now().isoformat()
                            })
                            
                            # Check if winner display time expired
                            if countdown <= 0:
                                # Mark game as completed
                                await Database.update_game_status(game_id, 'completed')
                                await Database.update_game_phase(game_id, 'completed')
                                
                                # Clean up called numbers for this game
                                if game_id in self.called_numbers:
                                    del self.called_numbers[game_id]
                                
                                # Broadcast new round will be handled by game_manager
                                break
                    
                    await asyncio.sleep(1)  # Update every second
                    
                except asyncio.CancelledError:
                    logger.info(f"Countdown task cancelled for game {game_id}")
                    break
                except Exception as e:
                    logger.error(f"Error in countdown loop: {e}")
                    await asyncio.sleep(1)
            
            # Cleanup
            if game_id in self.countdown_tasks:
                self.countdown_tasks.pop(game_id, None)
            
        except Exception as e:
            logger.error(f"Error in _manage_game_countdown: {e}")
    
    def _get_bingo_letter(self, number: int) -> str:
        """Get BINGO letter for a number"""
        if 1 <= number <= 15:
            return 'B'
        elif 16 <= number <= 30:
            return 'I'
        elif 31 <= number <= 45:
            return 'N'
        elif 46 <= number <= 60:
            return 'G'
        else:  # 61-75
            return 'O'
    
    # NEW: Get all games currently calling numbers
    def get_active_calling_games(self) -> List[str]:
        """Get list of game IDs that are currently calling numbers"""
        active_games = []
        for game_id, is_active in self._active_games.items():
            if is_active:
                active_games.append(game_id)
        return active_games
    
    # NEW: Force check and restart if needed
    async def ensure_calling_for_game(self, game_id: str) -> bool:
        """Ensure number calling is active for a game, restart if not"""
        try:
            from database.db import Database
            
            # Check if game exists and is active
            game = await Database.get_game(game_id)
            if not game:
                return False
            
            status = game.get('status', '').lower()
            phase = game.get('current_phase', '').lower()
            
            # Only ensure calling if game is active
            if status in ['active', 'game_play'] and phase not in ['winner_display', 'completed']:
                if not self.is_calling_numbers_for_game(game_id):
                    logger.warning(f"Number calling not active for game {game_id}, restarting...")
                    return await self.start_number_calling_for_game(game_id)
                return True
            return False
        except Exception as e:
            logger.error(f"Error ensuring number calling for game {game_id}: {e}")
            return False
    
    async def reset_called_numbers_for_game(self, game_id: str):
        """Reset called numbers for a game (when game restarts)"""
        if game_id in self.called_numbers:
            self.called_numbers[game_id] = []
            logger.info(f"Reset called numbers for game {game_id}")
    
    async def cleanup(self):
        """Cleanup all tasks"""
        try:
            # Update all tracking to False
            for game_id in list(self._active_games.keys()):
                self._active_games[game_id] = False
            
            # Cancel all calling tasks
            for game_id, task in list(self.calling_tasks.items()):
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            
            # Cancel all countdown tasks
            for game_id, task in list(self.countdown_tasks.items()):
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            
            self.calling_tasks.clear()
            self.countdown_tasks.clear()
            self._active_games.clear()
            self.called_numbers.clear()
            
            logger.info("NumberCaller cleanup completed")
            
        except Exception as e:
            logger.error(f"Error cleaning up NumberCaller: {e}")

# Global instance
number_caller = NumberCaller()