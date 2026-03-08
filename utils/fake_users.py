"""
Fake User Management System for Habesha Bingo
Simulates players when real users are not available
- Simple: Card purchases happen at different intervals within 30 seconds
- Dynamic player reduction (1 fake removed for each real player)
- Maintains minimum fake players at all times (minimum 10)
- FIXED: Generates valid Bingo cards following column rules
- FIXED: Fake players affect prize pool like real players (add 8 birr)
- FIXED: Fake player commission goes to house balance (2 birr each)
- FIXED: When removed, prize pool is NOT affected (already counted)
- CRITICAL FIX: Fake card creation ADDS to prize pool (+8) and house commission (+2)
- CRITICAL FIX: Fake card removal DOES NOT affect prize pool (already counted)
- CRITICAL FIX: Game cleanup DOES NOT affect prize pool
- FIXED: Fake players now have realistic delays when marking numbers
- FIXED: Fake users are added to fake_players table for admin panel filtering
- ==================== CRITICAL FIX: INSTANT BINGO CLAIMS ====================
- Fake winners now claim BINGO INSTANTLY (no delays) for faster game flow
- ==================== CRITICAL FIX: INSTANT CARD BROADCAST ====================
- Fake cards now broadcast IMMEDIATELY after each purchase via WebSocket
- Frontend receives card indices as soon as each fake player buys a card
- Cards appear gradually throughout the countdown for natural feel
- ============================================================
"""
import random
import asyncio
import logging
import time
from typing import List, Dict, Optional, Tuple
from datetime import datetime
import json

# ==================== IMPORT WEBSOCKET SERVER FOR BROADCASTS ====================
try:
    from web_server import websocket_server
except ImportError:
    logger = logging.getLogger(__name__)
    logger.warning("WebSocket server not available - broadcasts will fail")
    websocket_server = None

# ==================== FAKE USER CONFIGURATION ====================
# 300 realistic Telegram-style usernames with emojis, numbers, and patterns
FAKE_USER_NAMES = [
    # Common Ethiopian names with numbers
    'abel_99', 'yared_23', 'tekle_45', 'daniel_67', 'samuel_89', 'dawit_12', 
    'henok_34', 'nathan_56', 'yoni_78', 'meron_90', 'selam_21', 'hanna_43',
    'mekdes_65', 'betel_87', 'tsion_09', 'biruk_11', 'nahom_22', 'rob_33',
    'leul_44', 'ephrem_55', 'kidist_66', 'azeb_77', 'mulu_88', 'aster_99',
    
    # Names with dots and underscores
    'abraham.t', 'yosef.k', 'tigist.m', 'frehiwot.a', 'bereket.g', 'surafel.d',
    'biniyam.b', 'feven.r', 'meron.s', 'selam.t', 'yordanos.z', 'meklit.h',
    'elias.n', 'misrak.f', 'yeabsira.c', 'sosina.v', 'kidus.p', 'nardos.q',
    
    # Usernames with years
    'dave_2020', 'mike_2019', 'john_2021', 'sara_2022', 'joe_2023', 'lisa_2024',
    'alex_2018', 'emma_2017', 'chris_2016', 'anna_2015', 'kevin_2014', 'julia_2013',
    'mark_1985', 'lucy_1990', 'paul_1995', 'helen_2000', 'peter_2005', 'ruth_2010',
    
    # Names with emojis
    '🔥_abel', '⚡_dawit', '✨_selam', '🌟_henok', '💫_meron', '⭐_yoni',
    '👑_tekle', '🎮_daniel', '🎧_samuel', '📱_nahom', '💻_biruk', '🎯_leul',
    '🏀_ephrem', '⚽_kidist', '🎲_azeb', '🎨_mulu', '🎭_aster', '🎪_kidus',
    '🚀_abraham', '🌈_yosef', '⭐_tigist', '💪_frehiwot', '🔥_bereket', '✨_surafel',
    
    # Cool prefixes
    'xX_abel_Xx', 'xDawitx', 'xx_selam_xx', 'xxYonixx', 'xMeronx', 'xxHenokxx',
    'mr_daniel', 'ms_samuel', 'dr_nahom', 'prof_biruk', 'captain_leul', 'chief_ephrem',
    'king_kidist', 'queen_azeb', 'prince_mulu', 'princess_aster', 'lord_kidus', 'lady_nardos',
    
    # Numbers at beginning
    '001abel', '002dawit', '003selam', '004henok', '005meron', '006yoni',
    '007daniel', '008samuel', '009nahom', '010biruk', '011leul', '012ephrem',
    
    # Common Ethiopian names with variations
    'abush_23', 'chala_45', 'guta_67', 'bontu_89', 'bula_12', 'dinsa_34',
    'gammachiis_56', 'hunde_78', 'jilcha_90', 'kumsa_21', 'lema_43', 'mosisa_65',
    'olani_87', 'roba_09', 'tola_11', 'umesa_22', 'wakgari_33', 'yadeta_44',
    
    # Names with mixed case
    'AbelTheGreat', 'DawitLegend', 'SelamQueen', 'HenokStar', 'MeronBeauty',
    'YoniMaster', 'DanielPro', 'SamuelKing', 'NahomPrince', 'BirukLord',
    'LeulEmperor', 'EphremSultan', 'KidistEmpress', 'AzebDuchess', 'MuluCountess',
    
    # Names with special characters
    'abel_007', 'dawit_$', 'selam_&', 'henok_*', 'meron_#', 'yoni_@',
    'daniel_!', 'samuel_?', 'nahom_+', 'biruk_=', 'leul_-', 'ephrem_%',
    
    # Ethiopian names with numbers suffix
    'tsegaye1', 'gebre2', 'haftom3', 'tesfaye4', 'tadesse5', 'alemayehu6',
    'bekele7', 'desta8', 'fikre9', 'girma0', 'hailu11', 'kebede22',
    'lemma33', 'mekonnen44', 'negash55', 'shiferaw66', 'teferi77', 'wondimu88',
    
    # Names with common suffixes
    'abel_eth', 'dawit_habesha', 'selam_addis', 'henok_gondar', 'meron_tigray',
    'yoni_gojam', 'daniel_wollo', 'samuel_harar', 'nahom_dire', 'biruk_bahir',
    'leul_mekelle', 'ephrem_jimma', 'kidist_axum', 'azeb_lalibela', 'mulu_bale',
    
    # Modern usernames
    'itz_abel', 'im_dawit', 're_selam', 'just_henok', 'real_meron', 'only_yoni',
    'the_daniel', 'this_is_samuel', 'that_nahom', 'biruk_live', 'leul_online',
    'ephrem_world', 'kidist_life', 'azeb_style', 'mulu_vibes', 'aster_mood',
    
    # Names with game-related terms
    'bingo_abel', 'bingo_king_dawit', 'bingo_selam', 'bingo_master_henok',
    'jackpot_meron', 'winner_yoni', 'champion_daniel', 'victory_samuel',
    'lucky_nahom', 'golden_biruk', 'silver_leul', 'bronze_ephrem',
    'ace_kidist', 'pro_azeb', 'elite_mulu', 'legend_aster',
    
    # Names with Ethiopian cities
    'addis_abel', 'gondar_dawit', 'mekelle_selam', 'bahir_henok', 'harar_meron',
    'dire_yoni', 'jimma_daniel', 'axum_samuel', 'lalibela_nahom', 'arba_biruk',
    'sodo_leul', 'hawassa_ephrem', 'debre_kidist', 'wukro_azeb', 'adigrat_mulu',
    
    # Names with professions
    'dr_abel', 'prof_dawit', 'eng_selam', 'arch_henok', 'doc_meron',
    'nurse_yoni', 'teacher_daniel', 'coach_samuel', 'chef_nahom', 'pilot_biruk',
    'captain_leul', 'soldier_ephrem', 'artist_kidist', 'singer_azeb', 'dancer_mulu',
    
    # Names with random numbers (phone-like)
    'abel_0911', 'dawit_0912', 'selam_0913', 'henok_0914', 'meron_0915',
    'yoni_0916', 'daniel_0917', 'samuel_0918', 'nahom_0919', 'biruk_0920',
    'leul_0921', 'ephrem_0922', 'kidist_0923', 'azeb_0924', 'mulu_0925',
    'aster_0926', 'kidus_0927', 'nardos_0928', 'meklit_0929', 'feven_0930',
    
    # Names with Ethiopian coffee terms
    'buna_abel', 'coffee_dawit', 'jebena_selam', 'berele_henok', 'tann_meron',
    'kali_yoni', 'bunna_daniel', 'bari_samuel', 'buna_bet_nahom', 'coffee_lover_biruk',
    
    # Short names
    'ab', 'dw', 'sl', 'hn', 'mr', 'yn', 'dn', 'sm', 'nh', 'br',
    'll', 'ep', 'kd', 'az', 'ml', 'as', 'ks', 'nd', 'mk', 'fv',
    
    # Names with Ethiopian food
    'injera_abel', 'doro_dawit', 'kitfo_selam', 'tibs_henok', 'shiro_meron',
    'gomen_yoni', 'ayib_daniel', 'beyaynetu_samuel', 'firfir_nahom', 'kicha_biruk',
    
    # Names with music
    'ethio_jazz_abel', 'mulatu_dawit', 'aster_selam', 'mahmoud_henok', 'girma_meron',
    'hailu_yoni', 'tlahoun_daniel', 'alèmayèhu_samuel', 'tezeta_nahom', 'bati_biruk',
    
    # Youthful names
    'abel_king', 'dawit_boss', 'selam_doll', 'henok_star', 'meron_babe',
    'yoni_boy', 'daniel_guy', 'samuel_man', 'nahom_kid', 'biruk_teen',
    'leul_bro', 'ephrem_sis', 'kidist_sis', 'azeb_gal', 'mulu_girl',
    
    # Names with sports
    'football_abel', 'soccer_dawit', 'goal_selam', 'striker_henok', 'keeper_meron',
    'midfield_yoni', 'defender_daniel', 'coach_samuel', 'referee_nahom', 'captain_biruk',
    
    # Ethiopian athletes
    'haile_abel', 'gebrselassie_dawit', 'bekele_selam', 'dibaba_henok', 'defar_meron',
    'tola_yoni', 'lilesa_daniel', 'megertu_samuel', 'teferi_nahom', 'gidey_biruk',
    
    # Names with tech
    'coder_abel', 'dev_dawit', 'hacker_selam', 'geek_henok', 'nerd_meron',
    'python_yoni', 'java_daniel', 'js_samuel', 'sql_nahom', 'linux_biruk',
    'windows_leul', 'mac_ephrem', 'android_kidist', 'ios_azeb', 'web_mulu',
    
    # Names with cars
    'toyota_abel', 'mercedes_dawit', 'bmw_selam', 'audi_henok', 'lexus_meron',
    'hyundai_yoni', 'honda_daniel', 'nissan_samuel', 'mitsubishi_nahom', 'suzuki_biruk',
    
    # Names with nature
    'mountain_abel', 'river_dawit', 'forest_selam', 'lake_henok', 'ocean_meron',
    'sun_yoni', 'moon_daniel', 'star_samuel', 'sky_nahom', 'cloud_biruk',
    'rain_leul', 'wind_ephrem', 'earth_kidist', 'fire_azeb', 'water_mulu',
    
    # Random cool names
    'shadow_abel', 'blaze_dawit', 'frost_selam', 'storm_henok', 'thunder_meron',
    'lightning_yoni', 'phoenix_daniel', 'dragon_samuel', 'tiger_nahom', 'lion_biruk',
    'eagle_leul', 'hawk_ephrem', 'wolf_kidist', 'fox_azeb', 'bear_mulu',
    
    # More Ethiopian names
    'assefa_01', 'demeke_02', 'fikadu_03', 'getachew_04', 'habtamu_05',
    'jember_06', 'kassa_07', 'mamo_08', 'negussie_09', 'taye_10',
    'wondimu_11', 'yimer_12', 'zemedkun_13', 'abebe_14', 'berhanu_15',
    
    # Names with Ethiopia
    'ethiopia_abel', 'habesha_dawit', 'abyssinia_selam', 'addis_henok', 'sheba_meron',
    'lalibela_yoni', 'axum_daniel', 'gondar_samuel', 'harar_nahom', 'dire_biruk',
    
    # Names with numbers (year of birth style)
    'abel_1990', 'dawit_1991', 'selam_1992', 'henok_1993', 'meron_1994',
    'yoni_1995', 'daniel_1996', 'samuel_1997', 'nahom_1998', 'biruk_1999',
    'leul_2000', 'ephrem_2001', 'kidist_2002', 'azeb_2003', 'mulu_2004',
    
    # Names with symbols
    'a_b_e_l', 'd_a_w_i_t', 's_e_l_a_m', 'h_e_n_o_k', 'm_e_r_o_n',
    'y_o_n_i', 'd_a_n_i_e_l', 's_a_m_u_e_l', 'n_a_h_o_m', 'b_i_r_u_k',
    
    # Names with "x" at end
    'abelx', 'dawitx', 'selamx', 'henokx', 'meronx', 'yonix',
    'danielx', 'samuelx', 'nahomx', 'birukx', 'leulx', 'ephremx',
    
    # Names with underscores everywhere
    '_abel_', '_dawit_', '_selam_', '_henok_', '_meron_', '_yoni_',
    '_daniel_', '_samuel_', '_nahom_', '_biruk_', '_leul_', '_ephrem_',
    
    # Common English names (for variety)
    'john_eth', 'peter_hab', 'james_addis', 'paul_gondar', 'george_mekelle',
    'mike_bahir', 'steve_harar', 'david_dire', 'chris_jimma', 'tom_axum',
    
    # Names with emojis (at end)
    'abel_🔥', 'dawit_⚡', 'selam_✨', 'henok_🌟', 'meron_💫', 'yoni_⭐',
    'daniel_👑', 'samuel_🎮', 'nahom_🎧', 'biruk_📱', 'leul_💻', 'ephrem_🎯',
    
    # Last 15 to reach exactly 300
    'binyam_eth', 'ephrem_eth', 'kidane_eth', 'mehari_eth', 'nigus_eth',
    'tsegaye_eth', 'wolde_eth', 'zemed_eth', 'abinet_eth', 'belay_eth',
    'cheru_eth', 'demissie_eth', 'eshetu_eth', 'fisseha_eth', 'genet_eth'
]

# Fake user IDs (negative numbers to avoid conflict with real Telegram IDs)
FAKE_USER_IDS = [-i for i in range(1, 301)]  # 300 fake users

logger = logging.getLogger(__name__)

# ==================== BINGO COLUMN RANGES ====================
BINGO_COLUMNS = {
    'B': (1, 15),
    'I': (16, 30),
    'N': (31, 45),
    'G': (46, 60),
    'O': (61, 75)
}

# ==================== FAKE USER STATE ====================
class FakeUserManager:
    """Manages fake users for games - simplified version with valid card generation"""
    
    def __init__(self):
        self.fake_users = {}
        self.game_fake_cards = {}  # game_id -> {fake_user_id: card_data}
        self._initialize_fake_users()
        # Track removal queue for FIFO removal (oldest fake users removed first)
        self.game_purchase_order = {}  # game_id -> list of user_ids in purchase order
        
        # Track last number processed time for each game to add realistic delays
        self.last_number_time = {}  # game_id -> timestamp
        
    # ==================== FIXED: Initialize fake users and add to fake_players table ====================
    def _initialize_fake_users(self):
        """Initialize fake user accounts in memory and database"""
        from database.db import Database
        
        for i, name in enumerate(FAKE_USER_NAMES):
            user_id = FAKE_USER_IDS[i] if i < len(FAKE_USER_IDS) else -(i + 1)
            
            # Store in memory
            self.fake_users[user_id] = {
                'user_id': user_id,
                'username': name,
                'full_name': name,
                'is_fake': True,
                'balance': 1000.00,  # Give fake users plenty of balance (not used)
                'created_at': datetime.now().isoformat()
            }
            
            # Insert into database to satisfy foreign key constraints
            try:
                with Database.get_cursor() as cursor:
                    cursor.execute("""
                        INSERT OR IGNORE INTO users 
                        (user_id, username, full_name, balance, is_admin, status, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        user_id,
                        name,
                        name,
                        1000.00,  # Starting balance (not used for payouts)
                        0,  # not admin
                        'active',
                        datetime.now()
                    ))
                    
                    # ========== CRITICAL FIX: Add to fake_players table for admin panel filtering ==========
                    cursor.execute("""
                        INSERT OR IGNORE INTO fake_players (user_id, username, full_name)
                        VALUES (?, ?, ?)
                    """, (user_id, name, name))
                    
            except Exception as e:
                logger.error(f"Error creating fake user {user_id} in DB: {e}")
        
        logger.info(f"✅ Initialized {len(self.fake_users)} fake users in memory and database (also added to fake_players table)")
    
    def get_random_fake_users(self, count: int = None) -> List[Dict]:
        """Get random fake users"""
        if count is None:
            # Random between 60-70
            count = random.randint(60, 70)
        
        users = list(self.fake_users.values())
        count = min(count, len(users))
        return random.sample(users, count)
    
    
    
    
    
    def get_fake_user(self, user_id: int) -> Optional[Dict]:
        """Get fake user by ID"""
        return self.fake_users.get(user_id)
    
    # ==================== FIXED: Generate valid Bingo cards ====================
    def generate_bingo_card(self) -> Dict:
        """
        Generate a valid 5x5 bingo card following official Bingo rules:
        - B column: numbers 1-15
        - I column: numbers 16-30
        - N column: numbers 31-45
        - G column: numbers 46-60
        - O column: numbers 61-75
        - Each column has 5 unique numbers from its range
        - Center cell (row 2, col 2) is FREE (0)
        """
        import random
        
        # Create separate pools for each column
        column_pools = {
            'B': list(range(1, 16)),
            'I': list(range(16, 31)),
            'N': list(range(31, 46)),
            'G': list(range(46, 61)),
            'O': list(range(61, 76))
        }
        
        # Shuffle each column pool
        for col in column_pools.values():
            random.shuffle(col)
        
        # Build the grid column by column
        grid = []
        numbers = []
        
        # Create 5 rows
        for row in range(5):
            row_data = []
            for col_idx, col_name in enumerate(['B', 'I', 'N', 'G', 'O']):
                if row == 2 and col_idx == 2:
                    # Center is FREE
                    num = 0
                else:
                    # Take one number from the column pool
                    num = column_pools[col_name].pop()
                row_data.append(num)
                numbers.append(num)
            grid.append(row_data)
        
        # Verify the card is valid
        if not self._verify_card_validity(grid):
            logger.error("Generated invalid card, retrying...")
            return self.generate_bingo_card()  # Recursive retry
        
        return {
            'grid': grid,
            'numbers': numbers
        }
    
    def _verify_card_validity(self, grid):
        """Verify that the card follows Bingo rules"""
        try:
            # Check each column
            for col in range(5):
                col_numbers = []
                for row in range(5):
                    num = grid[row][col]
                    if num != 0:  # Skip FREE space
                        col_numbers.append(num)
                
                # Check column ranges
                if col == 0:  # B column
                    assert all(1 <= n <= 15 for n in col_numbers), f"Invalid B column: {col_numbers}"
                elif col == 1:  # I column
                    assert all(16 <= n <= 30 for n in col_numbers), f"Invalid I column: {col_numbers}"
                elif col == 2:  # N column
                    assert all(31 <= n <= 45 for n in col_numbers), f"Invalid N column: {col_numbers}"
                elif col == 3:  # G column
                    assert all(46 <= n <= 60 for n in col_numbers), f"Invalid G column: {col_numbers}"
                elif col == 4:  # O column
                    assert all(61 <= n <= 75 for n in col_numbers), f"Invalid O column: {col_numbers}"
                
                # Check for duplicates
                assert len(col_numbers) == len(set(col_numbers)), f"Duplicate in column {col}: {col_numbers}"
            
            return True
        except AssertionError as e:
            logger.warning(f"Card validation failed: {e}")
            return False
    
    def create_fake_user_card(self, game_id: str, fake_user_id: int, card_index: int) -> Optional[Dict]:
        """Create a card for a fake user in a game (memory only)"""
        if game_id not in self.game_fake_cards:
            self.game_fake_cards[game_id] = {}
            self.game_purchase_order[game_id] = []
        
        # Generate valid card
        card_data = self.generate_bingo_card()
        
        fake_card = {
            'user_id': fake_user_id,
            'game_id': game_id,
            'card_index': card_index,
            'card_data': json.dumps(card_data['grid']),
            'card_numbers': json.dumps(card_data['numbers']),
            'marked_numbers': [],
            'purchased_at': datetime.now().isoformat(),
            'is_winner': False,
            'is_fake': True
        }
        
        self.game_fake_cards[game_id][fake_user_id] = fake_card
        self.game_purchase_order[game_id].append(fake_user_id)
        return fake_card
    
    # ==================== CRITICAL FIX: Create fake card that affects prize pool like real players ====================
    def create_fake_user_card_in_db(self, game_id: str, fake_user_id: int, card_index: int) -> Optional[Dict]:
        """
        Create a card for a fake user - FULLY behaves like real (affects prize pool)
        CRITICAL: Adds 8 birr to prize pool and 2 birr to house commission
        """
        try:
            from database.db import Database
            
            # First ensure the fake user exists in users table
            fake_user = self.fake_users.get(fake_user_id)
            if not fake_user:
                logger.error(f"Fake user {fake_user_id} not found in memory")
                return None
            
            # Generate valid card
            card_data = self.generate_bingo_card()
            card_numbers = card_data['numbers']
            card_grid = card_data['grid']
            
            # Verify card is valid before inserting
            if not self._verify_card_validity(card_grid):
                logger.error(f"Generated invalid card for user {fake_user_id}, regenerating...")
                card_data = self.generate_bingo_card()
                card_numbers = card_data['numbers']
                card_grid = card_data['grid']
            
            # IMPORTANT: Insert into database so frontend sees it as sold
            with Database.get_cursor() as cursor:
                # First, check if this card index is already taken
                cursor.execute("""
                    SELECT id FROM player_cards 
                    WHERE game_id = ? AND card_index = ? AND is_active = 1
                """, (game_id, card_index))
                
                existing = cursor.fetchone()
                if existing:
                    logger.warning(f"Card #{card_index} already exists in database for game {game_id}")
                    return None
                
                # Insert the fake card
                cursor.execute("""
                    INSERT INTO player_cards (
                        user_id, game_id, card_index, card_data, card_numbers,
                        purchase_price, is_active, is_fake, purchase_time
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    fake_user_id,
                    game_id,
                    card_index,
                    json.dumps(card_grid),
                    json.dumps(card_numbers),
                    10.00,  # purchase_price
                    1,  # is_active
                    1,  # is_fake
                    datetime.now()  # purchase_time
                ))
                card_id = cursor.lastrowid
                
                # ========== CRITICAL: Fake users affect prize pool like real players! ==========
                # Each fake player adds 8 birr to prize pool
                cursor.execute("""
                    UPDATE games 
                    SET prize_pool = COALESCE(prize_pool, 0) + 8.00 
                    WHERE game_id = ?
                """, (game_id,))
                
                # Add commission to house balance (2 birr per fake player)
                cursor.execute("""
                    INSERT INTO house_balance (amount, transaction_type, description, game_id, created_at)
                    VALUES (2.00, 'fake_user_commission', ?, ?, ?)
                """, (f'Fake user card #{card_index} commission', game_id, datetime.now()))
            
            logger.info(f"🎭 Fake user {fake_user['username']} purchased card #{card_index} - Added 8 birr to prize pool, 2 birr commission")
            
            # Also store in memory for quick access
            if game_id not in self.game_fake_cards:
                self.game_fake_cards[game_id] = {}
                self.game_purchase_order[game_id] = []
            
            fake_card = {
                'id': card_id,
                'user_id': fake_user_id,
                'game_id': game_id,
                'card_index': card_index,
                'card_data': json.dumps(card_grid),
                'card_numbers': json.dumps(card_numbers),
                'marked_numbers': [],
                'purchased_at': datetime.now().isoformat(),
                'is_winner': False,
                'is_fake': True
            }
            
            self.game_fake_cards[game_id][fake_user_id] = fake_card
            self.game_purchase_order[game_id].append(fake_user_id)
            return fake_card
            
        except Exception as e:
            logger.error(f"Error creating fake user card in DB: {e}")
            return None
    
    def get_available_card_numbers(self, game_id: str, taken_cards: List[int] = None) -> List[int]:
        """Get available card numbers for fake users (1-400)"""
        from database.db import Database
        
        all_cards = list(range(1, 401))
        
        # Get taken cards from real users in database (only active cards)
        if taken_cards is None:
            with Database.get_cursor() as cursor:
                cursor.execute("""
                    SELECT card_index FROM player_cards 
                    WHERE game_id = ? AND is_active = 1
                """, (game_id,))
                taken_cards = [row['card_index'] for row in cursor.fetchall()]
        
        # Get taken cards from fake users (in memory)
        fake_taken = []
        if game_id in self.game_fake_cards:
            fake_taken = [card['card_index'] for card in self.game_fake_cards[game_id].values()]
        
        all_taken = set(taken_cards + fake_taken)
        available = [num for num in all_cards if num not in all_taken]
        
        # Prefer cards from 1-100 range
        preferred = [num for num in available if num <= 100]
        other = [num for num in available if num > 100]
        
        return preferred + other if preferred else other
    
    # ==================== CRITICAL FIX: Broadcast each fake card immediately after purchase ====================
    async def _broadcast_fake_card_purchase(self, game_id: str, card_index: int):
        """Broadcast a single fake card purchase to all clients"""
        if not websocket_server:
            return
        
        try:
            from database.db import Database
            
            # Get updated counts
            with Database.get_cursor() as cursor:
                cursor.execute("""
                    SELECT 
                        COUNT(CASE WHEN is_fake = 0 AND is_active = 1 THEN 1 END) as real_players,
                        COUNT(CASE WHEN is_fake = 1 AND is_active = 1 THEN 1 END) as fake_players
                    FROM player_cards 
                    WHERE game_id = ?
                """, (game_id,))
                row = cursor.fetchone()
                real_players = row['real_players'] if row else 0
                fake_players = row['fake_players'] if row else 0
                total_players = real_players + fake_players
                
                # Calculate correct prize pool based on total players
                correct_prize_pool = total_players * 8.00
            
            # Broadcast single card purchase
            await websocket_server.broadcast_with_retry({
                'type': 'fake_card_purchased',
                'game_id': game_id,
                'card_index': card_index,
                'real_players': real_players,
                'fake_players': fake_players,
                'total_players': total_players,
                'prize_pool': correct_prize_pool,
                'timestamp': datetime.now().isoformat()
            })
            
            logger.info(f"🎭 Broadcast fake card #{card_index} purchase for game {game_id}")
            
        except Exception as e:
            logger.error(f"Error broadcasting fake card purchase: {e}")
    
    # ==================== SIMPLIFIED: Just purchases at different intervals ====================
    async def select_fake_user_cards_async(self, game_id: str, count: int = None) -> List[Dict]:
        """
        Select cards for fake users - FIXED: Broadcast immediately after each card creation
        Cards appear gradually throughout the countdown for natural feel
        """
        from database.db import Database
        import asyncio
        import time
        
        # Get fake users
        fake_users = self.get_random_fake_users(count)
        if not fake_users:
            return []
        
        # Get available cards from database
        available_cards = self.get_available_card_numbers(game_id)
        if not available_cards:
            logger.warning(f"No available cards for game {game_id}")
            return []
        
        selected_cards = []
        cards_added = 0
        
        # ========== SIMPLE INTERVAL MODEL ==========
        # Generate purchase delays that spread purchases across the 30-second window
        
        # Determine total number of fake users to add
        total_to_add = min(count if count else len(fake_users), len(available_cards))
        
        # Create a list of purchase delays (0-25 seconds range)
        # This spreads purchases across the countdown window
        purchase_delays = []
        
        for i in range(total_to_add):
            # Simple distribution - some early, some middle, some late
            if i < total_to_add * 0.3:  # First 30% - early purchases (0-5 seconds)
                delay = random.uniform(0.5, 5.0)
            elif i < total_to_add * 0.7:  # Next 40% - mid purchases (5-15 seconds)
                delay = random.uniform(5.0, 15.0)
            else:  # Last 30% - late purchases (15-25 seconds)
                delay = random.uniform(15.0, 25.0)
            
            purchase_delays.append(delay)
        
        # Sort by delay so earliest purchases happen first
        # This creates a natural progression of purchases over time
        user_delay_pairs = list(zip(fake_users[:total_to_add], purchase_delays))
        user_delay_pairs.sort(key=lambda x: x[1])
        
        logger.info(f"🎭 Adding {total_to_add} fake users to game {game_id} over {purchase_delays[-1]:.1f}s")
        
        start_time = time.time()
        
        for fake_user, delay in user_delay_pairs:
            if cards_added >= total_to_add:
                break
                
            if not available_cards:
                break
            
            # Wait for the calculated delay
            elapsed = time.time() - start_time
            if delay > elapsed:
                wait_time = delay - elapsed
                if wait_time > 0.5:  # Only log if noticeable
                    logger.info(f"🎭 {fake_user['username']} will purchase in {wait_time:.1f}s")
                await asyncio.sleep(wait_time)
            
            # User selects a random card from available ones
            card_index = random.choice(available_cards)
            available_cards.remove(card_index)
            
            # Purchase the card (this now adds to prize pool and commission)
            fake_card = self.create_fake_user_card_in_db(
                game_id, 
                fake_user['user_id'], 
                card_index
            )
            
            if fake_card:
                selected_cards.append(fake_card)
                cards_added += 1
                
                total_elapsed = time.time() - start_time
                logger.info(f"🎭 ✅ {fake_user['username']} purchased card #{card_index} at {total_elapsed:.1f}s")
                
                # ==================== CRITICAL FIX: Broadcast after each card is created ====================
                # This sends the card index to all connected clients immediately
                await self._broadcast_fake_card_purchase(game_id, card_index)
        
        total_time = time.time() - start_time
        if selected_cards:
            logger.info(f"🎭 Added {len(selected_cards)} fake cards to game {game_id} in {total_time:.1f}s")
        else:
            logger.warning(f"🎭 No fake cards added to game {game_id}")
        
        return selected_cards
    
    # ==================== CRITICAL FIX: Remove fake user card (DOES NOT affect prize pool) ====================
    def remove_fake_user_card(self, game_id: str, count: int = 1) -> int:
        """
        Remove fake user cards when real users join.
        Maintains minimum fake players by removing oldest purchases first (FIFO).
        Returns number of fake users actually removed.
        
        CRITICAL: Exactly 1 fake user removed for each real user that joins.
        CRITICAL: Prize pool is NOT adjusted when removing fake users because:
                 - Fake players already contributed to prize pool when they joined
                 - Removing them doesn't refund their contribution
                 - Prize pool remains the same (already counted)
        CRITICAL: House commission is NOT adjusted when removing fake users because:
                 - Commission already collected when they joined
                 - Stays in house balance
        """
        if game_id not in self.game_fake_cards:
            logger.info(f"🎭 No fake cards in game {game_id} to remove")
            return 0
        
        from database.db import Database
        fake_cards = self.game_fake_cards.get(game_id, {})
        
        if not fake_cards:
            return 0
        
        # Get purchase order (oldest first)
        purchase_order = self.game_purchase_order.get(game_id, [])
        
        # If no purchase order recorded, fallback to any order
        if not purchase_order:
            purchase_order = list(fake_cards.keys())
        
        removed = 0
        removed_users = []
        
        # Remove exactly 'count' fake users (but not more than available)
        to_remove = min(count, len(purchase_order))
        
        for i in range(to_remove):
            if i >= len(purchase_order):
                break
                
            user_id = purchase_order[i]
            card = fake_cards.get(user_id)
            
            if not card:
                continue
            
            card_index = card.get('card_index')
            card_id = card.get('id')
            
            # Double-check this is still a fake card in database
            try:
                with Database.get_cursor() as cursor:
                    cursor.execute("""
                        SELECT id FROM player_cards 
                        WHERE id = ? AND game_id = ? AND is_fake = 1 AND is_active = 1
                    """, (card_id, game_id))
                    
                    if cursor.fetchone():
                        # Safe to remove - soft delete (mark as inactive)
                        cursor.execute("""
                            UPDATE player_cards 
                            SET is_active = 0 
                            WHERE id = ?
                        """, (card_id,))
                        
                        # ========== CRITICAL: DO NOT adjust prize pool when removing fake users ==========
                        # Prize pool already includes their contribution and stays the same
                        # The following lines are REMOVED/COMMENTED OUT:
                        # cursor.execute("""
                        #     UPDATE games 
                        #     SET prize_pool = MAX(0, prize_pool - 8.00)
                        #     WHERE game_id = ?
                        # """, (game_id,))
                        
                        # ========== CRITICAL: DO NOT adjust house balance when removing fake users ==========
                        # Commission already collected and stays in house
                        # The following lines are REMOVED/COMMENTED OUT:
                        # cursor.execute("""
                        #     INSERT INTO house_balance (amount, transaction_type, description, game_id, created_at)
                        #     VALUES (-2.00, 'fake_user_refund', ?, ?, ?)
                        # """, (f'Refund for fake user card #{card_index} removed', game_id, datetime.now()))
                        
                        logger.info(f"🎭 Removed fake user card #{card_index} from database (prize pool unchanged, house commission unchanged)")
                        
                        # Remove from memory
                        del self.game_fake_cards[game_id][user_id]
                        removed += 1
                        removed_users.append(user_id)
                        
            except Exception as e:
                logger.error(f"Error removing fake card from DB: {e}")
        
        # Update purchase order to remove the users we deleted
        if removed_users and game_id in self.game_purchase_order:
            self.game_purchase_order[game_id] = [
                uid for uid in self.game_purchase_order[game_id] 
                if uid not in removed_users
            ]
        
        if removed > 0:
            logger.info(f"🎭 Removed {removed} fake users from game {game_id} (1:1 ratio for real players)")
        
        return removed
    
    # ==================== ENHANCED: Batch removal for multiple real players ====================
    def remove_multiple_fake_cards(self, game_id: str, real_player_count: int) -> int:
        """
        Remove multiple fake cards at once (e.g., when multiple real players join).
        Maintains minimum fake players.
        
        Args:
            game_id: Game ID
            real_player_count: Number of real players that joined
            
        Returns:
            Number of fake users actually removed
        """
        if real_player_count <= 0:
            return 0
            
        total_removed = 0
        for _ in range(real_player_count):
            # Get current fake count before removal
            from database.db import Database
            with Database.get_cursor() as cursor:
                cursor.execute("""
                    SELECT COUNT(*) as count FROM player_cards 
                    WHERE game_id = ? AND is_fake = 1 AND is_active = 1
                """, (game_id,))
                result = cursor.fetchone()
                current_fake = result['count'] if result else 0
            
            # Stop if we'd go below minimum 10
            if current_fake <= 10:
                logger.info(f"🎭 Minimum fake players (10) reached, cannot remove more")
                break
                
            removed = self.remove_fake_user_card(game_id, 1)
            if removed == 0:
                break
            total_removed += 1
        
        if total_removed > 0:
            logger.info(f"🎭 Removed {total_removed} fake users for {real_player_count} new real players")
        
        return total_removed
    
    # ==================== ENHANCED: Check and maintain minimum fake players ====================
    async def ensure_minimum_fake_players(self, game_id: str, min_required: int = 300) -> int:
        """
        Ensure game has at least the minimum number of fake players.
        Adds more fake users if needed.
        
        Returns:
            Number of fake users added
        """
        from database.db import Database
        
        # Get current fake count from database
        with Database.get_cursor() as cursor:
            cursor.execute("""
                SELECT COUNT(*) as count FROM player_cards 
                WHERE game_id = ? AND is_fake = 1 AND is_active = 1
            """, (game_id,))
            result = cursor.fetchone()
            current_fake = result['count'] if result else 0
        
        # Get real player count
        with Database.get_cursor() as cursor:
            cursor.execute("""
                SELECT COUNT(*) as count FROM player_cards 
                WHERE game_id = ? AND is_fake = 0 AND is_active = 1
            """, (game_id,))
            real_result = cursor.fetchone()
            real_count = real_result['count'] if real_result else 0
        
        total_players = current_fake + real_count
        
        # Calculate how many we can add without exceeding 400
        max_can_add = 400 - total_players
        target = min(min_required, max_can_add + current_fake)
        
        if current_fake >= target:
            logger.info(f"🎭 Game {game_id} already has {current_fake} fake players (target: {target})")
            return 0
        
        fake_needed = min(target - current_fake, max_can_add)
        if fake_needed <= 0:
            logger.info(f"🎭 Game {game_id} at max capacity (400), cannot add more fake players")
            return 0
        
        logger.info(f"🎭 Game {game_id} needs {fake_needed} more fake players (current: {current_fake}, real: {real_count}, total: {total_players})")
        
        added = await self.select_fake_user_cards_async(game_id, fake_needed)
        return len(added)
    
    # Keep synchronous version for backward compatibility
    def select_fake_user_cards(self, game_id: str, count: int = None) -> List[Dict]:
        """Legacy synchronous version - use async version for natural timing"""
        logger.warning("Use select_fake_user_cards_async for natural timing")
        return []
    
    # ==================== FIXED: Mark number on fake cards with realistic delays ====================
    async def mark_number_on_fake_cards_async(self, game_id: str, number: int) -> Tuple[int, List]:
        """
        Mark a number on all fake user cards in a game with realistic timing delays.
        Fake players don't mark numbers instantly - they have varying reaction times.
        """
        if game_id not in self.game_fake_cards:
            return 0, []
        
        # Record the time this number was called for this game
        self.last_number_time[game_id] = time.time()
        
        updated_count = 0
        winners = []
        
        # Create a list of tasks with random delays for each fake player
        tasks = []
        for user_id, card in list(self.game_fake_cards[game_id].items()):
            if card.get('is_winner'):
                continue
            
            # Each fake player has a different reaction time
            # Some react quickly (0.5-2 seconds), others take their time (2-5 seconds)
            # This mimics real human behavior
            reaction_delay = random.uniform(0.5, 3.0)
            
            # Schedule the marking with delay
            tasks.append(self._delayed_mark_number(
                game_id, user_id, card, number, reaction_delay
            ))
        
        if tasks:
            # Wait for all fake players to "react" and mark their cards
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for result in results:
                if isinstance(result, tuple) and len(result) == 2:
                    marked, winner_info = result
                    updated_count += 1 if marked else 0
                    if winner_info:
                        # ==================== CRITICAL FIX: Process winner immediately ====================
                        # No delay - when fake player gets BINGO, claim immediately
                        card, pattern_type = winner_info
                        
                        # Trigger winner processing immediately
                        from game_manager import game_manager
                        asyncio.create_task(game_manager.process_fake_winner(
                            game_id, user_id, card, pattern_type
                        ))
                        
                        winners.append(winner_info)
        
        if updated_count > 0:
            logger.info(f"🎭 Marked number {number} on {updated_count} fake cards in game {game_id} with realistic delays, found {len(winners)} winners")
        
        return updated_count, winners
    
    async def _delayed_mark_number(self, game_id: str, user_id: int, card: Dict, number: int, delay: float):
        """Mark a number on a fake card after a delay"""
        try:
            await asyncio.sleep(delay)
            
            # Parse card numbers
            try:
                card_numbers = json.loads(card['card_numbers'])
            except:
                return False, None
            
            marked = card.get('marked_numbers', [])
            
            if number in card_numbers and number not in marked:
                marked.append(number)
                card['marked_numbers'] = marked
                
                # Check for bingo with pattern detection
                has_bingo, pattern_type = self.check_bingo_with_pattern(card_numbers, marked)
                if has_bingo and not card.get('is_winner'):
                    card['is_winner'] = True
                    logger.info(f"🎭 Fake user {user_id} got BINGO in game {game_id} with pattern: {pattern_type} (after {delay:.1f}s delay)")
                    
                    # ==================== CRITICAL FIX: Return winner info immediately ====================
                    # The caller will process this without additional delay
                    return True, (card, pattern_type)
            
            return True, None
            
        except Exception as e:
            logger.error(f"Error in delayed marking for user {user_id}: {e}")
            return False, None
    
    # Synchronous version for backward compatibility
    def mark_number_on_fake_cards(self, game_id: str, number: int) -> Tuple[int, List]:
        """
        Synchronous version - WARNING: Does NOT have realistic delays!
        Use mark_number_on_fake_cards_async for realistic timing.
        """
        if game_id not in self.game_fake_cards:
            return 0, []
        
        updated_count = 0
        winners = []
        
        for user_id, card in list(self.game_fake_cards[game_id].items()):
            if card.get('is_winner'):
                continue
            
            # Parse card numbers
            try:
                card_numbers = json.loads(card['card_numbers'])
            except:
                continue
                
            marked = card.get('marked_numbers', [])
            
            if number in card_numbers and number not in marked:
                marked.append(number)
                card['marked_numbers'] = marked
                updated_count += 1
                
                # Check for bingo with pattern detection
                has_bingo, pattern_type = self.check_bingo_with_pattern(card_numbers, marked)
                if has_bingo and not card.get('is_winner'):
                    card['is_winner'] = True
                    winners.append((card, pattern_type))
                    logger.info(f"🎭 Fake user {user_id} got BINGO in game {game_id} with pattern: {pattern_type} (SYNC)")
        
        if updated_count > 0:
            logger.info(f"🎭 (SYNC) Marked number {number} on {updated_count} fake cards in game {game_id}, found {len(winners)} winners")
        
        return updated_count, winners
    
    def check_bingo_with_pattern(self, card_numbers: List[int], marked_numbers: List[int]) -> Tuple[bool, str]:
        """Check if card has bingo and return the pattern type"""
        if len(card_numbers) != 25:
            return False, "invalid"
        
        # Convert to grid
        grid = []
        for i in range(0, 25, 5):
            grid.append(card_numbers[i:i+5])
        
        marked_set = set(marked_numbers)
        
        # ====== CHECK 4 CORNERS FIRST ======
        corners = [grid[0][0], grid[0][4], grid[4][0], grid[4][4]]
        corners_complete = all(corner in marked_set for corner in corners)
        if corners_complete:
            return True, "four_corners"
        
        # Check rows
        for row in range(5):
            row_complete = True
            row_numbers = []
            for col in range(5):
                if row == 2 and col == 2:  # FREE space
                    continue
                if grid[row][col] not in marked_set:
                    row_complete = False
                    break
                row_numbers.append(grid[row][col])
            if row_complete:
                return True, f"row_{row}"
        
        # Check columns
        for col in range(5):
            col_complete = True
            col_numbers = []
            for row in range(5):
                if row == 2 and col == 2:  # FREE space
                    continue
                if grid[row][col] not in marked_set:
                    col_complete = False
                    break
                col_numbers.append(grid[row][col])
            if col_complete:
                return True, f"column_{col}"
        
        # Check main diagonal
        diag1_complete = True
        diag1_numbers = []
        for i in range(5):
            if i == 2:  # Center is FREE
                continue
            if grid[i][i] not in marked_set:
                diag1_complete = False
                break
            diag1_numbers.append(grid[i][i])
        if diag1_complete:
            return True, "main_diagonal"
        
        # Check anti-diagonal
        diag2_complete = True
        diag2_numbers = []
        for i in range(5):
            if i == 2:  # Center is FREE
                continue
            if grid[i][4-i] not in marked_set:
                diag2_complete = False
                break
            diag2_numbers.append(grid[i][4-i])
        if diag2_complete:
            return True, "anti_diagonal"
        
        return False, "none"
    
    def check_bingo(self, card_numbers: List[int], marked_numbers: List[int]) -> bool:
        """Legacy method - returns just boolean"""
        result, _ = self.check_bingo_with_pattern(card_numbers, marked_numbers)
        return result
    
    def get_total_player_count(self, game_id: str) -> int:
        """Get total players (real + fake) in a game"""
        from database.db import Database
        
        with Database.get_cursor() as cursor:
            cursor.execute("""
                SELECT COUNT(*) as count FROM player_cards 
                WHERE game_id = ? AND is_active = 1
            """, (game_id,))
            result = cursor.fetchone()
            return result['count'] if result else 0
    
    def get_real_player_count(self, game_id: str) -> int:
        """Get real player count in a game"""
        from database.db import Database
        
        with Database.get_cursor() as cursor:
            cursor.execute("""
                SELECT COUNT(*) as count FROM player_cards 
                WHERE game_id = ? AND is_fake = 0 AND is_active = 1
            """, (game_id,))
            result = cursor.fetchone()
            return result['count'] if result else 0
    
    def get_fake_player_count(self, game_id: str) -> int:
        """Get fake player count in a game (from database)"""
        from database.db import Database
        
        with Database.get_cursor() as cursor:
            cursor.execute("""
                SELECT COUNT(*) as count FROM player_cards 
                WHERE game_id = ? AND is_fake = 1 AND is_active = 1
            """, (game_id,))
            result = cursor.fetchone()
            return result['count'] if result else 0
    
    # ==================== CRITICAL FIX: Claim bingo for fake winners - INSTANT! ====================
    async def claim_bingo_for_fake_winners_async(self, game_id: str) -> List[Dict]:
        """
        Fake winners claim bingo INSTANTLY (no delays).
        When a fake player gets BINGO, they claim immediately for faster game flow.
        """
        if game_id not in self.game_fake_cards:
            return []
        
        winners = []
        winner_cards = []
        
        # Find all fake winners
        for user_id, card in self.game_fake_cards[game_id].items():
            if card.get('is_winner') and not card.get('bingo_claimed'):
                # This fake player has bingo but hasn't claimed yet
                card['bingo_claimed'] = False  # Mark as ready to claim
                winner_cards.append((user_id, card))
        
        if not winner_cards:
            return []
        
        logger.info(f"🎭 {len(winner_cards)} fake winners claiming BINGO INSTANTLY...")
        
        # ==================== CRITICAL FIX: NO DELAYS ====================
        # Process all winners immediately without any waiting
        for user_id, card in winner_cards:
            card['bingo_claimed'] = True
            
            logger.info(f"🎭 Fake user {user_id} claimed BINGO INSTANTLY")
            
            winners.append({
                'user_id': user_id,
                'card': card,
                'pattern_type': card.get('winning_pattern', 'unknown'),
                'claim_delay': 0  # Instant claim
            })
        
        if winners:
            logger.info(f"🎭 {len(winners)} fake winners claimed bingo INSTANTLY")
        
        return winners
    
    # ==================== CRITICAL FIX: Cleanup game (DOES NOT affect prize pool) ====================
    def cleanup_game(self, game_id: str):
        """
        Clean up fake user data for a game - FIXED: Soft delete, prize pool already accounted for
        CRITICAL: Does NOT adjust prize pool or house balance
        """
        if game_id in self.game_fake_cards:
            # Soft delete from database (mark as inactive)
            try:
                from database.db import Database
                with Database.get_cursor() as cursor:
                    cursor.execute("""
                        UPDATE player_cards 
                        SET is_active = 0 
                        WHERE game_id = ? AND is_fake = 1
                    """, (game_id,))
                    
                    # ========== CRITICAL: DO NOT adjust prize pool when cleaning up ==========
                    # Prize pool already accounted for during the game
                    # The following lines are REMOVED/COMMENTED OUT:
                    # cursor.execute("""
                    #     SELECT COUNT(*) as fake_count FROM player_cards 
                    #     WHERE game_id = ? AND is_fake = 1 AND is_active = 0
                    # """, (game_id,))
                    # result = cursor.fetchone()
                    # fake_count = result['fake_count'] if result else 0
                    # 
                    # if fake_count > 0:
                    #     cursor.execute("""
                    #         UPDATE games 
                    #         SET prize_pool = MAX(0, prize_pool - (? * 8.00))
                    #         WHERE game_id = ?
                    #     """, (fake_count, game_id))
                    
                    # ========== CRITICAL: DO NOT adjust house balance when cleaning up ==========
                    # Commission already collected and stays in house
                    # No house balance adjustment needed
                    
            except Exception as e:
                logger.error(f"Error cleaning up fake cards from DB: {e}")
            
            # Clear last number time
            if game_id in self.last_number_time:
                del self.last_number_time[game_id]
            
            del self.game_fake_cards[game_id]
            
            if game_id in self.game_purchase_order:
                del self.game_purchase_order[game_id]
                
            logger.info(f"🧹 Cleaned up fake users for game {game_id} (prize pool unchanged)")

# Global instance
fake_user_manager = FakeUserManager()