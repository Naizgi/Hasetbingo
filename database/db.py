# database/db.py - Complete Database Schema with ALL missing methods
# FIXED: Added is_fake column handling, fixed player counts, added prize pool methods
# CRITICAL FIX: Added mark_number_on_real_cards method
# CRITICAL FIX: Added mark_number_on_fake_cards method
# CRITICAL FIX: Added get_drawn_numbers method
# CRITICAL FIX: Added get_last_number_call_time method
# CRITICAL FIX: Added commission_records table for separate commission tracking
# FIXED: Added missing fake_players table for admin panel balance calculation
# ADDED: Admin credentials table for authentication
# ADDED: Player card created_at column for better tracking

import sqlite3
import logging
import asyncio
import json
import decimal
from decimal import Decimal
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any, Tuple
import os
from contextlib import contextmanager

logger = logging.getLogger(__name__)

class Database:
    # SQLite connection
    _conn = None
    # FIX: Use absolute path to avoid directory creation issues
    _db_path = os.path.join(os.getcwd(), os.getenv('DB_PATH', 'habesha_bingo.db'))
    # Add lock for async operations
    _lock = asyncio.Lock()
    
    @classmethod
    def get_connection(cls):
        """Get or create database connection"""
        if cls._conn is None:
            try:
                # FIX: Handle directory creation properly
                db_path = cls._db_path
                
                # Ensure directory exists
                db_dir = os.path.dirname(db_path)
                if db_dir:  # Only create directory if path has one
                    os.makedirs(db_dir, exist_ok=True)
                
                # Create connection
                cls._conn = sqlite3.connect(
                    db_path,
                    check_same_thread=False,  # Allow access from multiple threads
                    detect_types=sqlite3.PARSE_DECLTYPES
                )
                cls._conn.row_factory = sqlite3.Row  # Return rows as dict-like objects
                
                # Enable foreign keys
                cls._conn.execute("PRAGMA foreign_keys = ON")
                
                # Enable WAL mode for better concurrency
                cls._conn.execute("PRAGMA journal_mode = WAL")
                
                logger.info(f"SQLite database connection created: {db_path}")
                
                # Initialize database tables
                cls._initialize_database()
                
            except Exception as e:
                logger.error(f"Failed to create database connection: {e}")
                raise
        return cls._conn
    
    @classmethod
    def _initialize_database(cls):
        """Initialize all database tables"""
        try:
            conn = cls.get_connection()
            cursor = conn.cursor()
            
            # 1. USERS TABLE - UPDATED WITH ADMIN PANEL COLUMNS
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    full_name TEXT,
                    balance REAL DEFAULT 1000.00,
                    total_wins INTEGER DEFAULT 0,
                    total_games_played INTEGER DEFAULT 0,
                    total_winnings REAL DEFAULT 0.00,
                    status TEXT DEFAULT 'active',
                    is_admin INTEGER DEFAULT 0,
                    deleted_at TIMESTAMP DEFAULT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    total_withdrawals REAL DEFAULT 0.00,
                    total_deposits REAL DEFAULT 0.00,
                    used_initial_balance INTEGER DEFAULT 0
                )
            """)
            
            # Create indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_balance ON users (balance)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_created ON users (created_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_status ON users (status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_admin ON users (is_admin)")
            
            # 2. GAMES TABLE (ROUND-BASED ONLY) - REMOVED COMMISSION FIELDS
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS games (
                    game_id TEXT PRIMARY KEY,
                    game_type TEXT DEFAULT 'round_based',
                    status TEXT DEFAULT 'card_purchase',
                    round_number INTEGER NOT NULL DEFAULT 1,
                    card_price REAL DEFAULT 10.00,
                    prize_pool REAL DEFAULT 0.00,
                    current_number INTEGER DEFAULT NULL,
                    total_players INTEGER DEFAULT 0,
                    total_cards_sold INTEGER DEFAULT 0,
                    winner_id INTEGER DEFAULT NULL,
                    winner_card_id INTEGER DEFAULT NULL,
                    winner_payout REAL DEFAULT 0.00,
                    started_at TIMESTAMP DEFAULT NULL,
                    completed_at TIMESTAMP DEFAULT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    purchase_end_time TIMESTAMP DEFAULT NULL,
                    countdown_remaining INTEGER DEFAULT 30,
                    called_numbers TEXT DEFAULT '[]',
                    current_phase TEXT DEFAULT 'card_purchase',
                    countdown_end REAL DEFAULT NULL,
                    winner_display_end TIMESTAMP DEFAULT NULL,
                    real_cards_sold INTEGER DEFAULT 0,
                    total_sales REAL DEFAULT 0.00,
                    winners_count INTEGER DEFAULT 0
                )
            """)
            
            # Create indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_games_status ON games (status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_games_round ON games (round_number)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_games_created ON games (created_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_games_type ON games (game_type)")
            
            # 3. PLAYER_CARDS TABLE - ADDED is_fake COLUMN AND created_at COLUMN
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS player_cards (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    game_id TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    card_index INTEGER NOT NULL,
                    card_numbers TEXT NOT NULL,
                    card_data TEXT DEFAULT NULL,
                    purchase_price REAL DEFAULT 10.00,
                    has_bingo INTEGER DEFAULT 0,
                    prize_won REAL DEFAULT 0.00,
                    bingo_claimed_at TIMESTAMP DEFAULT NULL,
                    purchase_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                     created_at TIMESTAMP,
                    is_active INTEGER DEFAULT 1,
                    is_fake INTEGER DEFAULT 0,
                    refunded_at TIMESTAMP DEFAULT NULL,
                    FOREIGN KEY (game_id) REFERENCES games(game_id) ON DELETE CASCADE,
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
                )
            """)
            
            # Create indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_player_cards_game_user ON player_cards (game_id, user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_player_cards_game ON player_cards (game_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_player_cards_user ON player_cards (user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_player_cards_bingo ON player_cards (has_bingo)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_player_cards_card_index ON player_cards (game_id, card_index)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_player_cards_fake ON player_cards (is_fake)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_player_cards_active ON player_cards (is_active)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_player_cards_created ON player_cards (created_at)")
            
            # 4. TRANSACTIONS TABLE
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    amount REAL NOT NULL,
                    balance_after REAL NOT NULL,
                    transaction_type TEXT NOT NULL,
                    description TEXT,
                    game_id TEXT DEFAULT NULL,
                    card_id INTEGER DEFAULT NULL,
                    reference_id TEXT DEFAULT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                    FOREIGN KEY (game_id) REFERENCES games(game_id) ON DELETE SET NULL
                )
            """)
            
            # Create indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_transactions_user ON transactions (user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_transactions_game ON transactions (game_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_transactions_type ON transactions (transaction_type)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_transactions_created ON transactions (created_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_transactions_user_game ON transactions (user_id, game_id)")
            
            # 5. GAME_HISTORY TABLE - UPDATED WITH NEW COLUMNS (NO COMMISSION FIELDS)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS game_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    game_id TEXT NOT NULL,
                    game_type TEXT NOT NULL,
                    round_number INTEGER NOT NULL,
                    total_players INTEGER DEFAULT 0,
                    total_cards_sold INTEGER DEFAULT 0,
                    prize_pool REAL DEFAULT 0.00,
                    winner_id INTEGER DEFAULT NULL,
                    winner_username TEXT DEFAULT NULL,
                    winner_card_index INTEGER DEFAULT NULL,
                    winner_payout REAL DEFAULT 0.00,
                    numbers_called TEXT DEFAULT NULL,
                    called_numbers TEXT DEFAULT NULL,
                    start_time TIMESTAMP DEFAULT NULL,
                    end_time TIMESTAMP DEFAULT NULL,
                    duration_seconds INTEGER DEFAULT NULL,
                    pattern_type TEXT DEFAULT NULL,
                    winning_pattern TEXT DEFAULT NULL,
                    total_sales REAL DEFAULT 0.00,
                    game_date DATE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    real_cards_sold INTEGER DEFAULT 0,
                    fake_cards_sold INTEGER DEFAULT 0,
                    winners_count INTEGER DEFAULT 0,
                    winners_data TEXT DEFAULT NULL,
                    winner_payouts TEXT DEFAULT NULL,
                    is_fake_winner INTEGER DEFAULT 0,
                    min_fake_players INTEGER DEFAULT 10,
                    max_fake_players INTEGER DEFAULT 40
                )
            """)
            
            # Create indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_game_history_game ON game_history (game_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_game_history_winner ON game_history (winner_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_game_history_round ON game_history (round_number)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_game_history_created ON game_history (created_at)")
            
            # 6. HOUSE_BALANCE TABLE
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS house_balance (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    amount REAL NOT NULL,
                    description TEXT,
                    game_id TEXT DEFAULT NULL,
                    transaction_type TEXT DEFAULT 'commission',
                    created_by TEXT DEFAULT 'system',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_house_balance_game ON house_balance (game_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_house_balance_created ON house_balance (created_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_house_balance_type ON house_balance (transaction_type)")
            
            # 7. CALLED_NUMBERS TABLE
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS called_numbers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    game_id TEXT NOT NULL,
                    number INTEGER NOT NULL,
                    bingo_letter TEXT NOT NULL,
                    called_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    called_by TEXT DEFAULT 'system',
                    UNIQUE(game_id, number),
                    FOREIGN KEY (game_id) REFERENCES games(game_id) ON DELETE CASCADE
                )
            """)
            
            # Create indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_called_numbers_game ON called_numbers (game_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_called_numbers_number ON called_numbers (number)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_called_numbers_called_at ON called_numbers (called_at)")
            
            # 8. BINGO_CLAIMS TABLE
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS bingo_claims (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    game_id TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    card_id INTEGER NOT NULL,
                    claim_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_valid INTEGER DEFAULT 0,
                    verified_by TEXT DEFAULT NULL,
                    verification_time TIMESTAMP DEFAULT NULL,
                    notes TEXT,
                    FOREIGN KEY (game_id) REFERENCES games(game_id) ON DELETE CASCADE,
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                    FOREIGN KEY (card_id) REFERENCES player_cards(id) ON DELETE CASCADE
                )
            """)
            
            # Create indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_bingo_claims_game ON bingo_claims (game_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_bingo_claims_user ON bingo_claims (user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_bingo_claims_valid ON bingo_claims (is_valid)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_bingo_claims_claim_time ON bingo_claims (claim_time)")
            
            # 9. DRAWN_NUMBERS TABLE
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS drawn_numbers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    game_id TEXT NOT NULL,
                    number INTEGER NOT NULL,
                    drawn_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (game_id) REFERENCES games(game_id) ON DELETE CASCADE
                )
            """)
            
            # Create indexes for drawn_numbers
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_drawn_numbers_game ON drawn_numbers (game_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_drawn_numbers_number ON drawn_numbers (number)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_drawn_numbers_drawn_at ON drawn_numbers (drawn_at)")
            
            # 10. NOTIFICATIONS TABLE
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER DEFAULT NULL,
                    notification_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    message TEXT NOT NULL,
                    is_read INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    read_at TIMESTAMP DEFAULT NULL
                )
            """)
            
            # Create indexes for notifications
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications (user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_notifications_type ON notifications (notification_type)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_notifications_read ON notifications (is_read)")
            
            # 11. WITHDRAWAL_REQUESTS TABLE - FIXED WITH ALL MISSING COLUMNS
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS withdrawal_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    amount REAL NOT NULL,
                    phone_number TEXT NOT NULL,
                    method TEXT DEFAULT 'tele_birr',
                    payment_method TEXT DEFAULT 'tele_birr',
                    full_name TEXT DEFAULT NULL,
                    status TEXT DEFAULT 'pending',
                    admin_notes TEXT DEFAULT NULL,
                    processed_by INTEGER DEFAULT NULL,
                    transaction_id INTEGER DEFAULT NULL,
                    requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    processed_at TIMESTAMP DEFAULT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
                )
            """)
            
            # Create indexes for withdrawal_requests
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_withdrawal_requests_user ON withdrawal_requests (user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_withdrawal_requests_status ON withdrawal_requests (status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_withdrawal_requests_requested_at ON withdrawal_requests (requested_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_withdrawal_requests_user_id ON withdrawal_requests (user_id)")
            
            # 12. ADMIN_TRANSACTIONS TABLE
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS admin_transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    admin_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    target_type TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    details TEXT DEFAULT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create indexes for admin_transactions
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_admin_transactions_admin ON admin_transactions (admin_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_admin_transactions_action ON admin_transactions (action)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_admin_transactions_created ON admin_transactions (created_at)")
            
            # 13. PAYMENTS TABLE
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    amount REAL NOT NULL,
                    payment_method TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    transaction_id TEXT DEFAULT NULL,
                    admin_notes TEXT DEFAULT NULL,
                    processed_by INTEGER DEFAULT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    processed_at TIMESTAMP DEFAULT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
                )
            """)
            
            # Create indexes for payments
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_payments_user ON payments (user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_payments_status ON payments (status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_payments_created ON payments (created_at)")
            
            # 14. TELEBIRR_TRANSACTIONS TABLE - FIXED WITH ALL MISSING COLUMNS
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS telebirr_transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    payment_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    amount REAL NOT NULL,
                    transaction_id TEXT DEFAULT NULL,
                    sms_hash TEXT DEFAULT NULL,
                    status TEXT DEFAULT 'pending',
                    fraud_score INTEGER DEFAULT 0,
                    admin_review INTEGER DEFAULT 0,
                    api_response TEXT DEFAULT NULL,
                    receiver_phone TEXT DEFAULT NULL,
                    receiver_name TEXT DEFAULT NULL,
                    payment_method TEXT DEFAULT NULL,
                    verified_at TIMESTAMP DEFAULT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (payment_id) REFERENCES payments(id) ON DELETE CASCADE,
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
                )
            """)
            
            # Create indexes for telebirr_transactions
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_telebirr_transactions_payment ON telebirr_transactions (payment_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_telebirr_transactions_user ON telebirr_transactions (user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_telebirr_transactions_txid ON telebirr_transactions (transaction_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_telebirr_transactions_sms_hash ON telebirr_transactions (sms_hash)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_telebirr_transactions_tx_id ON telebirr_transactions (transaction_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_telebirr_transactions_payment_id ON telebirr_transactions (payment_id)")
            
            # 15. USER_FRAUD_DETECTION TABLE
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_fraud_detection (
                    user_id INTEGER PRIMARY KEY,
                    suspicious_attempts INTEGER DEFAULT 0,
                    rejected_deposits INTEGER DEFAULT 0,
                    deposit_limit REAL DEFAULT 1000.00,
                    daily_limit REAL DEFAULT 5000.00,
                    restricted_until TIMESTAMP DEFAULT NULL,
                    notes TEXT DEFAULT NULL,
                    last_suspicious_attempt TIMESTAMP DEFAULT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
                )
            """)
            
            # Create indexes for user_fraud_detection
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_fraud_detection_user ON user_fraud_detection (user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_fraud_detection_restricted ON user_fraud_detection (restricted_until)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_fraud_detection_suspicious ON user_fraud_detection (suspicious_attempts)")
            
            # 16. WEEKLY_REPORTS Commision TABLE
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS weekly_reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    week_number VARCHAR(10) NOT NULL,
                    start_date DATE NOT NULL,
                    end_date DATE NOT NULL,
                    total_games INTEGER DEFAULT 0,
                    total_cards_sold INTEGER DEFAULT 0,
                    total_sales REAL DEFAULT 0.00,
                    commission REAL DEFAULT 0.00,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(week_number)
                )
            """)
            
            # Create indexes for weekly_reports
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_weekly_reports_week ON weekly_reports (week_number)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_weekly_reports_start_date ON weekly_reports (start_date)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_weekly_reports_end_date ON weekly_reports (end_date)")
            
            # 17. ADMINS TABLE
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS admins (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL UNIQUE,
                    username TEXT NOT NULL,
                    full_name TEXT,
                    permissions TEXT DEFAULT 'all',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_active INTEGER DEFAULT 1,
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
                )
            """)
            
            # Create indexes for admins
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_admins_user ON admins (user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_admins_active ON admins (is_active)")
            
            # ============ NEW: COMMISSION_RECORDS TABLE - COMPLETELY SEPARATE ============
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS commission_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    game_id TEXT NOT NULL,
                    round_number INTEGER NOT NULL,
                    real_players_count INTEGER NOT NULL,
                    commission_amount REAL NOT NULL,
                    recorded_at TIMESTAMP NOT NULL,
                    status TEXT DEFAULT 'recorded',
                    notes TEXT,
                    payable_amount REAL DEFAULT 0.00,
                    commission_paid INTEGER DEFAULT 0,
                    UNIQUE(game_id)
                )
            """)
            
            # Create indexes for commission_records
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_commission_game ON commission_records(game_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_commission_date ON commission_records(recorded_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_commission_status ON commission_records(status)")
            
            logger.info("✅ commission_records table created successfully")
            
            # ============ NEW: FAKE_PLAYERS TABLE FOR ADMIN PANEL BALANCE CALCULATION ============
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS fake_players (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    full_name TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create indexes for fake_players
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_fake_players_user ON fake_players (user_id)")
            
            logger.info("✅ fake_players table created successfully")
            
            # ============ NEW: ADMIN_CREDENTIALS TABLE FOR AUTHENTICATION ============
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS admin_credentials (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    phone TEXT UNIQUE NOT NULL,
                    full_name TEXT,
                    email TEXT,
                    role TEXT DEFAULT 'admin',
                    is_active INTEGER DEFAULT 1,
                    last_login TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create indexes for admin_credentials
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_admin_credentials_username ON admin_credentials (username)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_admin_credentials_phone ON admin_credentials (phone)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_admin_credentials_active ON admin_credentials (is_active)")
            
            # Insert default admin if not exists
            cursor.execute("SELECT COUNT(*) as count FROM admin_credentials")
            result = cursor.fetchone()
            if result and result[0] == 0:
                # Default admin: username: admin, password: admin123
                # In production, change this password immediately
                import hashlib
                default_password_hash = hashlib.sha256("admin123".encode()).hexdigest()
                cursor.execute("""
                    INSERT INTO admin_credentials (username, password_hash, phone, full_name, email, role)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, ('admin', default_password_hash, '+251911223344', 'System Administrator', 'admin@hasetbingo.com', 'super_admin'))
                logger.info("✅ Default admin created (username: admin, password: admin123)")
            
            conn.commit()
            logger.info("All database tables created/verified successfully")
            
        except Exception as e:
            logger.error(f"Error initializing database: {e}")
            if 'conn' in locals():
                conn.rollback()
            raise
    
    @classmethod
    async def init_db(cls):
        """Initialize database (public method for bot.py)"""
        try:
           cls.get_connection()
           # Run migration to fix missing columns
           await cls.fix_missing_created_at_column()
           return True
        except Exception as e:
            logger.error(f"Database initialization failed: {e}")
            return False
    
    @classmethod
    async def migrate_db(cls):
        """Run database migrations"""
        conn = None
        try:
            conn = cls.get_connection()
            cursor = conn.cursor()
            
            # Check if countdown_remaining exists in games
            cursor.execute("PRAGMA table_info(games)")
            columns = [column[1] for column in cursor.fetchall()]
            
            # Add missing columns to games table (without commission fields)
            if 'countdown_remaining' not in columns:
                logger.info("Adding countdown_remaining column to games table...")
                cursor.execute("ALTER TABLE games ADD COLUMN countdown_remaining INTEGER DEFAULT 30")
                conn.commit()
            
            if 'called_numbers' not in columns:
                logger.info("Adding called_numbers column to games table...")
                cursor.execute("ALTER TABLE games ADD COLUMN called_numbers TEXT DEFAULT '[]'")
                conn.commit()
            
            if 'current_phase' not in columns:
                logger.info("Adding current_phase column to games table...")
                cursor.execute("ALTER TABLE games ADD COLUMN current_phase TEXT DEFAULT 'card_purchase'")
                conn.commit()
            
            if 'countdown_end' not in columns:
                logger.info("Adding countdown_end column to games table...")
                cursor.execute("ALTER TABLE games ADD COLUMN countdown_end REAL DEFAULT NULL")
                conn.commit()
            
            if 'winner_display_end' not in columns:
                logger.info("Adding winner_display_end column to games table...")
                cursor.execute("ALTER TABLE games ADD COLUMN winner_display_end TIMESTAMP DEFAULT NULL")
                conn.commit()
            
            if 'real_cards_sold' not in columns:
                logger.info("Adding real_cards_sold column to games table...")
                cursor.execute("ALTER TABLE games ADD COLUMN real_cards_sold INTEGER DEFAULT 0")
                conn.commit()
            
            if 'total_sales' not in columns:
                logger.info("Adding total_sales column to games table...")
                cursor.execute("ALTER TABLE games ADD COLUMN total_sales REAL DEFAULT 0.00")
                conn.commit()
            
            if 'winners_count' not in columns:
                logger.info("Adding winners_count column to games table...")
                cursor.execute("ALTER TABLE games ADD COLUMN winners_count INTEGER DEFAULT 0")
                conn.commit()
            
            
            # Check withdrawal_requests table
            cursor.execute("PRAGMA table_info(withdrawal_requests)")
            withdrawal_columns = [column[1] for column in cursor.fetchall()]
            
            # Add missing columns to withdrawal_requests
            if 'phone_number' not in withdrawal_columns:
                logger.info("Adding phone_number column to withdrawal_requests table...")
                cursor.execute("ALTER TABLE withdrawal_requests ADD COLUMN phone_number TEXT DEFAULT ''")
                conn.commit()
            
            if 'method' not in withdrawal_columns:
                logger.info("Adding method column to withdrawal_requests table...")
                cursor.execute("ALTER TABLE withdrawal_requests ADD COLUMN method TEXT DEFAULT 'tele_birr'")
                conn.commit()
            
            if 'transaction_id' not in withdrawal_columns:
                logger.info("Adding transaction_id column to withdrawal_requests table...")
                cursor.execute("ALTER TABLE withdrawal_requests ADD COLUMN transaction_id INTEGER DEFAULT NULL")
                conn.commit()
            
            if 'requested_at' not in withdrawal_columns:
                logger.info("Adding requested_at column to withdrawal_requests table...")
                cursor.execute("ALTER TABLE withdrawal_requests ADD COLUMN requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
                conn.commit()
            
            # Check telebirr_transactions table for api_response column
            cursor.execute("PRAGMA table_info(telebirr_transactions)")
            telebirr_columns = [column[1] for column in cursor.fetchall()]
            
            # Add api_response column to telebirr_transactions if it doesn't exist
            if 'api_response' not in telebirr_columns:
                logger.info("Adding api_response column to telebirr_transactions table...")
                cursor.execute("ALTER TABLE telebirr_transactions ADD COLUMN api_response TEXT DEFAULT NULL")
                conn.commit()
            
            # Check if weekly_reports table exists
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='weekly_reports'")
            if not cursor.fetchone():
                logger.info("Creating weekly_reports table...")
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS weekly_reports (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        week_number VARCHAR(10) NOT NULL,
                        start_date DATE NOT NULL,
                        end_date DATE NOT NULL,
                        total_games INTEGER DEFAULT 0,
                        total_cards_sold INTEGER DEFAULT 0,
                        total_sales REAL DEFAULT 0.00,
                        commission REAL DEFAULT 0.00,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(week_number)
                    )
                """)
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_weekly_reports_week ON weekly_reports (week_number)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_weekly_reports_start_date ON weekly_reports (start_date)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_weekly_reports_end_date ON weekly_reports (end_date)")
                conn.commit()
            
            # Check and update game_history table for new game manager
            cursor.execute("PRAGMA table_info(game_history)")
            game_history_columns = [column[1] for column in cursor.fetchall()]
            
            # Add missing columns for game_history table
            missing_columns = [
                ('pattern_type', 'TEXT'),
                ('winning_pattern', 'TEXT'),
                ('game_date', 'DATE'),
                ('called_numbers', 'TEXT DEFAULT NULL'),
                ('real_cards_sold', 'INTEGER DEFAULT 0'),
                ('fake_cards_sold', 'INTEGER DEFAULT 0'),
                ('winners_count', 'INTEGER DEFAULT 0'),
                ('winners_data', 'TEXT DEFAULT NULL'),
                ('winner_payouts', 'TEXT DEFAULT NULL'),
                ('is_fake_winner', 'INTEGER DEFAULT 0'),
                ('min_fake_players', 'INTEGER DEFAULT 10'),
                ('max_fake_players', 'INTEGER DEFAULT 40')
            ]
            
            for column_name, column_type in missing_columns:
                if column_name not in game_history_columns:
                    logger.info(f"Adding {column_name} column to game_history table...")
                    cursor.execute(f"ALTER TABLE game_history ADD COLUMN {column_name} {column_type}")
                    conn.commit()
            
            # Add created_by column to house_balance if it doesn't exist
            cursor.execute("PRAGMA table_info(house_balance)")
            house_balance_columns = [column[1] for column in cursor.fetchall()]
            
            if 'created_by' not in house_balance_columns:
                logger.info("Adding created_by column to house_balance table...")
                cursor.execute("ALTER TABLE house_balance ADD COLUMN created_by TEXT DEFAULT 'system'")
                conn.commit()
            
            # Add transaction_type column to house_balance if it doesn't exist
            if 'transaction_type' not in house_balance_columns:
                logger.info("Adding transaction_type column to house_balance table...")
                cursor.execute("ALTER TABLE house_balance ADD COLUMN transaction_type TEXT DEFAULT 'commission'")
                conn.commit()
            
            # Create admins table if it doesn't exist
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='admins'")
            if not cursor.fetchone():
                logger.info("Creating admins table...")
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS admins (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL UNIQUE,
                        username TEXT NOT NULL,
                        full_name TEXT,
                        permissions TEXT DEFAULT 'all',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        is_active INTEGER DEFAULT 1,
                        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
                    )
                """)
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_admins_user ON admins (user_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_admins_active ON admins (is_active)")
                conn.commit()
            
            # ============ CREATE COMMISSION_RECORDS TABLE IF NOT EXISTS ============
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='commission_records'")
            if not cursor.fetchone():
                logger.info("Creating commission_records table...")
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS commission_records (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        game_id TEXT NOT NULL,
                        round_number INTEGER NOT NULL,
                        real_players_count INTEGER NOT NULL,
                        commission_amount REAL NOT NULL,
                        recorded_at TIMESTAMP NOT NULL,
                        status TEXT DEFAULT 'recorded',
                        notes TEXT,
                        payable_amount REAL DEFAULT 0.00,
                        commission_paid INTEGER DEFAULT 0,
                        UNIQUE(game_id)
                    )
                """)
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_commission_game ON commission_records(game_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_commission_date ON commission_records(recorded_at)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_commission_status ON commission_records(status)")
                conn.commit()
                logger.info("✅ commission_records table created successfully")
            
            #adding payable_amount to commission_records
            cursor.execute("PRAGMA table_info(commission_records)")
            commission_records_columns = [column[1] for column in cursor.fetchall()]
            if 'payable_amount' not in commission_records_columns:
                logger.info("Adding transaction_type column to house_balance table...")
                cursor.execute("ALTER TABLE commission_records ADD COLUMN payable_amount REAL DEFAULT 0.00")
                conn.commit()
            if 'commission_paid' not in commission_records_columns:
                logger.info("Adding transaction_type column to house_balance table...")
                cursor.execute("ALTER TABLE commission_records ADD COLUMN commission_paid INTEGER DEFAULT 0")
                conn.commit()
            # ============ CREATE FAKE_PLAYERS TABLE IF NOT EXISTS ============
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='fake_players'")
            if not cursor.fetchone():
                logger.info("Creating fake_players table...")
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS fake_players (
                        user_id INTEGER PRIMARY KEY,
                        username TEXT,
                        full_name TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_fake_players_user ON fake_players (user_id)")
                conn.commit()
                logger.info("✅ fake_players table created successfully")
            
            # ============ CREATE ADMIN_CREDENTIALS TABLE IF NOT EXISTS ============
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='admin_credentials'")
            if not cursor.fetchone():
                logger.info("Creating admin_credentials table...")
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS admin_credentials (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        username TEXT UNIQUE NOT NULL,
                        password_hash TEXT NOT NULL,
                        phone TEXT UNIQUE NOT NULL,
                        full_name TEXT,
                        email TEXT,
                        role TEXT DEFAULT 'admin',
                        is_active INTEGER DEFAULT 1,
                        last_login TIMESTAMP,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_admin_credentials_username ON admin_credentials (username)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_admin_credentials_phone ON admin_credentials (phone)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_admin_credentials_active ON admin_credentials (is_active)")
                
                # Insert default admin if not exists
                cursor.execute("SELECT COUNT(*) as count FROM admin_credentials")
                result = cursor.fetchone()
                if result and result[0] == 0:
                    import hashlib
                    default_password_hash = hashlib.sha256("admin123".encode()).hexdigest()
                    cursor.execute("""
                        INSERT INTO admin_credentials (username, password_hash, phone, full_name, email, role)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, ('admin', default_password_hash, '+251911223344', 'System Administrator', 'admin@hasetbingo.com', 'super_admin'))
                    logger.info("✅ Default admin created in migration")
                
                conn.commit()
                logger.info("✅ admin_credentials table created successfully")
            
            # ============ ADD IS_FAKE COLUMN TO PLAYER_CARDS TABLE ============
            cursor.execute("PRAGMA table_info(player_cards)")
            player_cards_columns = [column[1] for column in cursor.fetchall()]
            
            # Add is_fake column if it doesn't exist
            if 'is_fake' not in player_cards_columns:
                logger.info("Adding is_fake column to player_cards table...")
                cursor.execute("ALTER TABLE player_cards ADD COLUMN is_fake INTEGER DEFAULT 0")
                conn.commit()
                logger.info("✅ is_fake column added to player_cards table")
            
            # Add created_at column if it doesn't exist
            if 'created_at' not in player_cards_columns:
                logger.info("Adding created_at column to player_cards table...")
                cursor.execute("ALTER TABLE player_cards ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
                conn.commit()
                logger.info("✅ created_at column added to player_cards table")
            
            # Add refunded_at column if it doesn't exist
            if 'refunded_at' not in player_cards_columns:
                logger.info("Adding refunded_at column to player_cards table...")
                cursor.execute("ALTER TABLE player_cards ADD COLUMN refunded_at TIMESTAMP DEFAULT NULL")
                conn.commit()
                logger.info("✅ refunded_at column added to player_cards table")
            
            # Add admin panel columns to users table
            await cls.add_admin_panel_columns()
            
            # Add missing payment columns migration
            await cls.add_missing_payment_columns()
            
            logger.info("Database migrations completed successfully")
            
        except Exception as e:
            logger.error(f"Error running migrations: {e}")
            if conn:
                conn.rollback()
    
    @classmethod
    async def add_missing_payment_columns(cls):
        """
        Add missing columns to database tables for payment processing
        Run this migration to fix all schema issues
        """
        try:
            conn = cls.get_connection()
            cursor = conn.cursor()
            
            logger.info("=" * 60)
            logger.info("🔧 RUNNING DATABASE SCHEMA MIGRATION")
            logger.info("=" * 60)
            
            # ============ 1. FIX WITHDRAWAL_REQUESTS TABLE ============
            logger.info("📋 Checking withdrawal_requests table...")
            cursor.execute("PRAGMA table_info(withdrawal_requests)")
            columns = [col[1] for col in cursor.fetchall()]
            
            # Add full_name column if missing
            if 'full_name' not in columns:
                logger.info("  ➕ Adding 'full_name' column to withdrawal_requests...")
                cursor.execute("ALTER TABLE withdrawal_requests ADD COLUMN full_name TEXT DEFAULT NULL")
                conn.commit()
                logger.info("  ✅ full_name column added")
            
            # Add payment_method column (or rename method to payment_method)
            if 'payment_method' not in columns:
                if 'method' in columns:
                    logger.info("  🔄 Copying data from 'method' to 'payment_method'...")
                    # Add payment_method column
                    cursor.execute("ALTER TABLE withdrawal_requests ADD COLUMN payment_method TEXT DEFAULT 'tele_birr'")
                    conn.commit()
                    
                    # Copy data from method to payment_method
                    cursor.execute("UPDATE withdrawal_requests SET payment_method = method WHERE method IS NOT NULL")
                    conn.commit()
                    logger.info("  ✅ payment_method column added and data copied")
                else:
                    logger.info("  ➕ Adding 'payment_method' column to withdrawal_requests...")
                    cursor.execute("ALTER TABLE withdrawal_requests ADD COLUMN payment_method TEXT DEFAULT 'tele_birr'")
                    conn.commit()
                    logger.info("  ✅ payment_method column added")
            
            # ============ 2. FIX TELEBIRR_TRANSACTIONS TABLE ============
            logger.info("📋 Checking telebirr_transactions table...")
            cursor.execute("PRAGMA table_info(telebirr_transactions)")
            columns = [col[1] for col in cursor.fetchall()]
            
            # Add receiver_phone column if missing
            if 'receiver_phone' not in columns:
                logger.info("  ➕ Adding 'receiver_phone' column to telebirr_transactions...")
                cursor.execute("ALTER TABLE telebirr_transactions ADD COLUMN receiver_phone TEXT DEFAULT NULL")
                conn.commit()
                logger.info("  ✅ receiver_phone column added")
            
            # Add receiver_name column if missing
            if 'receiver_name' not in columns:
                logger.info("  ➕ Adding 'receiver_name' column to telebirr_transactions...")
                cursor.execute("ALTER TABLE telebirr_transactions ADD COLUMN receiver_name TEXT DEFAULT NULL")
                conn.commit()
                logger.info("  ✅ receiver_name column added")
            
            # Add payment_method column if missing
            if 'payment_method' not in columns:
                logger.info("  ➕ Adding 'payment_method' column to telebirr_transactions...")
                cursor.execute("ALTER TABLE telebirr_transactions ADD COLUMN payment_method TEXT DEFAULT NULL")
                conn.commit()
                logger.info("  ✅ payment_method column added")
            
            # ============ 3. FIX USERS TABLE ============
            logger.info("📋 Checking users table...")
            cursor.execute("PRAGMA table_info(users)")
            columns = [col[1] for col in cursor.fetchall()]
            
            if 'total_withdrawals' not in columns:
                logger.info("  ➕ Adding 'total_withdrawals' column to users...")
                cursor.execute("ALTER TABLE users ADD COLUMN total_withdrawals REAL DEFAULT 0.00")
                conn.commit()
                logger.info("  ✅ total_withdrawals column added")
            
            if 'total_deposits' not in columns:
                logger.info("  ➕ Adding 'total_deposits' column to users...")
                cursor.execute("ALTER TABLE users ADD COLUMN total_deposits REAL DEFAULT 0.00")
                conn.commit()
                logger.info("  ✅ total_deposits column added")
            if 'used_initial_balance' not in columns:
                logger.info("Adding used_initial_balance column to users table...")
                cursor.execute("ALTER TABLE users ADD COLUMN used_initial_balance INTEGER DEFAULT 0")
                conn.commit()
            
            # ============ 4. CREATE INDEXES FOR BETTER PERFORMANCE ============
            logger.info("📋 Creating indexes for better performance...")
            
            try:
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_withdrawal_requests_user_id ON withdrawal_requests (user_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_withdrawal_requests_status ON withdrawal_requests (status)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_withdrawal_requests_requested_at ON withdrawal_requests (requested_at)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_telebirr_transactions_tx_id ON telebirr_transactions (transaction_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_telebirr_transactions_sms_hash ON telebirr_transactions (sms_hash)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_telebirr_transactions_payment_id ON telebirr_transactions (payment_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_house_balance_type ON house_balance (transaction_type)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_commission_status ON commission_records (status)")
                conn.commit()
                logger.info("  ✅ Indexes created/verified")
            except Exception as e:
                logger.warning(f"  ⚠️ Index creation issue: {e}")
            
            logger.info("=" * 60)
            logger.info("✅ DATABASE SCHEMA MIGRATION COMPLETED SUCCESSFULLY")
            logger.info("=" * 60)
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error adding missing columns: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    @classmethod
    async def add_admin_panel_columns(cls):
        """Add missing columns for admin panel functionality"""
        conn = None
        try:
            conn = cls.get_connection()
            cursor = conn.cursor()
            
            # Check users table for missing columns
            cursor.execute("PRAGMA table_info(users)")
            user_columns = [column[1] for column in cursor.fetchall()]
            
            # Add status column if missing
            if 'status' not in user_columns:
                logger.info("Adding status column to users table...")
                cursor.execute("ALTER TABLE users ADD COLUMN status TEXT DEFAULT 'active'")
                conn.commit()
            
            # Add deleted_at column if missing
            if 'deleted_at' not in user_columns:
                logger.info("Adding deleted_at column to users table...")
                cursor.execute("ALTER TABLE users ADD COLUMN deleted_at TIMESTAMP DEFAULT NULL")
                conn.commit()
            
            # Add updated_at column if missing
            if 'updated_at' not in user_columns:
                logger.info("Adding updated_at column to users table...")
                cursor.execute("ALTER TABLE users ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
                conn.commit()
            
            # Add is_admin column if missing (used in get_admin_by_user_id method)
            if 'is_admin' not in user_columns:
                logger.info("Adding is_admin column to users table...")
                cursor.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0")
                conn.commit()
            
            logger.info("Admin panel database columns added successfully")
            
        except Exception as e:
            logger.error(f"Error adding admin panel columns: {e}")
            if conn:
                conn.rollback()
    
    @classmethod
    @contextmanager
    def get_cursor(cls):
        """Context manager for database cursor"""
        conn = cls.get_connection()
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()
            
            
            
            
    @classmethod
    async def fix_missing_created_at_column(cls):
        """Force add created_at column to player_cards if missing, or make it nullable"""
        try:
            with cls.get_cursor() as cursor:
                # Check if created_at column exists
                cursor.execute("PRAGMA table_info(player_cards)")
                columns = [column[1] for column in cursor.fetchall()]
        
                if 'created_at' not in columns:
                    logger.info("Adding created_at column to player_cards table...")
                    # Add WITHOUT DEFAULT to make it nullable
                    cursor.execute("ALTER TABLE player_cards ADD COLUMN created_at TIMESTAMP")
                    logger.info("✅ created_at column added to player_cards table (nullable)")
                    return True
                else:
                    # Check if the column has a DEFAULT constraint
                    cursor.execute("PRAGMA table_info(player_cards)")
                    for column in cursor.fetchall():
                        if column[1] == 'created_at':
                            # Column already exists, check if it has a default value
                            if column[4] is not None:  # dflt_value column
                                logger.info("✅ created_at column already exists with default value")
                                # Note: SQLite doesn't support modifying column constraints directly
                                # If you need to remove the default, you'd need to recreate the table
                                # For now, we'll leave it as is
                            break
                    logger.info("✅ created_at column already exists in player_cards")
                    return True
        except Exception as e:
            logger.error(f"Error fixing created_at column: {e}")
            return False
    
    # ==================== CRITICAL FIX: PLAYER COUNT METHODS ====================
    
    @classmethod
    async def count_game_players(cls, game_id: str) -> int:
        """
        Count distinct real players in a game - FIXED to count only ACTIVE real cards
        This is the critical fix for the real_players count issue
        """
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    SELECT COUNT(DISTINCT user_id) as count 
                    FROM player_cards 
                    WHERE game_id = ? AND is_active = 1 AND is_fake = 0
                """, (game_id,))
                result = cursor.fetchone()
                if result:
                    return result[0] if result[0] is not None else 0
                return 0
                
        except Exception as e:
            logger.error(f"Error counting game players: {e}")
            return 0
    
    @classmethod
    def _count_game_players(cls, game_id: str) -> int:
        """
        Count distinct real players in a game - FIXED to count only ACTIVE real cards
        This is the critical fix for the real_players count issue
        """
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    SELECT COUNT(DISTINCT user_id) as count 
                    FROM player_cards 
                    WHERE game_id = ? AND is_active = 1 AND is_fake = 0
                """, (game_id,))
                result = cursor.fetchone()
                if result:
                    return result[0] if result[0] is not None else 0
                return 0
                
        except Exception as e:
            logger.error(f"Error counting game players: {e}")
            return 0
    
    @classmethod
    async def count_active_game_players(cls, game_id: str) -> int:
        """Count real active players in a game (alias for count_game_players)"""
        return await cls.count_game_players(game_id)
    
    @classmethod
    async def count_total_active_players(cls, game_id: str) -> int:
        """Count total active players (real + fake) in a game"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    SELECT COUNT(DISTINCT user_id) as count 
                    FROM player_cards 
                    WHERE game_id = ? AND is_active = 1
                """, (game_id,))
                result = cursor.fetchone()
                if result:
                    return result[0] if result[0] is not None else 0
                return 0
        except Exception as e:
            logger.error(f"Error counting total active players: {e}")
            return 0
    
    @classmethod
    async def count_fake_players(cls, game_id: str) -> int:
        """Count fake players in a game"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    SELECT COUNT(DISTINCT user_id) as count 
                    FROM player_cards 
                    WHERE game_id = ? AND is_active = 1 AND is_fake = 1
                """, (game_id,))
                result = cursor.fetchone()
                if result:
                    return result[0] if result[0] is not None else 0
                return 0
        except Exception as e:
            logger.error(f"Error counting fake players: {e}")
            return 0
    
    @classmethod
    async def count_active_real_cards(cls, game_id: str) -> int:
        """Count number of active real cards in a game"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    SELECT COUNT(*) as count 
                    FROM player_cards 
                    WHERE game_id = ? AND is_fake = 0 AND is_active = 1
                """, (game_id,))
                result = cursor.fetchone()
                return result[0] if result and result[0] is not None else 0
        except Exception as e:
            logger.error(f"Error counting active real cards: {e}")
            return 0
    
    @classmethod
    async def count_active_fake_cards(cls, game_id: str) -> int:
        """Count number of active fake cards in a game"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    SELECT COUNT(*) as count 
                    FROM player_cards 
                    WHERE game_id = ? AND is_fake = 1 AND is_active = 1
                """, (game_id,))
                result = cursor.fetchone()
                return result[0] if result and result[0] is not None else 0
        except Exception as e:
            logger.error(f"Error counting active fake cards: {e}")
            return 0
    
    # ==================== CRITICAL FIX: MARK NUMBERS ON CARDS METHODS ====================
    
    @classmethod
    async def mark_number_on_real_cards(cls, game_id: str, number: int) -> int:
        """
        Mark a number on all real player cards in a game
        Returns the number of cards updated
        """
        try:
            with cls.get_cursor() as cursor:
                # Get all real player cards for this game
                cursor.execute("""
                    SELECT id, card_numbers, card_data FROM player_cards 
                    WHERE game_id = ? AND is_active = 1 AND is_fake = 0
                """, (game_id,))
                
                cards = cursor.fetchall()
                updated_count = 0
                
                for card in cards:
                    card_id = card['id']
                    card_numbers_json = card['card_numbers']
                    card_data_json = card['card_data']
                    
                    # Parse card numbers
                    try:
                        card_numbers = json.loads(card_numbers_json) if card_numbers_json else []
                        card_data = json.loads(card_data_json) if card_data_json else {}
                    except:
                        continue
                    
                    # Check if number exists on card
                    if number in card_numbers:
                        # Update marked numbers in card_data
                        if 'marked_numbers' not in card_data:
                            card_data['marked_numbers'] = []
                        
                        if number not in card_data['marked_numbers']:
                            card_data['marked_numbers'].append(number)
                            
                            # Update the card_data in database
                            cursor.execute("""
                                UPDATE player_cards 
                                SET card_data = ? 
                                WHERE id = ?
                            """, (json.dumps(card_data), card_id))
                            
                            updated_count += 1
                
                logger.info(f"✅ Marked number {number} on {updated_count} real cards in game {game_id}")
                return updated_count
                
        except Exception as e:
            logger.error(f"Error marking number on real cards: {e}")
            return 0
    
    @classmethod
    async def mark_number_on_fake_cards(cls, game_id: str, number: int) -> int:
        """
        Mark a number on all fake player cards in a game
        Returns the number of cards updated
        """
        try:
            with cls.get_cursor() as cursor:
                # Get all fake player cards for this game
                cursor.execute("""
                    SELECT id, card_numbers, card_data FROM player_cards 
                    WHERE game_id = ? AND is_active = 1 AND is_fake = 1
                """, (game_id,))
                
                cards = cursor.fetchall()
                updated_count = 0
                
                for card in cards:
                    card_id = card['id']
                    card_numbers_json = card['card_numbers']
                    card_data_json = card['card_data']
                    
                    # Parse card numbers
                    try:
                        card_numbers = json.loads(card_numbers_json) if card_numbers_json else []
                        card_data = json.loads(card_data_json) if card_data_json else {}
                    except:
                        continue
                    
                    # Check if number exists on card
                    if number in card_numbers:
                        # Update marked numbers in card_data
                        if 'marked_numbers' not in card_data:
                            card_data['marked_numbers'] = []
                        
                        if number not in card_data['marked_numbers']:
                            card_data['marked_numbers'].append(number)
                            
                            # Update the card_data in database
                            cursor.execute("""
                                UPDATE player_cards 
                                SET card_data = ? 
                                WHERE id = ?
                            """, (json.dumps(card_data), card_id))
                            
                            updated_count += 1
                
                logger.info(f"✅ Marked number {number} on {updated_count} fake cards in game {game_id}")
                return updated_count
                
        except Exception as e:
            logger.error(f"Error marking number on fake cards: {e}")
            return 0
    
    # ==================== DRAWN NUMBERS METHODS ====================
    
    @classmethod
    def _get_bingo_letter_for_number(cls, number: int) -> str:
        """Get BINGO letter for a number"""
        if not (1 <= number <= 75):
            return 'X'  # Invalid number
        
        letters = ['B', 'I', 'N', 'G', 'O']
        index = min((number - 1) // 15, 4)  # 0-4 for B, I, N, G, O
        return letters[index]
    
    @classmethod
    async def record_drawn_number(cls, game_id: str, number: int, drawn_by: str = 'system') -> bool:
        """
        Record a drawn number for a game.
        """
        try:
            with cls.get_cursor() as cursor:
                # First, add to called_numbers table (with bingo letter)
                letter = cls._get_bingo_letter_for_number(number)
                # cursor.execute("""
                #     INSERT OR IGNORE INTO called_numbers 
                #     (game_id, number, bingo_letter, called_at, called_by)
                #     VALUES (?, ?, ?, ?, ?)
                # """, (game_id, number, letter, datetime.now(), drawn_by))
                
                # # Also add to drawn_numbers table (for backward compatibility)
                # cursor.execute("""
                #     INSERT INTO drawn_numbers (game_id, number, drawn_at)
                #     VALUES (?, ?, ?)
                # """, (game_id, number, datetime.now()))
                
                # Update game's current number and called_numbers array
                # Get current called numbers
                cursor.execute("SELECT called_numbers FROM games WHERE game_id = ?", (game_id,))
                result = cursor.fetchone()
                current_numbers = []
                if result and result[0]:
                    try:
                        current_numbers = json.loads(result[0])
                    except:
                        current_numbers = []
                
                # Add new number if not already present
                if number not in current_numbers:
                    current_numbers.append(number)
                
                # Update game
                cursor.execute("""
                    UPDATE games SET 
                        current_number = ?,
                        called_numbers = ?
                    WHERE game_id = ?
                """, (number, json.dumps(current_numbers), game_id))
                
                logger.info(f"Recorded drawn number {number} for game {game_id} by {drawn_by}")
                return True
                
        except Exception as e:
            logger.error(f"Error recording drawn number {number}: {e}")
            return False
    
    @classmethod
    async def get_drawn_numbers(cls, game_id: str) -> List[int]:
        """Get all drawn numbers for a game"""
        try:
            with cls.get_cursor() as cursor:
                # Try to get from games table first (most efficient)
                cursor.execute("SELECT called_numbers FROM games WHERE game_id = ?", (game_id,))
                result = cursor.fetchone()
                
                if result and result[0]:
                    try:
                        numbers = json.loads(result[0])
                        if numbers and isinstance(numbers, list):
                            return numbers
                        return []
                    except Exception as e:
                        print("error ",e)
                        return []
                
                # Fallback to called_numbers table
                # cursor.execute("""
                #     SELECT number FROM called_numbers 
                #     WHERE game_id = ? 
                #     ORDER BY called_at
                # """, (game_id,))
                # rows = cursor.fetchall()
                
                # if rows:
                #     return [row[0] for row in rows] if rows else []
                
                # # Fallback to drawn_numbers if called_numbers is empty
                # cursor.execute("""
                #     SELECT number FROM drawn_numbers 
                #     WHERE game_id = ? 
                #     ORDER BY drawn_at
                # """, (game_id,))
                # rows = cursor.fetchall()
                # return [row[0] for row in rows] if rows else []
                
        except Exception as e:
            logger.error(f"Error getting drawn numbers: {e}")
            return []
    @classmethod
    def _get_drawn_numbers(cls, game_id: str) -> List[int]:
        """Get all drawn numbers for a game"""
        try:
            with cls.get_cursor() as cursor:
                # Try to get from games table first (most efficient)
                cursor.execute("SELECT called_numbers FROM games WHERE game_id = ?", (game_id,))
                result = cursor.fetchone()
                
                if result and result[0]:
                    try:
                        numbers = json.loads(result[0])
                        if numbers and isinstance(numbers, list):
                            return numbers
                    except:
                        pass
                
                # Fallback to called_numbers table
                cursor.execute("""
                    SELECT number FROM called_numbers 
                    WHERE game_id = ? 
                    ORDER BY called_at
                """, (game_id,))
                rows = cursor.fetchall()
                
                if rows:
                    return [row[0] for row in rows] if rows else []
                
                # Fallback to drawn_numbers if called_numbers is empty
                cursor.execute("""
                    SELECT number FROM drawn_numbers 
                    WHERE game_id = ? 
                    ORDER BY drawn_at
                """, (game_id,))
                rows = cursor.fetchall()
                return [row[0] for row in rows] if rows else []
                
        except Exception as e:
            logger.error(f"Error getting drawn numbers: {e}")
            return []
    
    @classmethod
    async def get_last_number_call_time(cls, game_id: str) -> Optional[datetime]:
        """Get the last time a number was called for a game"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    SELECT MAX(called_at) as last_call 
                    FROM called_numbers 
                    WHERE game_id = ?
                """, (game_id,))
                result = cursor.fetchone()
                
                if result and result[0]:
                    last_call = result[0]
                    # Parse datetime from string if needed
                    if isinstance(last_call, str):
                        try:
                            return datetime.fromisoformat(last_call.replace('Z', '+00:00'))
                        except ValueError:
                            # Try SQLite format
                            try:
                                return datetime.strptime(last_call, '%Y-%m-%d %H:%M:%S')
                            except ValueError:
                                return datetime.now() - timedelta(minutes=5)  # Fallback
                    elif isinstance(last_call, datetime):
                        return last_call
                
                return None
        except Exception as e:
            logger.error(f"Error getting last number call time for game {game_id}: {e}")
            return None
    
    # ==================== CRITICAL FIX: DEACTIVATE CARD METHOD ====================
    
    @classmethod
    async def deactivate_player_card(cls, card_id: int) -> bool:
        """Mark a player card as inactive (refunded)"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    UPDATE player_cards 
                    SET is_active = 0, refunded_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (card_id,))
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error deactivating player card: {e}")
            return False
    
    @classmethod
    async def mark_purchase_refunded_and_inactive(cls, card_id: int) -> bool:
        """Mark a card purchase as refunded and inactive"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    UPDATE player_cards 
                    SET is_active = 0,
                        refunded_at = CURRENT_TIMESTAMP,
                        has_bingo = 0,
                        prize_won = 0,
                        bingo_claimed_at = NULL
                    WHERE id = ?
                """, (card_id,))
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error marking purchase refunded: {e}")
            return False
    
    # ==================== PRIZE POOL METHODS ====================
    
    @classmethod
    async def add_to_prize_pool(cls, game_id: str, amount: float) -> bool:
        """Add amount to prize pool"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    UPDATE games SET prize_pool = prize_pool + ? WHERE game_id = ?
                """, (amount, game_id))
                return cursor.rowcount > 0
                
        except Exception as e:
            logger.error(f"Error adding to prize pool: {e}")
            return False
    
    @classmethod
    async def update_prize_pool(cls, game_id: str, amount: float) -> bool:
        """Update prize pool to specific amount"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    UPDATE games SET prize_pool = ? WHERE game_id = ?
                """, (amount, game_id))
                return cursor.rowcount > 0
                
        except Exception as e:
            logger.error(f"Error updating prize pool: {e}")
            return False
    
    @classmethod
    async def remove_from_prize_pool(cls, game_id: str, amount: float) -> bool:
        """Remove amount from prize pool (for refunds)"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    UPDATE games SET prize_pool = MAX(0, prize_pool - ?) WHERE game_id = ?
                """, (amount, game_id))
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error removing from prize pool: {e}")
            return False
    
    @classmethod
    async def get_game_prize_pool(cls, game_id: str) -> float:
        """Get prize pool for a game"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("SELECT prize_pool FROM games WHERE game_id = ?", (game_id,))
                result = cursor.fetchone()
                if result and len(result) > 0 and result[0] is not None:
                    return float(result[0])
                return 0.00
        except Exception as e:
            logger.error(f"Error getting game prize pool: {e}")
            return 0.00
    
    # ==================== HOUSE BALANCE METHODS ====================
    
    @classmethod
    async def add_to_house_balance(cls, amount: float, description: str = None,
                                   game_id: str = None) -> bool:
        """Add to house balance"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    INSERT INTO house_balance (amount, description, game_id, transaction_type, created_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (amount, description, game_id, 'commission', datetime.now()))
                return True
                
        except Exception as e:
            logger.error(f"Error adding to house balance: {e}")
            return False
    
    @classmethod
    async def get_house_balance(cls) -> float:
        """Get total house balance"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("SELECT COALESCE(SUM(amount), 0) as total FROM house_balance")
                result = cursor.fetchone()
                return float(result[0]) if result and result[0] is not None else 0.00
                
        except Exception as e:
            logger.error(f"Error getting house balance: {e}")
            return 0.00
    
    # ==================== NEW: COMMISSION RECORDS METHODS ====================
    
    @classmethod
    async def record_game_commission(cls, game_id: str, round_number: int, 
                                     real_players_count: int, commission_amount: float,
                                     notes: str = None) -> bool:
        """
        Record commission in dedicated commission_records table.
        This is the source of truth for all commission data.
        """
        try:
            with cls.get_cursor() as cursor:
                # Check if already recorded
                cursor.execute("SELECT COUNT(*) as count FROM commission_records WHERE game_id = ?", (game_id,))
                result = cursor.fetchone()
                if result and result[0] > 0:
                    logger.info(f"Commission already recorded for game {game_id}, skipping")
                    return True
                
                # Insert commission record
                cursor.execute("""
                    INSERT INTO commission_records 
                    (game_id, round_number, real_players_count, commission_amount, recorded_at, status, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    game_id,
                    round_number,
                    real_players_count,
                    commission_amount,
                    datetime.now(),
                    'recorded',
                    notes
                ))
                
                logger.info(f"✅ Commission recorded for game {game_id}: {real_players_count} real players, {commission_amount:.2f} birr")
                return True
                
        except Exception as e:
            logger.error(f"Error recording game commission: {e}")
            return False
    
    @classmethod
    async def get_game_commission(cls, game_id: str) -> Optional[Dict]:
        """Get commission for a specific game from commission_records"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    SELECT * FROM commission_records 
                    WHERE game_id = ?
                """, (game_id,))
                row = cursor.fetchone()
                
                if row:
                    return dict(row)
                return None
        except Exception as e:
            logger.error(f"Error getting game commission: {e}")
            return None
    
    @classmethod
    async def get_total_commission(cls) -> float:
        """Get total commission from commission_records"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("SELECT COALESCE(SUM(commission_amount), 0) as total FROM commission_records")
                row = cursor.fetchone()
                return float(row[0] or 0) if row else 0
        except Exception as e:
            logger.error(f"Error getting total commission: {e}")
            return 0.00
    
    @classmethod
    def _get_weekly_revenue(cls):
        """Get weekly revenue data (sync - runs in thread)"""
        try:
            from datetime import datetime

            with cls.get_cursor() as cursor:
                # Weekly aggregation
                cursor.execute("""
                    SELECT 
                        strftime('%Y-%W', recorded_at),
                        MIN(recorded_at),
                        MAX(recorded_at),
                        COUNT(*),
                        SUM(real_players_count),
                        SUM(commission_amount),
                        SUM(payable_amount)
                    FROM commission_records 
                    GROUP BY strftime('%Y-%W', recorded_at)
                    ORDER BY strftime('%Y-%W', recorded_at) DESC
                    LIMIT 10
                """)
                rows = cursor.fetchall()

                weekly_data = []
                total_commission = 0
                total_payable = 0

                for row in rows:
                    week_data = {
                        'week': row[0],
                        'start_date': row[1],
                        'end_date': row[2],
                        'games_count': row[3] or 0,
                        'total_real_players': row[4] or 0,
                        'commission': float(row[5] or 0),
                        'payable_amount': float(row[6] or 0),
                    }
                    weekly_data.append(week_data)
                    total_commission += week_data['commission']
                    total_payable += week_data['payable_amount']

                # Weekly stats
                this_week_commission = weekly_data[0]['commission'] if weekly_data else 0
                last_week_commission = weekly_data[1]['commission'] if len(weekly_data) > 1 else 0
                this_week_payable = weekly_data[0]['payable_amount'] if weekly_data else 0
                last_week_payable = weekly_data[1]['payable_amount'] if len(weekly_data) > 1 else 0

                # Monthly stats
                current_year_month = datetime.now().strftime('%Y-%m')
                cursor.execute("""
                    SELECT 
                        COALESCE(SUM(commission_amount), 0),
                        COALESCE(SUM(payable_amount), 0)
                    FROM commission_records 
                    WHERE strftime('%Y-%m', recorded_at) = ?
                """, (current_year_month,))
                month_row = cursor.fetchone()

                this_month_commission = float(month_row[0] or 0) if month_row else 0
                this_month_payable = float(month_row[1] or 0) if month_row else 0

                logger.info(f"📊 Weekly revenue computed (threaded)")

                return {
                    'weekly_data': weekly_data,
                    'this_week_commission': this_week_commission,
                    'last_week_commission': last_week_commission,
                    'this_month_commission': this_month_commission,
                    'total_commission': total_commission,
                    'this_week_payable': this_week_payable,
                    'last_week_payable': last_week_payable,
                    'this_month_payable': this_month_payable,
                    'total_payable': total_payable,
                    'house_balance_commission': None
                }

        except Exception as e:
            logger.error(f"DB error (weekly revenue): {e}")
            return {
                'error': str(e),
                'weekly_data': [],
                'this_week_commission': 0,
                'last_week_commission': 0,
                'this_month_commission': 0,
                'total_commission': 0,
                'this_month_payable': 0,
                'total_payable': 0,
                'this_week_payable': 0,
                'last_week_payable': 0,
                'house_balance_commission': None
            }
    @classmethod
    def _get_commission_details(cls, page: int, limit: int):
        """Get commission details (sync - runs in thread)"""
        try:
            offset = (page - 1) * limit

            with cls.get_cursor() as cursor:

                # ================== GAMES ==================
                cursor.execute("""
                    SELECT 
                        cr.game_id,
                        cr.round_number,
                        cr.recorded_at,
                        cr.real_players_count,
                        cr.commission_amount,
                        cr.status,
                        g.total_players,
                        g.prize_pool,
                        g.card_price,
                        (SELECT COUNT(*) FROM player_cards WHERE game_id = cr.game_id AND is_fake = 0 AND is_active = 1),
                        cr.payable_amount
                    FROM commission_records cr
                    LEFT JOIN games g ON cr.game_id = g.game_id
                    ORDER BY cr.recorded_at DESC
                    LIMIT ? OFFSET ?
                """, (limit, offset))

                rows = cursor.fetchall()
                commission_games = []

                for row in rows:
                    commission_games.append({
                        'game_id': row[0],
                        'round_number': row[1] or 1,
                        'game_date': row[2].isoformat() if row[2] else None,
                        'real_players': row[3] or 0,
                        'commission': float(row[4] or 0),
                        'commission_status': row[5] or 'recorded',
                        'total_players': row[6] or 0,
                        'prize_pool': float(row[7] or 0),
                        'card_price': float(row[8] or 10.0),
                        'real_cards_sold': row[9] or 0,
                        'total_sales': (row[9] or 0) * float(row[8] or 10.0),
                        'payable_amount': float(row[10] or 0)
                    })

                # ================== DAILY ==================
                cursor.execute("""
                    SELECT 
                        date(recorded_at),
                        COUNT(*),
                        SUM(real_players_count),
                        SUM(commission_amount),
                        SUM(g.total_cards_sold),
                        SUM(g.total_cards_sold * g.card_price),
                        SUM(payable_amount)
                    FROM commission_records cr
                    LEFT JOIN games g ON cr.game_id = g.game_id
                    GROUP BY date(recorded_at)
                    ORDER BY date(recorded_at) DESC
                    LIMIT 30
                """)

                daily_data = [{
                    'date': row[0],
                    'games_count': row[1] or 0,
                    'real_players': row[2] or 0,
                    'total_commission': float(row[3] or 0),
                    'total_cards_sold': row[4] or 0,
                    'total_sales': float(row[5] or 0),
                    'total_payable':float(row[6] or 0)
                } for row in cursor.fetchall()]

                # ================== MONTHLY ==================
                cursor.execute("""
                    SELECT 
                        strftime('%Y-%m', recorded_at),
                        COUNT(*),
                        SUM(real_players_count),
                        SUM(commission_amount),
                        SUM(g.total_cards_sold),
                        SUM(g.total_cards_sold * g.card_price),
                        SUM(payable_amount)
                    FROM commission_records cr
                    LEFT JOIN games g ON cr.game_id = g.game_id
                    GROUP BY strftime('%Y-%m', recorded_at)
                    ORDER BY strftime('%Y-%m', recorded_at) DESC
                    LIMIT 12
                """)

                monthly_data = [{
                    'month': row[0],
                    'games_count': row[1] or 0,
                    'real_players': row[2] or 0,
                    'total_commission': float(row[3] or 0),
                    'total_cards_sold': row[4] or 0,
                    'total_sales': float(row[5] or 0),
                    'total_payable':float(row[6] or 0)
                } for row in cursor.fetchall()]

                # ================== COUNT ==================
                cursor.execute("SELECT COUNT(*) FROM commission_records")
                total = cursor.fetchone()[0] or 0

                return {
                    "games": commission_games,
                    "daily": daily_data,
                    "monthly": monthly_data,
                    "total": total
                }

        except Exception as e:
            logger.error(f"DB error (commission details): {e}", exc_info=True)
            return {
                "error": str(e),
                "games": [],
                "daily": [],
                "monthly": [],
                "total": 0
            }
    @classmethod
    async def get_this_week_commission(cls) -> float:
        """Get this week's commission from commission_records"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    SELECT COALESCE(SUM(commission_amount), 0) as week_commission
                    FROM 5 
                    WHERE recorded_at >= date('now', '-7 days')
                """)
                row = cursor.fetchone()
                return float(row[0] or 0) if row else 0
        except Exception as e:
            logger.error(f"Error getting this week commission: {e}")
            return 0.00

    @classmethod
    def _get_total_balance(cls):
        """Get total balance of real users (sync - runs in thread)"""
        try:
            with cls.get_cursor() as cursor:
                try:
                    cursor.execute("""
                        SELECT 
                            COALESCE(SUM(balance), 0) as total_balance,
                            COUNT(*) as real_user_count
                        FROM users
                        WHERE user_id > -1
                    """)

                    row = cursor.fetchone()
                    total_balance = float(row[0] or 0) if row else 0
                    real_user_count = row[1] if row else 0

                    cursor.execute("""
                        SELECT 
                            COALESCE(SUM(amount), 0) as total_deposite
                        FROM transactions
                        WHERE transaction_type = 'deposit'
                    """)
                    row = cursor.fetchone()
                    total_deposit = float(row[0] or 0) if row else 0
                    logger.info(f"💰 Total balance (fake_players): {total_balance} birr ({real_user_count} users), total_depositte {total_deposit}")

                except Exception as e:
                    logger.warning(f"Fallback mode: {e}")
                    # Fallback logic
                    total_balance = 0
                    real_user_count = 0
                    logger.info(f"💰 Total balance (fallback): {total_balance} birr ({real_user_count} users)")

                return {
                    "total_balance": total_balance,
                    "real_user_count": real_user_count,
                    "total_deposit":total_deposit
                }

        except Exception as e:
            logger.error(f"DB error: {e}")
            return {
                "total_balance": 0,
                "real_user_count": 0,
                "total_deposit":0,
                "error": str(e)
            }

    # ==================== CARD METHODS ====================
    
    @classmethod
    async def create_player_card(cls, user_id: int, game_id: str, 
                                 card_numbers: List[int], price: float, 
                                 card_index: int, is_active: int = 1,
                                 is_fake: int = 0) -> int:
        """Create a player card"""
        try:
            card_numbers_json = json.dumps(card_numbers)
            card_data = {
                'numbers': card_numbers,
                'grid': [card_numbers[i:i+5] for i in range(0, 25, 5)],
                'purchased_at': datetime.now().isoformat(),
                'marked_numbers': []
            }
            card_data_json = json.dumps(card_data)
            now = datetime.now()
            
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    INSERT INTO player_cards (
                        game_id, user_id, card_index, card_numbers, 
                        card_data, purchase_price, purchase_time, created_at,
                        is_active, is_fake
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    game_id, user_id, card_index, card_numbers_json,
                    card_data_json, price, now, now,
                    is_active, is_fake
                ))
                
                card_id = cursor.lastrowid
                
                # Update game stats
                cursor.execute("""
                    UPDATE games 
                    SET total_cards_sold = total_cards_sold + 1
                    WHERE game_id = ?
                """, (game_id,))
                
                return card_id
                
        except Exception as e:
            logger.error(f"Error creating player card: {e}")
            return 0
    
    @classmethod
    async def get_user_card_in_game(cls, user_id: int, game_id: str) -> Optional[Dict]:
        """Get user's active card in a game"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    SELECT * FROM player_cards 
                    WHERE user_id = ? AND game_id = ? AND is_active = 1
                    LIMIT 1
                """, (user_id, game_id))
                row = cursor.fetchone()
                
                if row:
                    card = dict(row)
                    # Parse JSON data
                    try:
                        card['card_numbers'] = json.loads(card['card_numbers']) if card.get('card_numbers') else []
                        card['card_data'] = json.loads(card['card_data']) if card.get('card_data') else {}
                    except:
                        card['card_numbers'] = []
                        card['card_data'] = {}
                    
                    return card
                return None
                    
        except Exception as e:
            logger.error(f"Error getting user card: {e}")
            return None
    
    @classmethod
    async def get_game_cards(cls, game_id: str) -> List[Dict]:
        """Get all active cards for a game with debugging"""
        try:
            with cls.get_cursor() as cursor:
                # First, check if any records exist at all for this game
                cursor.execute("""
                    SELECT COUNT(*) as total,
                         SUM(CASE WHEN is_active = 1 THEN 1 ELSE 0 END) as active,
                         SUM(CASE WHEN is_fake = 1 AND is_active = 1 THEN 1 ELSE 0 END) as fake_active
                    FROM player_cards 
                    WHERE game_id = ?
                """, (game_id,))
                count_result = cursor.fetchone()
            
                if count_result:
                  total = count_result[0] or 0
                  active = count_result[1] or 0
                  fake_active = count_result[2] or 0
                  real_active = active - fake_active
                
                logger.info(f"📊 Game {game_id} cards: TOTAL={total}, ACTIVE={active} (Real: {real_active}, Fake: {fake_active})")
            
            # Get all active cards with user info
            cursor.execute("""
                SELECT pc.*, u.username, u.full_name 
                FROM player_cards pc
                LEFT JOIN users u ON pc.user_id = u.user_id
                WHERE pc.game_id = ? AND pc.is_active = 1
                ORDER BY pc.card_index
            """, (game_id,))
            rows = cursor.fetchall()
            
            cards = []
            for row in rows:
                card = dict(row)
                try:
                    card['card_numbers'] = json.loads(card['card_numbers']) if card.get('card_numbers') else []
                    card['card_data'] = json.loads(card['card_data']) if card.get('card_data') else {}
                except:
                    card['card_numbers'] = []
                    card['card_data'] = {}
                
                cards.append(card)
            
            logger.info(f"✅ Game {game_id}: Returning {len(cards)} active cards")
            return cards
            
        except Exception as e:
         logger.error(f"❌ Error getting game cards for {game_id}: {e}")
        return []
    
    @classmethod
    async def mark_bingo(cls, card_id: int, prize_won: float) -> bool:
        """Mark card as bingo winner"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    UPDATE player_cards 
                    SET has_bingo = 1, prize_won = ?, bingo_claimed_at = datetime('now')
                    WHERE id = ?
                """, (prize_won, card_id))
                
                # Get game_id and user_id for updating game
                cursor.execute("SELECT game_id, user_id FROM player_cards WHERE id = ?", (card_id,))
                result = cursor.fetchone()
                
                if result and len(result) >= 2:
                    game_id = result[0]
                    user_id = result[1]
                    
                    # Update game with winner info
                    cursor.execute("""
                        UPDATE games 
                        SET winner_id = ?, winner_card_id = ?, winner_payout = ?,
                            status = 'winner_display'
                        WHERE game_id = ?
                    """, (user_id, card_id, prize_won, game_id))
                
                return cursor.rowcount > 0
                
        except Exception as e:
            logger.error(f"Error marking bingo: {e}")
            return False
    
    @classmethod
    async def count_sold_cards(cls, game_id: str) -> int:
        """Count sold cards for a game"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute(
                    "SELECT COUNT(*) as count FROM player_cards WHERE game_id = ? AND is_active = 1",
                    (game_id,)
                )
                result = cursor.fetchone()
                if result and len(result) > 0:
                    return result[0]
                return 0
        except Exception as e:
            logger.error(f"Error counting sold cards: {e}")
            return 0
    @classmethod
    def _count_sold_cards(cls, game_id: str) -> int:
        """Count sold cards for a game"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute(
                    "SELECT COUNT(*) as count FROM player_cards WHERE game_id = ? AND is_active = 1",
                    (game_id,)
                )
                result = cursor.fetchone()
                if result and len(result) > 0:
                    return result[0]
                return 0
        except Exception as e:
            logger.error(f"Error counting sold cards: {e}")
            return 0
    
    @classmethod
    async def can_user_buy_card(cls, game_id: str, user_id: int) -> Dict[str, Any]:
        """Check if user can buy a card in the current game"""
        try:
            with cls.get_cursor() as cursor:
                # Check if game exists and is in card purchase phase
                cursor.execute("""
                    SELECT status, purchase_end_time FROM games 
                    WHERE game_id = ?
                """, (game_id,))
                game_result = cursor.fetchone()
                
                if not game_result:
                    return {'can_buy': False, 'reason': 'Game not found'}
                
                if len(game_result) < 2:
                    return {'can_buy': False, 'reason': 'Invalid game data'}
                
                status = game_result[0]
                purchase_end_time = game_result[1]
                
                if status != 'card_purchase':
                    return {'can_buy': False, 'reason': 'Card purchase period has ended'}
                
                # Check purchase end time
                if purchase_end_time and purchase_end_time < datetime.now():
                    return {'can_buy': False, 'reason': 'Card purchase time expired'}
                
                # Check if user already has a card in this game
                cursor.execute("""
                    SELECT COUNT(*) as count FROM player_cards 
                    WHERE game_id = ? AND user_id = ? AND is_active = 1
                """, (game_id, user_id))
                card_result = cursor.fetchone()
                
                if card_result and card_result[0] > 0:
                    return {'can_buy': False, 'reason': 'Already have a card in this round'}
                
                # Check user balance
                cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
                user_result = cursor.fetchone()
                
                if not user_result:
                    return {'can_buy': False, 'reason': 'User not found'}
                
                balance = user_result[0] if user_result else 0.00
                
                if balance < 10.00:  # Card price
                    return {'can_buy': False, 'reason': 'Insufficient balance'}
                
                return {'can_buy': True, 'reason': ''}
                
        except Exception as e:
            logger.error(f"Error checking can user buy card: {e}")
            return {'can_buy': False, 'reason': 'Server error'}
    
    @classmethod
    async def get_card_owner(cls, game_id: str, card_index: int) -> Optional[int]:
        """Get owner of a card by index"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    SELECT user_id FROM player_cards 
                    WHERE game_id = ? AND card_index = ? AND is_active = 1
                    LIMIT 1
                """, (game_id, card_index))
                result = cursor.fetchone()
                return result[0] if result and len(result) > 0 else None
        except Exception as e:
            logger.error(f"Error getting card owner: {e}")
            return None
    
    @classmethod
    async def get_sold_cards(cls, game_id: str) -> List[Dict]:
        """Get all sold cards for a game"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    SELECT card_index FROM player_cards 
                    WHERE game_id = ? AND is_active = 1
                    ORDER BY card_index
                """, (game_id,))
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting sold cards: {e}")
            return []
    
    @classmethod
    async def get_all_card_purchases_for_game(cls, game_id: str) -> List[Dict]:
        """Get all card purchases for a specific game"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    SELECT pc.*, u.username, u.full_name 
                    FROM player_cards pc
                    LEFT JOIN users u ON pc.user_id = u.user_id
                    WHERE pc.game_id = ? AND pc.is_active = 1
                    ORDER BY pc.purchase_time
                """, (game_id,))
                rows = cursor.fetchall()
                
                purchases = []
                for row in rows:
                    purchase = dict(row)
                    # Convert decimals to float
                    if purchase.get('purchase_price') is not None:
                        purchase['purchase_price'] = float(purchase['purchase_price'])
                    
                    # Parse card numbers if needed
                    if purchase.get('card_numbers'):
                        try:
                            purchase['card_numbers'] = json.loads(purchase['card_numbers'])
                        except:
                            purchase['card_numbers'] = []
                    
                    purchases.append(purchase)
                
                return purchases
        except Exception as e:
            logger.error(f"Error getting all card purchases for game {game_id}: {e}")
            return []
    
    @classmethod
    async def delete_player_card(cls, card_id: int) -> bool:
        """Delete/soft-delete a player card"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("UPDATE player_cards SET is_active = 0 WHERE id = ?", (card_id,))
                return cursor.rowcount > 0
                
        except Exception as e:
            logger.error(f"Error deleting player card: {e}")
            return False
    
    @classmethod
    async def get_next_card_index(cls, game_id: str) -> int:
        """Get next available card index for a game"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    SELECT COALESCE(MAX(card_index), 0) + 1 as next_index 
                    FROM player_cards WHERE game_id = ?
                """, (game_id,))
                result = cursor.fetchone()
                if result and len(result) > 0:
                    return result[0]
                return 1
                
        except Exception as e:
            logger.error(f"Error getting next card index: {e}")
            return 1
    
    @classmethod
    async def get_user_card_by_index(cls, user_id: int, game_id: str, card_index: int) -> Optional[Dict]:
        """Get user's card by index"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    SELECT * FROM player_cards 
                    WHERE user_id = ? AND game_id = ? AND card_index = ? AND is_active = 1
                    LIMIT 1
                """, (user_id, game_id, card_index))
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting user card by index: {e}")
            return None
    
    # ==================== GAME MANAGEMENT METHODS ====================
    
    @classmethod
    async def get_game(cls, game_id: str) -> Optional[Dict]:
        """Get game by ID - FIXED VERSION with timestamp parsing fix"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("SELECT * FROM games WHERE game_id = ?", (game_id,))
                row = cursor.fetchone()
                
                if not row:
                    logger.debug(f"Game {game_id} not found")
                    return None
                
                # Create dictionary from row
                game = dict(row)
                
                # Convert decimals to float for JSON serialization
                for key in ['prize_pool', 'card_price', 'winner_payout']:
                    if game.get(key) is not None:
                        try:
                            game[key] = float(game[key])
                        except (ValueError, TypeError):
                            game[key] = 0.0
                
                # Parse called_numbers JSON
                if game.get('called_numbers'):
                    try:
                        if isinstance(game['called_numbers'], str):
                            game['called_numbers'] = json.loads(game['called_numbers'])
                        else:
                            game['called_numbers'] = list(game['called_numbers'])
                    except Exception:
                        game['called_numbers'] = []
                else:
                    game['called_numbers'] = []
                
                return game
                    
        except Exception as e:
            logger.error(f"Error getting game {game_id}: {e}", exc_info=True)
            return None
        
    @classmethod
    def _get_game(cls, game_id: str) -> Optional[Dict]:
        """Get game by ID - FIXED VERSION with timestamp parsing fix"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("SELECT * FROM games WHERE game_id = ?", (game_id,))
                row = cursor.fetchone()
                
                if not row:
                    logger.debug(f"Game {game_id} not found")
                    return None
                
                # Create dictionary from row
                game = dict(row)
                
                # Convert decimals to float for JSON serialization
                for key in ['prize_pool', 'card_price', 'winner_payout']:
                    if game.get(key) is not None:
                        try:
                            game[key] = float(game[key])
                        except (ValueError, TypeError):
                            game[key] = 0.0
                
                # Parse called_numbers JSON
                if game.get('called_numbers'):
                    try:
                        if isinstance(game['called_numbers'], str):
                            game['called_numbers'] = json.loads(game['called_numbers'])
                        else:
                            game['called_numbers'] = list(game['called_numbers'])
                    except Exception:
                        game['called_numbers'] = []
                else:
                    game['called_numbers'] = []
                
                return game
                    
        except Exception as e:
            logger.error(f"Error getting game {game_id}: {e}", exc_info=True)
            return None
    
    @classmethod
    async def get_active_round_game(cls) -> Optional[Dict]:
        """Get active round-based game (card_purchase or active)"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    SELECT * FROM games 
                    WHERE game_type = 'round_based' 
                    AND status IN ('card_purchase', 'active', 'winner_display')
                    ORDER BY created_at DESC 
                    LIMIT 1
                """)
                row = cursor.fetchone()
                
                if row:
                    game = dict(row)
                    # Convert decimals to float
                    for key in ['prize_pool', 'card_price', 'winner_payout']:
                        if game.get(key) is not None:
                            game[key] = float(game[key])
                    
                    # Parse called_numbers
                    if game.get('called_numbers'):
                        try:
                            game['called_numbers'] = json.loads(game['called_numbers'])
                        except:
                            game['called_numbers'] = []
                    
                    return game
                return None
                    
        except Exception as e:
            logger.error(f"Error getting active round game: {e}")
            return None
    
    @classmethod
    async def get_games_by_status(cls, status: str) -> List[Dict]:
        """
        Get all games with a specific status.
        
        Args:
            status: Game status to filter by (e.g., 'card_purchase', 'active', 'completed')
            
        Returns:
            List of game dictionaries matching the status
        """
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    SELECT * FROM games 
                    WHERE status = ?
                    ORDER BY created_at DESC
                """, (status,))
                rows = cursor.fetchall()
                
                games = []
                for row in rows:
                    game = dict(row)
                    # Convert decimals to float
                    for key in ['prize_pool', 'card_price', 'winner_payout']:
                        if game.get(key) is not None:
                            game[key] = float(game[key])
                    
                    # Parse called_numbers
                    if game.get('called_numbers'):
                        try:
                            game['called_numbers'] = json.loads(game['called_numbers'])
                        except:
                            game['called_numbers'] = []
                    
                    games.append(game)
                
                logger.debug(f"Found {len(games)} games with status '{status}'")
                return games
                
        except Exception as e:
            logger.error(f"Error getting games by status '{status}': {e}")
            return []
    
    @classmethod
    async def get_incomplete_games(cls) -> List[Dict]:
        """
        Get games that are not in completed or archived state.
        Used by game_manager to ensure continuity.
        """
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    SELECT * FROM games 
                    WHERE status NOT IN ('completed', 'archived')
                    AND game_type = 'round_based'
                    ORDER BY created_at DESC
                """)
                rows = cursor.fetchall()
                
                games = []
                for row in rows:
                    game = dict(row)
                    # Convert decimals to float
                    for key in ['prize_pool', 'card_price', 'winner_payout']:
                        if game.get(key) is not None:
                            game[key] = float(game[key])
                    
                    # Parse called_numbers
                    if game.get('called_numbers'):
                        try:
                            game['called_numbers'] = json.loads(game['called_numbers'])
                        except:
                            game['called_numbers'] = []
                    
                    games.append(game)
                
                logger.info(f"Found {len(games)} incomplete round-based games")
                return games
                
        except Exception as e:
            logger.error(f"Error getting incomplete games: {e}")
            return []
    
    @classmethod
    async def get_all_games(cls, limit: int = 100, offset: int = 0) -> List[Dict]:
        """Get all games with pagination"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    SELECT * FROM games 
                    ORDER BY created_at DESC 
                    LIMIT ? OFFSET ?
                """, (limit, offset))
                rows = cursor.fetchall()
                
                games = []
                for row in rows:
                    game = dict(row)
                    # Convert decimals to float
                    for key in ['prize_pool', 'card_price', 'winner_payout']:
                        if game.get(key) is not None:
                            game[key] = float(game[key])
                    
                    # Parse called_numbers
                    if game.get('called_numbers'):
                        try:
                            game['called_numbers'] = json.loads(game['called_numbers'])
                        except:
                            game['called_numbers'] = []
                    games.append(game)
                
                return games
                
        except Exception as e:
            logger.error(f"Error getting all games: {e}")
            return []
    
    @classmethod
    async def get_round_games(cls, limit: int = 10) -> List[Dict]:
        """Get round-based games - FIXED VERSION"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    SELECT * FROM games 
                    WHERE game_type = 'round_based' 
                    ORDER BY created_at DESC 
                    LIMIT ?
                """, (limit,))
                rows = cursor.fetchall()
                
                games = []
                for row in rows:
                    game = dict(row)
                    for key in ['prize_pool', 'card_price', 'winner_payout']:
                        if game.get(key) is not None:
                            game[key] = float(game[key])
                    
                    # Parse called_numbers
                    if game.get('called_numbers'):
                        try:
                            game['called_numbers'] = json.loads(game['called_numbers'])
                        except:
                            game['called_numbers'] = []
                    
                    games.append(game)
                
                return games
                
        except Exception as e:
            logger.error(f"Error getting round games: {e}")
            return []
    
    @classmethod
    async def get_admin_games(cls, limit: int = 20, offset: int = 0) -> List[Dict]:
        """Get admin games with pagination - FIXED VERSION"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                        SELECT 
                            g.*,
                            COALESCE(c.commission_amount, 0) as commission,
                            u.username as winner_username,
                            COUNT(DISTINCT pc.user_id) as unique_players
                        FROM games g
                        LEFT JOIN commission_records c ON g.game_id = c.game_id
                        LEFT JOIN users u ON g.winner_id = u.user_id
                        LEFT JOIN player_cards pc ON g.game_id = pc.game_id AND pc.is_active = 1
                        GROUP BY g.game_id
                        ORDER BY g.created_at DESC
                        LIMIT ? OFFSET ?
                    """, (limit, offset))
                rows = cursor.fetchall()
                
                games = []
                for row in rows:
                    game = dict(row)
                    # Convert decimals to float
                    for key in ['prize_pool', 'card_price', 'winner_payout','total_players']:
                        if game.get(key) is not None:
                            game[key] = float(game[key])
                    
                    # Parse called_numbers
                    if game.get('called_numbers'):
                        try:
                            game['called_numbers'] = json.loads(game['called_numbers'])
                        except:
                            game['called_numbers'] = []
                    
                    games.append(game)
                
                return games
        except Exception as e:
            logger.error(f"Error getting admin games: {e}")
            return []
    
    @classmethod
    def _get_admin_games(cls, limit: int = 20, offset: int = 0) -> List[Dict]:
        """Get admin games with pagination - FIXED VERSION"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    SELECT g.*, 
                           u.username as winner_username,
                           COUNT(DISTINCT pc.user_id) as unique_players
                    FROM games g
                    LEFT JOIN users u ON g.winner_id = u.user_id
                    LEFT JOIN player_cards pc ON g.game_id = pc.game_id AND pc.is_active = 1
                    GROUP BY g.game_id
                    ORDER BY g.created_at DESC
                    LIMIT ? OFFSET ?
                """, (limit, offset))
                rows = cursor.fetchall()
                
                games = []
                for row in rows:
                    game = dict(row)
                    # Convert decimals to float
                    for key in ['prize_pool', 'card_price', 'winner_payout']:
                        if game.get(key) is not None:
                            game[key] = float(game[key])
                    
                    # Parse called_numbers
                    if game.get('called_numbers'):
                        try:
                            game['called_numbers'] = json.loads(game['called_numbers'])
                        except:
                            game['called_numbers'] = []
                    
                    games.append(game)
                
                return games
        except Exception as e:
            logger.error(f"Error getting admin games: {e}")
            return []
    
    @classmethod
    async def create_new_round_game(cls, admin_id: int, round_number: int, 
                                    status: str = 'card_purchase', 
                                    current_phase: str = 'card_purchase',
                                    countdown_end: datetime = None,
                                    purchase_end_time: datetime = None) -> Optional[str]:
        """Create a new round-based game"""
        import uuid
        
        game_id = f"ROUND_{round_number}_{uuid.uuid4().hex[:8].upper()}"
        
        try:
            # Set default values if not provided
            now = datetime.now()
            if countdown_end is None:
                countdown_end = now + timedelta(seconds=30)
            if purchase_end_time is None:
                purchase_end_time = now + timedelta(seconds=30)
            
            with cls.get_cursor() as cursor:
                # Create game with all parameters
                cursor.execute("""
                    INSERT INTO games (
                        game_id, game_type, round_number, status, card_price,
                        purchase_end_time, created_at, countdown_remaining,
                        current_phase, countdown_end, prize_pool,called_numbers
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,?)
                """, (
                    game_id, 'round_based', round_number, status,
                    10.00, purchase_end_time, now, 30,
                    current_phase, countdown_end.timestamp() if countdown_end else None, 0.00,json.dumps([])
                ))
                
                logger.info(f"Created new round game: {game_id} (Round {round_number}) with status: {status}, phase: {current_phase}")
                return game_id
                
        except Exception as e:
            logger.error(f"Error creating new round game: {e}")
            return None
    
    @classmethod
    async def create_continuous_game(cls, admin_id: int) -> Optional[str]:
        """Create a new continuous game"""
        import uuid
        
        game_id = f"CONTINUOUS_{uuid.uuid4().hex[:8].upper()}"
        
        try:
            with cls.get_cursor() as cursor:
                # Create game
                cursor.execute("""
                    INSERT INTO games (
                        game_id, game_type, status, card_price,
                        created_at, countdown_remaining
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    game_id, 'continuous', 'card_purchase',
                    10.00, datetime.now(), 30
                ))
                
                logger.info(f"Created new continuous game: {game_id}")
                return game_id
                
        except Exception as e:
            logger.error(f"Error creating continuous game: {e}")
            return None
    
    @classmethod
    async def create_new_round_from_previous(cls, previous_game_id: str) -> Optional[str]:
        """Create a new round game from a completed game"""
        try:
            # Get previous game info
            previous_game = await cls.get_game(previous_game_id)
            if not previous_game:
                logger.error(f"Previous game {previous_game_id} not found")
                return None
            
            # Get next round number
            latest_round = await cls.get_latest_round_number()
            round_number = latest_round + 1
            
            # Create brand new game ID
            import uuid
            new_game_id = f"ROUND_{round_number}_{uuid.uuid4().hex[:8].upper()}"
            
            # Calculate times
            now = datetime.now()
            purchase_end = now + timedelta(seconds=30)
            
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    INSERT INTO games (
                        game_id, game_type, round_number, status, card_price,
                        purchase_end_time, created_at, countdown_remaining,
                        current_phase, countdown_end, prize_pool
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    new_game_id, 'round_based', round_number, 'card_purchase',
                    10.00, purchase_end.isoformat(), now, 30,
                    'card_purchase', purchase_end.timestamp(), 0.00
                ))
                
                logger.info(f"Created new round game: {new_game_id} from previous game {previous_game_id}")
                return new_game_id
                
        except Exception as e:
            logger.error(f"Error creating new round from previous: {e}")
            return None
    
    @classmethod
    async def register_game(cls, game_id: str, game_type: str = 'round_based', 
                          round_number: int = 1, status: str = 'card_purchase',
                          card_price: float = 10.00, admin_id: int = None) -> bool:
        """
        Register a new game in the database
        
        Args:
            game_id: Unique game identifier
            game_type: Type of game ('round_based', 'continuous')
            round_number: Round number for round-based games
            status: Initial game status
            card_price: Price per bingo card
            admin_id: Admin who created the game
            
        Returns:
            True if successful, False otherwise
        """
        try:
            with cls.get_cursor() as cursor:
                now = datetime.now()
                purchase_end = now + timedelta(seconds=30)
                
                # Insert the game
                cursor.execute("""
                    INSERT INTO games (
                        game_id, game_type, round_number, status, card_price,
                        prize_pool, total_players, total_cards_sold,
                        purchase_end_time, countdown_remaining, current_phase,
                        countdown_end, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    game_id, game_type, round_number, status, card_price,
                    0.00, 0, 0, purchase_end, 30, 'card_purchase',
                    purchase_end.timestamp(), now
                ))
                
                # Record admin transaction if admin_id provided
                if admin_id:
                    cursor.execute("""
                        INSERT INTO admin_transactions (
                            admin_id, action, target_type, target_id, details, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        str(admin_id), 'create_game', 'game', game_id,
                        json.dumps({
                            'game_type': game_type,
                            'round_number': round_number,
                            'status': status,
                            'card_price': card_price
                        }), now
                    ))
                
                logger.info(f"Registered new game: {game_id} (Type: {game_type}, Round: {round_number})")
                return True
                
        except Exception as e:
            logger.error(f"Error registering game {game_id}: {e}")
            return False
    
    @classmethod
    async def add_game_to_database(cls, game_data: Dict) -> Optional[str]:
        """
        Add a game to the database from game data
        
        Args:
            game_data: Dictionary containing game information
            
        Returns:
            Game ID if successful, None otherwise
        """
        try:
            import uuid
            
            # Generate a unique game ID
            game_id = game_data.get('game_id')
            if not game_id:
                round_num = game_data.get('round_number', 1)
                game_id = f"ROUND_{round_num}_{uuid.uuid4().hex[:8].upper()}"
            
            with cls.get_cursor() as cursor:
                now = datetime.now()
                purchase_end = now + timedelta(seconds=30)
                
                # Extract game data with defaults
                game_type = game_data.get('game_type', 'round_based')
                round_number = game_data.get('round_number', 1)
                status = game_data.get('status', 'card_purchase')
                card_price = game_data.get('card_price', 10.00)
                prize_pool = game_data.get('prize_pool', 0.00)
                
                # Insert the game
                cursor.execute("""
                    INSERT OR REPLACE INTO games (
                        game_id, game_type, round_number, status, card_price,
                        prize_pool, total_players, total_cards_sold,
                        current_number, winner_id, winner_card_id,
                        winner_payout, started_at,
                        completed_at, purchase_end_time, countdown_remaining,
                        called_numbers, current_phase, countdown_end,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    game_id, game_type, round_number, status, card_price,
                    prize_pool, game_data.get('total_players', 0),
                    game_data.get('total_cards_sold', 0),
                    game_data.get('current_number'),
                    game_data.get('winner_id'),
                    game_data.get('winner_card_id'),
                    game_data.get('winner_payout', 0.00),
                    game_data.get('started_at'),
                    game_data.get('completed_at'),
                    purchase_end,
                    game_data.get('countdown_remaining', 30),
                    json.dumps(game_data.get('called_numbers', [])),
                    game_data.get('current_phase', 'card_purchase'),
                    purchase_end.timestamp(),
                    now
                ))
                
                logger.info(f"Added game to database: {game_id}")
                return game_id
                
        except Exception as e:
            logger.error(f"Error adding game to database: {e}")
            return None
    
    @classmethod
    async def get_or_create_active_game(cls, admin_id: int = None) -> Optional[Dict]:
        """
        Get active game or create a new one if none exists
        
        Args:
            admin_id: Admin ID for creating a new game
            
        Returns:
            Active game dictionary or None
        """
        try:
            # First, try to get existing active game
            active_game = await cls.get_active_round_game()
            
            if active_game:
                logger.info(f"Found existing active game: {active_game.get('game_id')}")
                return active_game
            
            # No active game found, create a new one
            latest_round = await cls.get_latest_round_number()
            round_number = latest_round + 1
            
            game_id = await cls.create_new_round_game(
                admin_id=admin_id or 0,
                round_number=round_number,
                status='card_purchase',
                current_phase='card_purchase'
            )
            
            if game_id:
                return await cls.get_game(game_id)
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting or creating active game: {e}")
            return None
    
    @classmethod
    async def update_game_status(cls, game_id: str, status: str) -> bool:
        """Update game status"""
        try:
            with cls.get_cursor() as cursor:
                now = datetime.now()
                if status == 'active':
                    cursor.execute("""
                        UPDATE games 
                        SET status = ?, started_at = ?, countdown_remaining = NULL
                        WHERE game_id = ?
                    """, (status, now, game_id))
                elif status == 'completed':
                    cursor.execute("""
                        UPDATE games 
                        SET status = ?, completed_at = ?, countdown_remaining = NULL
                        WHERE game_id = ?
                    """, (status, now, game_id))
                elif status == 'card_purchase':
                    cursor.execute("""
                        UPDATE games 
                        SET status = ?, purchase_end_time = ?, countdown_remaining = 30,
                            countdown_end = ?, current_phase = 'card_purchase'
                        WHERE game_id = ?
                    """, (status, now + timedelta(seconds=30), 
                          (now + timedelta(seconds=30)).timestamp(), game_id))
                elif status == 'winner_display':
                    cursor.execute("""
                        UPDATE games 
                        SET status = ?, countdown_remaining = 10
                        WHERE game_id = ?
                    """, (status, game_id))
                else:
                    cursor.execute("""
                        UPDATE games SET status = ? WHERE game_id = ?
                    """, (status, game_id))
                
                return cursor.rowcount > 0
                
        except Exception as e:
            logger.error(f"Error updating game status: {e}")
            return False
    
    @classmethod
    async def update_game_phase(cls, game_id: str, phase: str) -> bool:
        """Update the current phase for a game"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    UPDATE games 
                    SET current_phase = ? 
                    WHERE game_id = ?
                """, (phase, game_id))
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error updating game phase: {e}")
            return False
    
    @classmethod
    async def update_game_start_time(cls, game_id: str) -> bool:
        """Update game start time"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    UPDATE games 
                    SET started_at = datetime('now') 
                    WHERE game_id = ? AND started_at IS NULL
                """, (game_id,))
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error updating game start time: {e}")
            return False
    
    @classmethod
    async def update_game_winner(cls, game_id: str, user_id: int, prize_pool: float) -> bool:
        """Update game with winner information - FIXED VERSION"""
        try:
            with cls.get_cursor() as cursor:
                # Winner gets prize pool
                winner_payout = prize_pool
                
                # Update game with winner info
                cursor.execute("""
                    UPDATE games 
                    SET winner_id = ?, 
                        winner_payout = ?,
                        status = 'winner_display'
                    WHERE game_id = ?
                """, (user_id, winner_payout, game_id))
                
                logger.info(f"Updated game {game_id} winner: user {user_id} wins {winner_payout:.2f}")
                return True
                
        except Exception as e:
            logger.error(f"Error updating game winner: {e}")
            return False
    
    @classmethod
    async def update_current_number(cls, game_id: str, number: Optional[int]) -> bool:
        """Update current called number"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    UPDATE games SET current_number = ? WHERE game_id = ?
                """, (number, game_id))
                return cursor.rowcount > 0
                
        except Exception as e:
            logger.error(f"Error updating current number: {e}")
            return False
    
    @classmethod
    async def set_purchase_end_time(cls, game_id: str, end_time: datetime) -> bool:
        """Set card purchase end time"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    UPDATE games SET purchase_end_time = ? WHERE game_id = ?
                """, (end_time, game_id))
                return cursor.rowcount > 0
                
        except Exception as e:
            logger.error(f"Error setting purchase end time: {e}")
            return False
    
    @classmethod
    async def set_winner_display_end(cls, game_id: str, winner_display_end: datetime) -> bool:
        """Set winner display end time"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    UPDATE games 
                    SET winner_display_end = ? 
                    WHERE game_id = ?
                """, (winner_display_end, game_id))
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error setting winner display end: {e}")
            return False
    
    @classmethod
    async def update_game_countdown(cls, game_id: str, countdown: int) -> bool:
        """Update countdown for a game"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    UPDATE games SET countdown_remaining = ? WHERE game_id = ?
                """, (countdown, game_id))
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error updating countdown: {e}")
            return False
    @classmethod
    async def get_game_countdown(cls, game_id: str) -> int | None:
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    SELECT countdown_remaining FROM games WHERE game_id = ?
                """, (game_id,))
                
                row = cursor.fetchone()
                
                if row is None:
                    return None
                
                return int(row[0])  # extract the integer
        except Exception as e:
            print(f"Error: {e}")
            return None
    
    @classmethod
    async def update_game_countdown_end(cls, game_id: str, countdown_end: float) -> bool:
        """Update the countdown end time for a game"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    UPDATE games 
                    SET countdown_end = ? 
                    WHERE game_id = ?
                """, (countdown_end, game_id))
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error updating game countdown end: {e}")
            return False
    
    @classmethod
    async def calculate_purchase_countdown(cls, game_id: str) -> int:
        """Calculate remaining purchase countdown"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    SELECT purchase_end_time FROM games WHERE game_id = ?
                """, (game_id,))
                result = cursor.fetchone()
                
                if result and result[0]:
                    purchase_end = datetime.fromisoformat(result[0]) if isinstance(result[0], str) else result[0]
                    now = datetime.now()
                    remaining = (purchase_end - now).total_seconds()
                    return max(0, int(remaining))
                
                return 30  # Default
                
        except Exception as e:
            logger.error(f"Error calculating countdown: {e}")
            return 30
    
    @classmethod
    async def calculate_winner_display_countdown(cls, game_id: str) -> int:
        """Calculate remaining winner display countdown"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    SELECT completed_at FROM games WHERE game_id = ?
                """, (game_id,))
                result = cursor.fetchone()
                
                if result and result[0]:
                    completed_at = datetime.fromisoformat(result[0]) if isinstance(result[0], str) else result[0]
                    now = datetime.now()
                    elapsed = (now - completed_at).total_seconds()
                    remaining = max(0, 5 - int(elapsed))
                    return remaining
                
                return 5  # Default
                
        except Exception as e:
            logger.error(f"Error calculating winner display countdown: {e}")
            return 5
    
    @classmethod
    async def get_game_countdown(cls, game_id: str) -> int:
        """Get countdown for a game"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    SELECT countdown_remaining FROM games WHERE game_id = ?
                """, (game_id,))
                result = cursor.fetchone()
                if result and len(result) > 0 and result[0] is not None:
                    return result[0]
                return 30
        except Exception as e:
            logger.error(f"Error getting countdown: {e}")
            return 30
    
    @classmethod
    async def get_latest_round_number(cls) -> int:
        """Get latest round number"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    SELECT COALESCE(MAX(round_number), 0) as latest_round 
                    FROM games 
                    WHERE game_type = 'round_based'
                """)
                result = cursor.fetchone()
                if result and len(result) > 0:
                    return result[0]
                return 0
                
        except Exception as e:
            logger.error(f"Error getting latest round number: {e}")
            return 0
    
    @classmethod
    async def delete_game(cls, game_id: str) -> bool:
        """Delete a game and all related data"""
        try:
            with cls.get_cursor() as cursor:
                # Delete related records first
                cursor.execute("DELETE FROM called_numbers WHERE game_id = ?", (game_id,))
                cursor.execute("DELETE FROM drawn_numbers WHERE game_id = ?", (game_id,))
                cursor.execute("DELETE FROM bingo_claims WHERE game_id = ?", (game_id,))
                cursor.execute("DELETE FROM player_cards WHERE game_id = ?", (game_id,))
                cursor.execute("DELETE FROM game_history WHERE game_id = ?", (game_id,))
                cursor.execute("DELETE FROM commission_records WHERE game_id = ?", (game_id,))
                
                # Delete the game
                cursor.execute("DELETE FROM games WHERE game_id = ?", (game_id,))
                
                logger.info(f"Deleted game {game_id} and all related data")
                return True
                
        except Exception as e:
            logger.error(f"Error deleting game {game_id}: {e}")
            return False
    
    @classmethod
    async def reset_game_for_next_round(cls, game_id: str) -> bool:
        """Reset game for next round - SUPER SAFE VERSION WITH TIMESTAMP FIX"""
        try:
            with cls.get_cursor() as cursor:
                # FIRST: Check if game exists and get current data
                cursor.execute("SELECT * FROM games WHERE game_id = ?", (game_id,))
                game_data = cursor.fetchone()
                
                if not game_data:
                    logger.error(f"Cannot reset non-existent game: {game_id}")
                    return False
                
                logger.debug(f"Resetting game {game_id}: current data = {dict(game_data) if game_data else 'None'}")
                
                # SECOND: Archive current cards (mark as inactive)
                cursor.execute("""
                    UPDATE player_cards SET is_active = 0 WHERE game_id = ?
                """, (game_id,))
                
                # THIRD: Clear called numbers
                cursor.execute("DELETE FROM called_numbers WHERE game_id = ?", (game_id,))
                cursor.execute("DELETE FROM drawn_numbers WHERE game_id = ?", (game_id,))
                
                # FOURTH: Calculate new times using Python datetime
                now = datetime.now()
                purchase_end = now + timedelta(seconds=30)
                
                # FIFTH: Reset game stats - CRITICAL: KEEP SAME game_id AND ALL COLUMNS
                cursor.execute("""
                    UPDATE games 
                    SET current_number = NULL, 
                        called_numbers = '[]',
                        total_players = 0,
                        total_cards_sold = 0,
                        winner_id = NULL,
                        winner_card_id = NULL,
                        winner_payout = 0.00,
                        prize_pool = 0.00,
                        status = 'card_purchase',
                        purchase_end_time = ?,
                        countdown_remaining = 30,
                        current_phase = 'card_purchase',
                        countdown_end = ?,
                        started_at = NULL,
                        completed_at = NULL,
                        winner_display_end = NULL,
                        real_cards_sold = 0,
                        total_sales = 0.00,
                        winners_count = 0
                    WHERE game_id = ?
                """, (
                    purchase_end.isoformat() if purchase_end else None, 
                    purchase_end.timestamp() if purchase_end else None, 
                    game_id
                ))
                
                # SIXTH: Verify the update worked
                cursor.execute("SELECT status, current_phase, round_number FROM games WHERE game_id = ?", (game_id,))
                verify_result = cursor.fetchone()
                
                if verify_result:
                    logger.info(f"Game {game_id} reset successfully. Status: {verify_result[0]}, Phase: {verify_result[1]}, Round: {verify_result[2]}")
                    return True
                else:
                    logger.error(f"Game {game_id} disappeared after reset!")
                    return False
                
        except Exception as e:
            logger.error(f"Error resetting game {game_id}: {e}", exc_info=True)
            return False
    
    @classmethod
    async def force_reset_stuck_game(cls, game_id: str) -> bool:
        """Force reset a stuck game back to card purchase phase"""
        try:
            with cls.get_cursor() as cursor:
                # Get current game state
                cursor.execute("SELECT status, current_phase FROM games WHERE game_id = ?", (game_id,))
                result = cursor.fetchone()
                
                if not result:
                    return False
                
                # Reset to fresh state
                now = datetime.now()
                purchase_end = now + timedelta(seconds=30)
                
                cursor.execute("""
                    UPDATE games 
                    SET status = 'card_purchase',
                        current_phase = 'card_purchase',
                        purchase_end_time = ?,
                        countdown_remaining = 30,
                        countdown_end = ?,
                        started_at = NULL,
                        completed_at = NULL,
                        winner_display_end = NULL,
                        current_number = NULL,
                        called_numbers = '[]',
                        winner_id = NULL,
                        winner_card_id = NULL,
                        winner_payout = 0.00,
                        prize_pool = 0.00,
                        real_cards_sold = 0,
                        total_sales = 0.00,
                        winners_count = 0
                    WHERE game_id = ?
                """, (
                    purchase_end.isoformat(),
                    purchase_end.timestamp(),
                    game_id
                ))
                
                # Archive any existing cards
                cursor.execute("UPDATE player_cards SET is_active = 0 WHERE game_id = ?", (game_id,))
                
                logger.info(f"Force reset stuck game {game_id} to fresh card purchase phase")
                return True
                
        except Exception as e:
            logger.error(f"Error force resetting stuck game: {e}")
            return False
    
    @classmethod
    async def get_game_statistics(cls, game_id: str) -> Dict:
        """Get comprehensive statistics for a game"""
        try:
            with cls.get_cursor() as cursor:
                stats = {}
                
                # Get basic game info
                game = await cls.get_game(game_id)
                if not game:
                    return {}
                
                stats['game'] = game
                
                # Get card statistics
                cursor.execute("""
                    SELECT 
                        COUNT(*) as total_cards,
                        COUNT(DISTINCT user_id) as unique_players,
                        COUNT(CASE WHEN has_bingo = 1 THEN 1 END) as bingo_count,
                        COALESCE(SUM(prize_won), 0) as total_prizes_paid
                    FROM player_cards 
                    WHERE game_id = ? AND is_active = 1
                """, (game_id,))
                card_stats = cursor.fetchone()
                if card_stats and len(card_stats) >= 4:
                    stats['cards'] = {
                        'total': card_stats[0],
                        'unique_players': card_stats[1],
                        'bingo_count': card_stats[2],
                        'total_prizes_paid': float(card_stats[3]) if card_stats[3] else 0.00
                    }
                
                # Get called numbers count
                cursor.execute("SELECT COUNT(*) as count FROM called_numbers WHERE game_id = ?", (game_id,))
                called_result = cursor.fetchone()
                stats['numbers_called'] = called_result[0] if called_result and called_result[0] else 0
                
                # Get purchase timeline
                cursor.execute("""
                    SELECT 
                        COUNT(*) as purchases_per_minute,
                        strftime('%Y-%m-%d %H:%M:00', purchase_time) as minute_bucket
                    FROM player_cards 
                    WHERE game_id = ? AND is_active = 1
                    GROUP BY minute_bucket
                    ORDER BY minute_bucket
                """, (game_id,))
                timeline_rows = cursor.fetchall()
                stats['purchase_timeline'] = [dict(row) for row in timeline_rows]
                
                return stats
                
        except Exception as e:
            logger.error(f"Error getting game statistics: {e}")
            return {}
    
    # ==================== USER MANAGEMENT METHODS ====================
    
    @classmethod
    async def create_user(cls, user_id: int, username: str = None, full_name: str = None) -> bool:
        """Create a new user"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    INSERT OR REPLACE INTO users (
                        user_id, username, full_name, balance, status, 
                        last_active, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'), datetime('now'))
                """, (user_id, username or f"User_{user_id}", full_name or f"User {user_id}", 5.00, 'active'))
                
                # Log the initial balance transaction
                cursor.execute("""
                    INSERT INTO transactions (
                        user_id, amount, balance_after, transaction_type, description, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    user_id, 5.00, 5.00, 'initial_deposit', 
                    'Initial signup bonus', datetime.now()
                ))
                
                logger.info(f"Created new user {user_id} with initial balance 10.00")
                return True
                
        except Exception as e:
            logger.error(f"Error creating user: {e}")
            return False
    
    @classmethod
    async def get_user(cls, user_id: int) -> Optional[Dict]:
        """Get user by ID - simple version for basic operations"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    SELECT user_id, username, full_name, balance, 
                           total_wins, total_games_played, total_winnings,
                           status, is_admin, created_at, updated_at, last_active,
                           total_withdrawals, total_deposits
                    FROM users 
                    WHERE user_id = ? AND deleted_at IS NULL
                """, (user_id,))
                
                row = cursor.fetchone()
                if not row:
                    logger.debug(f"User {user_id} not found")
                    return None
                
                user = dict(row)
                
                # Convert decimal values to float
                for key in ['balance', 'total_winnings', 'total_withdrawals', 'total_deposits']:
                    if user.get(key) is not None:
                        try:
                            user[key] = float(user[key])
                        except (ValueError, TypeError):
                            user[key] = 0.0
                
                return user
                
        except Exception as e:
            logger.error(f"Error getting user {user_id}: {e}")
            return None
    @classmethod
    async def add_used_initial_balance_column(cls):
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("PRAGMA table_info(users)")
                columns = [col[1] for col in cursor.fetchall()]

                if "used_initial_balance" not in columns:
                    cursor.execute("""
                        ALTER TABLE users 
                        ADD COLUMN used_initial_balance INTEGER DEFAULT 0
                    """)
        except Exception as e:
            logger.error(f"Error adding initial balance column: {e}")
            return None
    @classmethod
    async def get_user_with_details(cls, user_id: int) -> Optional[Dict]:
        """Get detailed user information including all columns"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    SELECT 
                        u.*,
                        COUNT(DISTINCT pc.id) as total_cards_purchased,
                        COUNT(DISTINCT CASE WHEN pc.has_bingo = 1 THEN pc.id END) as total_bingos,
                        COALESCE(SUM(pc.prize_won), 0) as total_winnings,
                        COUNT(DISTINCT t.id) as total_transactions,
                        COALESCE(SUM(CASE WHEN t.amount > 0 THEN t.amount ELSE 0 END), 0) as total_deposits,
                        COALESCE(SUM(CASE WHEN t.amount < 0 THEN ABS(t.amount) ELSE 0 END), 0) as total_withdrawals,
                        MAX(t.created_at) as last_transaction_date
                    FROM users u
                    LEFT JOIN player_cards pc ON u.user_id = pc.user_id AND pc.is_active = 1
                    LEFT JOIN transactions t ON u.user_id = t.user_id
                    WHERE u.user_id = ? AND u.deleted_at IS NULL
                    GROUP BY u.user_id
                """, (user_id,))
                
                row = cursor.fetchone()
                if row:
                    user = dict(row)
                    # Convert decimals to float
                    for key in ['balance', 'total_winnings', 'total_winnings_amount', 
                              'total_deposits', 'total_withdrawals', 'total_winnings']:
                        if user.get(key) is not None:
                            try:
                                user[key] = float(user[key])
                            except (ValueError, TypeError):
                                user[key] = 0.0
                    return user
                return None
        except Exception as e:
            logger.error(f"Error getting user with details: {e}")
            return None
        
    @classmethod
    def _get_user_details(cls, user_id: int):
        """Get detailed user info (sync - runs in thread)"""
        try:
            with cls.get_cursor() as cursor:

                # Main user query
                cursor.execute("""
                                SELECT 
                                    u.*,

                                    -- Games played
                                    (
                                        SELECT COUNT(DISTINCT game_id)
                                        FROM player_cards
                                        WHERE user_id = u.user_id
                                    ) as total_games_played,

                                    -- Cards purchased
                                    (
                                        SELECT COUNT(*)
                                        FROM player_cards
                                        WHERE user_id = u.user_id
                                    ) as total_cards_purchased,

                                    -- Total wins
                                    (
                                        SELECT COUNT(*)
                                        FROM transactions
                                        WHERE user_id = u.user_id
                                        AND transaction_type = 'winning'
                                    ) as total_wins,

                                    -- Total winnings
                                    (
                                        SELECT COALESCE(SUM(amount), 0)
                                        FROM transactions
                                        WHERE user_id = u.user_id
                                        AND transaction_type = 'winning'
                                    ) as total_winnings

                                FROM users u
                                WHERE u.user_id = ?
                            """, (user_id,))

                row = cursor.fetchone()
                if not row:
                    return None

                user_data = dict(row)
                user_data['balance'] = float(user_data.get('balance', 0))
                user_data['total_winnings'] = float(user_data.get('total_winnings', 0))

                # Transactions
                cursor.execute("""
                    SELECT * FROM transactions 
                    WHERE user_id = ? 
                    ORDER BY created_at DESC 
                    LIMIT 10
                """, (user_id,))
                transactions = [
                    {**dict(r), 'amount': float(r['amount'])}
                    for r in cursor.fetchall()
                ]

                # Payments
                cursor.execute("""
                    SELECT * FROM payments 
                    WHERE user_id = ? 
                    ORDER BY created_at DESC 
                    LIMIT 10
                """, (user_id,))
                payments = [
                    {**dict(r), 'amount': float(r['amount'])}
                    for r in cursor.fetchall()
                ]

                # Withdrawals
                cursor.execute("""
                    SELECT * FROM withdrawal_requests 
                    WHERE user_id = ? 
                    ORDER BY requested_at DESC 
                    LIMIT 10
                """, (user_id,))
                withdrawals = [
                    {**dict(r), 'amount': float(r['amount'])}
                    for r in cursor.fetchall()
                ]

                user_data['recent_transactions'] = transactions
                user_data['payment_history'] = payments
                user_data['withdrawal_history'] = withdrawals

                return user_data

        except Exception as e:
            logger.error(f"DB error (user details): {e}")
            return {"error": str(e)}
        
    @classmethod
    async def get_user_with_balance(cls, user_id: int) -> Optional[Dict]:
        """Get user with balance"""
        return await cls.get_user(user_id)
    
    @classmethod
    async def update_user_balance(cls, user_id: int, amount: float) -> bool:
        """Update user balance"""
        try:
            with cls.get_cursor() as cursor:
                if amount >= 0:
                    cursor.execute("""
                        UPDATE users SET balance = balance + ? WHERE user_id = ?
                    """, (amount, user_id))
                else:
                    # Ensure balance doesn't go negative
                    cursor.execute("""
                        UPDATE users 
                        SET balance = MAX(0, balance + ?) 
                        WHERE user_id = ?
                    """, (amount, user_id))
                
                return cursor.rowcount > 0
                
        except Exception as e:
            logger.error(f"Error updating user balance: {e}")
            return False
    
    @classmethod
    async def get_game_players(cls, game_id: str) -> List[Dict]:
        """Get all players in a game"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    SELECT DISTINCT u.user_id, u.username, u.full_name, u.balance,
                           pc.card_index, pc.purchase_time, pc.is_fake
                    FROM users u
                    INNER JOIN player_cards pc ON u.user_id = pc.user_id
                    WHERE pc.game_id = ? AND pc.is_active = 1
                    ORDER BY pc.purchase_time
                """, (game_id,))
                rows = cursor.fetchall()
                
                players = []
                for row in rows:
                    player = dict(row)
                    if player.get('balance') is not None:
                        player['balance'] = float(player['balance'])
                    players.append(player)
                
                return players
                
        except Exception as e:
            logger.error(f"Error getting game players: {e}")
            return []
    
    @classmethod
    async def suspend_user(cls, user_id: int, admin_id: int, reason: str = None) -> bool:
        """Suspend a user"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    UPDATE users 
                    SET status = 'suspended', updated_at = datetime('now')
                    WHERE user_id = ?
                """, (user_id,))
                
                if cursor.rowcount > 0:
                    # Record admin transaction
                    await cls.record_admin_transaction(
                        admin_id=str(admin_id),
                        action='suspend_user',
                        target_type='user',
                        target_id=str(user_id),
                        details={'reason': reason}
                    )
                    return True
                return False
        except Exception as e:
            logger.error(f"Error suspending user: {e}")
            return False

    @classmethod
    async def unsuspend_user(cls, user_id: int, admin_id: int) -> bool:
        """Unsuspend a user"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    UPDATE users 
                    SET status = 'active', updated_at = datetime('now')
                    WHERE user_id = ?
                """, (user_id,))
                
                if cursor.rowcount > 0:
                    # Record admin transaction
                    await cls.record_admin_transaction(
                        admin_id=str(admin_id),
                        action='unsuspend_user',
                        target_type='user',
                        target_id=str(user_id),
                        details={}
                    )
                    return True
                return False
        except Exception as e:
            logger.error(f"Error unsuspending user: {e}")
            return False

    @classmethod
    async def delete_user(cls, user_id: int, admin_id: int, reason: str = None) -> bool:
        """Soft delete a user"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    UPDATE users 
                    SET deleted_at = datetime('now'), 
                        status = 'deleted',
                        updated_at = datetime('now')
                    WHERE user_id = ?
                """, (user_id,))
                
                if cursor.rowcount > 0:
                    # Record admin transaction
                    await cls.record_admin_transaction(
                        admin_id=str(admin_id),
                        action='delete_user',
                        target_type='user',
                        target_id=str(user_id),
                        details={'reason': reason}
                    )
                    return True
                return False
        except Exception as e:
            logger.error(f"Error deleting user: {e}")
            return False
    
    @classmethod
    async def add_user_balance(cls, user_id: int, amount: float, 
                               transaction_type: str, notes: str = None) -> float:
        """Add balance to user and return new balance"""
        try:
            with cls.get_cursor() as cursor:
                # Update user balance
                cursor.execute("""
                    UPDATE users 
                    SET balance = balance + ?, last_active = datetime('now'), updated_at = datetime('now')
                    WHERE user_id = ?
                """, (amount, user_id))
                
                if cursor.rowcount == 0:
                    return 0.00
                
                # Get new balance
                cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
                result = cursor.fetchone()
                if result and len(result) > 0:
                    new_balance = float(result[0])
                else:
                    new_balance = 0.00
                
                # Create transaction record
                cursor.execute("""
                    INSERT INTO transactions (
                        user_id, amount, balance_after, transaction_type, description, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    user_id, amount, new_balance, transaction_type, 
                    f"Admin action: {notes}" if notes else f"Balance added via admin", 
                    datetime.now()
                ))
                
                logger.info(f"Added {amount} to user {user_id}, new balance: {new_balance}")
                return new_balance
        except Exception as e:
            logger.error(f"Error adding user balance: {e}")
            return 0.00
    
    # ==================== ADMIN CREDENTIALS METHODS ====================

    @classmethod
    async def create_admin_credential(cls, username: str, password: str, phone: str, 
                                      full_name: str = None, email: str = None, 
                                      role: str = 'admin') -> Optional[int]:
        """Create a new admin credential"""
        try:
            import hashlib
            password_hash = hashlib.sha256(password.encode()).hexdigest()
            
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    INSERT INTO admin_credentials 
                    (username, password_hash, phone, full_name, email, role, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (username, password_hash, phone, full_name, email, role, 
                      datetime.now(), datetime.now()))
                
                admin_id = cursor.lastrowid
                logger.info(f"✅ Created admin credential: {username} (ID: {admin_id})")
                return admin_id
        except Exception as e:
            logger.error(f"Error creating admin credential: {e}")
            return None

    @classmethod
    async def verify_admin_login(cls, username: str, password: str) -> Optional[Dict]:
        """Verify admin login credentials"""
        try:
            import hashlib
            password_hash = hashlib.sha256(password.encode()).hexdigest()
            
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    SELECT * FROM admin_credentials 
                    WHERE username = ? AND password_hash = ? AND is_active = 1
                """, (username, password_hash))
                
                row = cursor.fetchone()
                if row:
                    admin = dict(row)
                    # Update last login
                    cursor.execute("""
                        UPDATE admin_credentials 
                        SET last_login = ?, updated_at = ?
                        WHERE id = ?
                    """, (datetime.now(), datetime.now(), admin['id']))
                    
                    # Remove password hash from response
                    admin.pop('password_hash', None)
                    logger.info(f"✅ Admin logged in: {username}")
                    return admin
                return None
        except Exception as e:
            logger.error(f"Error verifying admin login: {e}")
            return None

    @classmethod
    async def verify_admin_login_by_phone(cls, phone: str, password: str) -> Optional[Dict]:
        """Verify admin login by phone number"""
        try:
            import hashlib
            password_hash = hashlib.sha256(password.encode()).hexdigest()
            
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    SELECT * FROM admin_credentials 
                    WHERE phone = ? AND password_hash = ? AND is_active = 1
                """, (phone, password_hash))
                
                row = cursor.fetchone()
                if row:
                    admin = dict(row)
                    # Update last login
                    cursor.execute("""
                        UPDATE admin_credentials 
                        SET last_login = ?, updated_at = ?
                        WHERE id = ?
                    """, (datetime.now(), datetime.now(), admin['id']))
                    
                    # Remove password hash from response
                    admin.pop('password_hash', None)
                    logger.info(f"✅ Admin logged in via phone: {phone}")
                    return admin
                return None
        except Exception as e:
            logger.error(f"Error verifying admin login by phone: {e}")
            return None

    @classmethod
    async def get_admin_by_id(cls, admin_id: int) -> Optional[Dict]:
        """Get admin by ID"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    SELECT id, username, phone, full_name, email, role, is_active, 
                           last_login, created_at, updated_at
                    FROM admin_credentials 
                    WHERE id = ? AND is_active = 1
                """, (admin_id,))
                
                row = cursor.fetchone()
                if row:
                    return dict(row)
                return None
        except Exception as e:
            logger.error(f"Error getting admin by ID: {e}")
            return None

    @classmethod
    async def update_admin_password(cls, admin_id: int, old_password: str, new_password: str) -> bool:
        """Update admin password"""
        try:
            import hashlib
            old_hash = hashlib.sha256(old_password.encode()).hexdigest()
            new_hash = hashlib.sha256(new_password.encode()).hexdigest()
            
            with cls.get_cursor() as cursor:
                # Verify old password
                cursor.execute("""
                    SELECT id FROM admin_credentials 
                    WHERE id = ? AND password_hash = ?
                """, (admin_id, old_hash))
                
                if not cursor.fetchone():
                    return False
                
                # Update to new password
                cursor.execute("""
                    UPDATE admin_credentials 
                    SET password_hash = ?, updated_at = ?
                    WHERE id = ?
                """, (new_hash, datetime.now(), admin_id))
                
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error updating admin password: {e}")
            return False

    @classmethod
    async def update_admin_profile(cls, admin_id: int, **kwargs) -> bool:
        """Update admin profile information"""
        try:
            allowed_fields = ['phone', 'full_name', 'email']
            updates = []
            values = []
            
            for field in allowed_fields:
                if field in kwargs:
                    updates.append(f"{field} = ?")
                    values.append(kwargs[field])
            
            if not updates:
                return False
            
            updates.append("updated_at = ?")
            values.append(datetime.now())
            values.append(admin_id)
            
            with cls.get_cursor() as cursor:
                cursor.execute(f"""
                    UPDATE admin_credentials 
                    SET {', '.join(updates)}
                    WHERE id = ?
                """, values)
                
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error updating admin profile: {e}")
            return False

    @classmethod
    async def get_all_admins(cls) -> List[Dict]:
        """Get all active admins"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    SELECT id, username, phone, full_name, email, role, is_active, 
                           last_login, created_at
                    FROM admin_credentials 
                    WHERE is_active = 1
                    ORDER BY created_at DESC
                """)
                
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting all admins: {e}")
            return []

    @classmethod
    async def deactivate_admin(cls, admin_id: int) -> bool:
        """Deactivate an admin account"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    UPDATE admin_credentials 
                    SET is_active = 0, updated_at = ?
                    WHERE id = ?
                """, (datetime.now(), admin_id))
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error deactivating admin: {e}")
            return False

    @classmethod
    async def activate_admin(cls, admin_id: int) -> bool:
        """Activate an admin account"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    UPDATE admin_credentials 
                    SET is_active = 1, updated_at = ?
                    WHERE id = ?
                """, (datetime.now(), admin_id))
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error activating admin: {e}")
            return False
    
    # ==================== TRANSACTION METHODS ====================
    
    @classmethod
    async def add_transaction(
        cls,
        user_id: int,
        transaction_type: str,
        amount: float,
        description: str,
        game_id: str = None
     ) -> int:
        """
        Add a transaction record

        Args:
            user_id: Telegram user ID
            transaction_type: Type of transaction ('deposit', 'withdrawal', 'purchase', 'winning')
            amount: Transaction amount (positive for deposit/winning, negative for purchase)
            description: Transaction description
            game_id: Associated game ID (optional)

        Returns:
            Transaction ID
        """
        try:
            with cls.get_cursor() as cursor:
                # Get current balance BEFORE the transaction
                cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
                result = cursor.fetchone()
                current_balance = float(result[0]) if result and result[0] is not None else 0.00
            
                # Calculate new balance
                if transaction_type in ['deposit', 'winning', 'initial_deposit', 'withdrawal_refund']:
                    new_balance = current_balance + amount
                    cursor.execute(
                        "UPDATE users SET balance = ? WHERE user_id = ?",
                        (new_balance, user_id)
                    )
                elif transaction_type in ['purchase', 'withdrawal', 'withdrawal_request']:
                    new_balance = max(0, current_balance - abs(amount))
                    cursor.execute(
                        "UPDATE users SET balance = ? WHERE user_id = ?",
                        (new_balance, user_id)
                    )
                else:
                    new_balance = current_balance
             
                # FIXED: Use correct column name 'transaction_type' and ensure balance_after is NOT NULL
                cursor.execute(
                    """
                    INSERT INTO transactions 
                    (user_id, transaction_type, amount, balance_after, description, game_id, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
                    """,
                    (user_id, transaction_type, amount, new_balance, description, game_id)
                )
               
                transaction_id = cursor.lastrowid
                
                logger.info(f"Added transaction {transaction_id} for user {user_id}: "
                           f"{transaction_type} {amount:.2f} birr - {description}")
              
                return transaction_id
              
        except Exception as e:
            logger.error(f"Error adding transaction for user {user_id}: {e}")
            return 0
    
    @classmethod
    async def update_balance_with_transaction(cls, user_id: int, amount: float,
                                              transaction_type: str, description: str = None,
                                              game_id: str = None) -> bool:
        """Update user balance and create transaction"""
        try:
            with cls.get_cursor() as cursor:
                # Update user balance
                if amount >= 0:
                    cursor.execute("""
                        UPDATE users SET balance = balance + ? WHERE user_id = ?
                    """, (amount, user_id))
                else:
                    # For deductions, ensure balance doesn't go negative
                    cursor.execute("""
                        UPDATE users 
                        SET balance = MAX(0, balance + ?) 
                        WHERE user_id = ?
                    """, (amount, user_id))
                
                if cursor.rowcount == 0:
                    return False
                
                # Get updated balance
                cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
                result = cursor.fetchone()
                new_balance = float(result[0]) if result and len(result) > 0 else 0.00
                
                # Create transaction record
                cursor.execute("""
                    INSERT INTO transactions (
                        user_id, amount, balance_after, transaction_type,
                        description, game_id, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    user_id, amount, new_balance, transaction_type,
                    description, game_id, datetime.now()
                ))
                
                # Update user stats for wins
                if transaction_type == 'bingo_win' and amount > 0:
                    cursor.execute("""                    
                    UPDATE users 
                    SET total_wins = total_wins + 1,
                        total_winnings = total_winnings + ?,
                        total_games_played = total_games_played + 1
                    WHERE user_id = ?
                """, (amount, user_id))
                elif transaction_type == 'card_purchase':
                    cursor.execute("""
                        UPDATE users 
                        SET total_games_played = total_games_played + 1
                        WHERE user_id = ?
                    """, (user_id,))
                
                return True
                
        except Exception as e:
            logger.error(f"Error updating balance with transaction: {e}")
            return False
    
    @classmethod
    async def create_transaction(cls, user_id: int, amount: float, 
                                 transaction_type: str, description: str = None,
                                 game_id: str = None, card_id: int = None,
                                 reference_id: str = None) -> int:
        """Create a transaction record"""
        try:
            # Get current balance
            user = await cls.get_user(user_id)
            current_balance = float(user['balance']) if user else 0.00
            
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    INSERT INTO transactions (
                        user_id, amount, balance_after, transaction_type,
                        description, game_id, card_id, reference_id, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    user_id, amount, current_balance + amount, transaction_type,
                    description, game_id, card_id, reference_id, datetime.now()
                ))
                
                return cursor.lastrowid
                
        except Exception as e:
            logger.error(f"Error creating transaction: {e}")
            return 0
    
    @classmethod
    async def deduct_balance_with_transaction_id(cls, user_id: int, amount: float,
                                                transaction_id: int, description: str = None) -> bool:
        """Deduct balance using existing transaction ID"""
        try:
            with cls.get_cursor() as cursor:
                # Ensure balance doesn't go negative
                cursor.execute("""
                    UPDATE users 
                    SET balance = MAX(0, balance - ?) 
                    WHERE user_id = ?
                """, (amount, user_id))
                
                if cursor.rowcount == 0:
                    return False
                
                # Get updated balance
                cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
                result = cursor.fetchone()
                new_balance = float(result[0]) if result and len(result) > 0 else 0.00
                
                # Update transaction with new balance
                cursor.execute("""
                    UPDATE transactions 
                    SET balance_after = ? 
                    WHERE id = ?
                """, (new_balance, transaction_id))
                
                return True
                
        except Exception as e:
            logger.error(f"Error deducting balance: {e}")
            return False
    
    @classmethod
    async def get_user_transactions(cls, user_id: int, limit: int = 50) -> List[Dict]:
        """Get user transaction history"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    SELECT * FROM transactions 
                    WHERE user_id = ? 
                    ORDER BY created_at DESC 
                    LIMIT ?
                """, (user_id, limit))
                rows = cursor.fetchall()
                
                transactions = []
                for row in rows:
                    trans = dict(row)
                    for key in ['amount', 'balance_after']:
                        if trans.get(key) is not None:
                            trans[key] = float(trans[key])
                    transactions.append(trans)
                
                return transactions
                
        except Exception as e:
            logger.error(f"Error getting user transactions: {e}")
            return []
    
    # ==================== GAME HISTORY METHODS ====================
    
    @classmethod
    async def register_completed_game(cls, game_data: Dict) -> bool:
        """Register completed game to history"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    INSERT INTO game_history (
                        game_id, game_type, round_number, total_players,
                        total_cards_sold, prize_pool, winner_id, winner_username,
                        winner_card_index, winner_payout,
                        numbers_called, called_numbers, pattern_type, winning_pattern,
                        total_sales, game_date,
                        start_time, end_time, duration_seconds,
                        real_cards_sold, fake_cards_sold,
                        winners_count, winners_data, winner_payouts,
                        is_fake_winner, min_fake_players, max_fake_players,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    game_data.get('game_id'),
                    game_data.get('game_type', 'round_based'),
                    game_data.get('round_number', 1),
                    game_data.get('total_players', 0),
                    game_data.get('total_cards_sold', 0),
                    game_data.get('prize_pool', 0.00),
                    game_data.get('winner_id'),
                    game_data.get('winner_username'),
                    game_data.get('winner_card_index'),
                    game_data.get('winner_payout', 0.00),
                    json.dumps(game_data.get('numbers_called', [])),
                    json.dumps(game_data.get('called_numbers', [])),
                    game_data.get('pattern_type'),
                    json.dumps(game_data.get('winning_pattern', {})),
                    game_data.get('total_sales', 0.00),
                    game_data.get('game_date', datetime.now().date()),
                    game_data.get('start_time'),
                    game_data.get('end_time'),
                    game_data.get('duration_seconds', 0),
                    game_data.get('real_cards_sold', 0),
                    game_data.get('fake_cards_sold', 0),
                    game_data.get('winners_count', 0),
                    json.dumps(game_data.get('winners_data', [])),
                    json.dumps(game_data.get('winner_payouts', [])),
                    game_data.get('is_fake_winner', 0),
                    game_data.get('min_fake_players', 10),
                    game_data.get('max_fake_players', 40),
                    datetime.now()
                ))
                
                return True
                
        except Exception as e:
            logger.error(f"Error registering completed game: {e}")
            return False
    
    @classmethod
    async def get_game_history(cls, limit: int = 10) -> List[Dict]:
        """Get game history"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    SELECT * FROM game_history 
                    ORDER BY created_at DESC 
                    LIMIT ?
                """, (limit,))
                rows = cursor.fetchall()
                
                games = []
                for row in rows:
                    game = dict(row)
                    for key in ['prize_pool', 'winner_payout', 'total_sales']:
                        if game.get(key) is not None:
                            game[key] = float(game[key])
                    
                    if game.get('numbers_called'):
                        try:
                            game['numbers_called'] = json.loads(game['numbers_called'])
                        except:
                            game['numbers_called'] = []
                    
                    if game.get('called_numbers'):
                        try:
                            game['called_numbers'] = json.loads(game['called_numbers'])
                        except:
                            game['called_numbers'] = []
                    
                    if game.get('winning_pattern'):
                        try:
                            game['winning_pattern'] = json.loads(game['winning_pattern'])
                        except:
                            game['winning_pattern'] = {}
                    
                    if game.get('winners_data'):
                        try:
                            game['winners_data'] = json.loads(game['winners_data'])
                        except:
                            game['winners_data'] = []
                    
                    if game.get('winner_payouts'):
                        try:
                            game['winner_payouts'] = json.loads(game['winner_payouts'])
                        except:
                            game['winner_payouts'] = []
                    
                    games.append(game)
                
                return games
                
        except Exception as e:
            logger.error(f"Error getting game history: {e}")
            return []
    
    # ==================== ADMIN METHODS ====================
    
    @classmethod
    async def get_admin_by_user_id(cls, user_id: int) -> Optional[Dict]:
        """Get admin by user ID"""
        try:
            with cls.get_cursor() as cursor:
                # First, check if there's an admins table
                cursor.execute("SELECT * FROM admins WHERE user_id = ? AND is_active = 1", (user_id,))
                row = cursor.fetchone()
                if row:
                    return dict(row)
                
                # Fallback: Check if user has admin privileges in users table
                cursor.execute("""
                    SELECT * FROM users 
                    WHERE user_id = ? AND is_admin = 1
                """, (user_id,))
                row = cursor.fetchone()
                if row:
                    return dict(row)
                
                return None
        except Exception as e:
            logger.error(f"Error getting admin by user ID {user_id}: {e}")
            return None
        
        
    @staticmethod
    async def verify_admin_login(username, password):
        """Verify admin login credentials using admin_credentials table with hashed passwords"""
        try:
            import hashlib
            # Hash the provided password
            password_hash = hashlib.sha256(password.encode()).hexdigest()
        
            with Database.get_cursor() as cursor:
                # Use the admin_credentials table
                cursor.execute("""
                    SELECT * FROM admin_credentials 
                    WHERE username = ? AND password_hash = ? AND is_active = 1
                """, (username, password_hash))
            
                row = cursor.fetchone()
                if row:
                    # Convert row to dict using column names
                    columns = [description[0] for description in cursor.description]
                    admin_data = dict(zip(columns, row))
                
                    # Update last login
                    cursor.execute("""
                        UPDATE admin_credentials 
                        SET last_login = ?, updated_at = ?
                        WHERE id = ?
                    """, (datetime.now(), datetime.now(), admin_data['id']))
                
                    # Return admin data without password hash
                    return {
                       'id': admin_data['id'],
                        'username': admin_data['username'],
                       'full_name': admin_data['full_name'] or admin_data['username'],
                       'phone': admin_data['phone'],
                       'email': admin_data['email'],
                       'role': admin_data['role']
                    }
            
                # Fallback: Check the old admins table for backward compatibility
                cursor.execute("""
                   SELECT name FROM sqlite_master 
                   WHERE type='table' AND name='admins'
                """)
                if cursor.fetchone():
                    cursor.execute("""
                       SELECT * FROM admins 
                       WHERE username = ? AND password = ? AND role IN ('admin', 'super_admin')
                    """, (username, password))
                
                    old_row = cursor.fetchone()
                    if old_row:
                        # Migrate this admin to the new table
                        new_password_hash = hashlib.sha256(password.encode()).hexdigest()
                        cursor.execute("""
                           INSERT OR IGNORE INTO admin_credentials 
                           (username, password_hash, phone, full_name, email, role, created_at, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            old_row[1], new_password_hash, old_row[3], old_row[4], 
                            old_row[5], old_row[6], datetime.now(), datetime.now()
                        ))
                    
                        return {
                           'id': old_row[0],
                           'username': old_row[1],
                           'full_name': old_row[4] or old_row[1],
                           'phone': old_row[3],
                           'email': old_row[5],
                           'role': old_row[6]
                        }
            
                return None
            
        except Exception as e:
            logger.error(f"Error verifying admin login: {e}")
            return None
        
        
        
        
        
    @staticmethod
    async def verify_admin_login_by_phone(phone, password):
        """Verify admin login by phone number"""
        try:
            import hashlib
            password_hash = hashlib.sha256(password.encode()).hexdigest()
        
            with Database.get_cursor() as cursor:
                cursor.execute("""
                   SELECT * FROM admin_credentials 
                   WHERE phone = ? AND password_hash = ? AND is_active = 1
                """, (phone, password_hash))
            
                row = cursor.fetchone()
                if row:
                    columns = [description[0] for description in cursor.description]
                    admin_data = dict(zip(columns, row))
                
                    # Update last login
                    cursor.execute("""
                        UPDATE admin_credentials 
                        SET last_login = ?, updated_at = ?
                        WHERE id = ?
                    """, (datetime.now(), datetime.now(), admin_data['id']))
                
                    return {
                        'id': admin_data['id'],
                        'username': admin_data['username'],
                        'full_name': admin_data['full_name'] or admin_data['username'],
                        'phone': admin_data['phone'],
                        'email': admin_data['email'],
                        'role': admin_data['role']
                    }
                return None
        except Exception as e:
            logger.error(f"Error verifying admin login by phone: {e}")
            return None
        
    
    @classmethod
    async def record_admin_transaction(cls, admin_id: str, action: str, 
                                       target_type: str, target_id: str, 
                                       details: Dict = None) -> int:
        """Record admin transaction"""
        try:
            details_json = json.dumps(details) if details else None
            
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    INSERT INTO admin_transactions (
                        admin_id, action, target_type, target_id, details, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """, (admin_id, action, target_type, target_id, details_json, datetime.now()))
                
                return cursor.lastrowid
        except Exception as e:
            logger.error(f"Error recording admin transaction: {e}")
            return 0
    
    @classmethod
    async def get_admin_stats(cls) -> Dict:
        """Get admin statistics - FIXED VERSION with commission from commission_records"""
        try:
            with cls.get_cursor() as cursor:
                stats = {}
                
                # Total users
                cursor.execute("SELECT COUNT(*) as count FROM users WHERE deleted_at IS NULL")
                result = cursor.fetchone()
                stats['total_users'] = result[0] if result and len(result) > 0 else 0
                
                # Active users (last 7 days)
                cursor.execute("""
                    SELECT COUNT(DISTINCT user_id) as count 
                    FROM transactions 
                    WHERE created_at >= datetime('now', '-7 days')
                """)
                result = cursor.fetchone()
                stats['active_users'] = result[0] if result and len(result) > 0 else 0
                
                # Total cards sold
                cursor.execute("SELECT COUNT(*) as count FROM player_cards WHERE is_active = 1")
                result = cursor.fetchone()
                stats['total_cards'] = result[0] if result and len(result) > 0 else 0
                
                # Real cards sold
                cursor.execute("SELECT COUNT(*) as count FROM player_cards WHERE is_active = 1 AND is_fake = 0")
                result = cursor.fetchone()
                stats['real_cards'] = result[0] if result and len(result) > 0 else 0
                
                # Fake cards sold
                cursor.execute("SELECT COUNT(*) as count FROM player_cards WHERE is_active = 1 AND is_fake = 1")
                result = cursor.fetchone()
                stats['fake_cards'] = result[0] if result and len(result) > 0 else 0
                
                # Total games
                cursor.execute("SELECT COUNT(*) as count FROM games")
                result = cursor.fetchone()
                stats['total_games'] = result[0] if result and len(result) > 0 else 0
                
                # Total prize pool
                cursor.execute("SELECT COALESCE(SUM(prize_pool), 0) as total FROM games")
                result = cursor.fetchone()
                stats['total_prize_pool'] = float(result[0]) if result and len(result) > 0 and result[0] is not None else 0.00
                
                # Total winnings paid
                cursor.execute("SELECT COALESCE(SUM(winner_payout), 0) as total FROM games")
                result = cursor.fetchone()
                stats['total_winnings'] = float(result[0]) if result and len(result) > 0 and result[0] is not None else 0.00
                
                # Get total commission from commission_records (source of truth)
                cursor.execute("SELECT COALESCE(SUM(commission_amount), 0) as total FROM commission_records")
                result = cursor.fetchone()
                stats['total_commission'] = float(result[0]) if result and len(result) > 0 and result[0] is not None else 0.00
                
                # Pending withdrawals
                cursor.execute("""
                    SELECT COUNT(*) as count, COALESCE(SUM(amount), 0) as total 
                    FROM withdrawal_requests 
                    WHERE status = 'pending'
                """)
                result = cursor.fetchone()
                if result and len(result) >= 2:
                    stats['pending_withdrawals'] = result[0] if result[0] is not None else 0
                    stats['pending_amount'] = float(result[1]) if result[1] is not None else 0.00
                else:
                    stats['pending_withdrawals'] = 0
                    stats['pending_amount'] = 0.00
                
                # Pending payments
                cursor.execute("""
                    SELECT COUNT(*) as count, COALESCE(SUM(amount), 0) as total 
                    FROM payments 
                    WHERE status = 'pending'
                """)
                result = cursor.fetchone()
                if result and len(result) >= 2:
                    stats['pending_payments'] = result[0] if result[0] is not None else 0
                    stats['pending_payments_amount'] = float(result[1]) if result[1] is not None else 0.00
                else:
                    stats['pending_payments'] = 0
                    stats['pending_payments_amount'] = 0.00
                
                # Today's stats
                cursor.execute("""
                    SELECT COUNT(*) as count FROM games 
                    WHERE date(created_at) = date('now')
                """)
                result = cursor.fetchone()
                stats['today_games'] = result[0] if result and len(result) > 0 else 0
                
                cursor.execute("""
                    SELECT COALESCE(SUM(prize_pool), 0) as total FROM games 
                    WHERE date(created_at) = date('now')
                """)
                result = cursor.fetchone()
                stats['today_prize_pool'] = float(result[0]) if result and len(result) > 0 and result[0] is not None else 0.00
                
                cursor.execute("""
                    SELECT COUNT(*) as count FROM player_cards 
                    WHERE date(purchase_time) = date('now') AND is_active = 1
                """)
                result = cursor.fetchone()
                stats['today_cards'] = result[0] if result and len(result) > 0 else 0
                
                # House balance
                cursor.execute("SELECT COALESCE(SUM(amount), 0) as total FROM house_balance")
                result = cursor.fetchone()
                stats['house_balance'] = float(result[0]) if result and len(result) > 0 and result[0] is not None else 0.00
                
                return stats
        except Exception as e:
            logger.error(f"Error getting admin stats: {e}")
            return {}
    
    @classmethod
    async def get_total_users(cls) -> int:
        """Get total number of users"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("SELECT COUNT(*) as count FROM users WHERE deleted_at IS NULL AND user_id > -1")
                result = cursor.fetchone()
                if result and len(result) > 0:
                    return result[0]
                return 0
        except Exception as e:
            logger.error(f"Error getting total users: {e}")
            return 0
    @classmethod
    def _get_total_users(cls) -> int:
        """Get total number of users"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("SELECT COUNT(*) as count FROM users WHERE deleted_at IS NULL AND user_id > -1")
                result = cursor.fetchone()
                if result and len(result) > 0:
                    return result[0]
                return 0
        except Exception as e:
            logger.error(f"Error getting total users: {e}")
            return 0
    
    @classmethod
    async def get_total_users_count(cls) -> int:
        """Get total number of users (alias)"""
        return await cls.get_total_users()
    
    @classmethod
    async def get_active_users_count(cls, days: int = 7) -> int:
        """Get number of active users in the last N days"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    SELECT COUNT(DISTINCT user_id) as count 
                    FROM transactions 
                    WHERE created_at >= datetime('now', ?)
                """, (f'-{days} days',))
                result = cursor.fetchone()
                if result and len(result) > 0:
                    return result[0]
                return 0
        except Exception as e:
            logger.error(f"Error getting active users count: {e}")
            return 0
    
    @classmethod
    async def get_total_cards_sold(cls) -> int:
        """Get total number of cards sold"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("SELECT COUNT(*) as count FROM player_cards WHERE is_active = 1")
                result = cursor.fetchone()
                if result and len(result) > 0:
                    return result[0]
                return 0
        except Exception as e:
            logger.error(f"Error getting total cards sold: {e}")
            return 0
    
    @classmethod
    async def get_total_prizes_paid(cls) -> float:
        """Get total prizes paid"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("SELECT COALESCE(SUM(winner_payout), 0) as total FROM games")
                result = cursor.fetchone()
                return float(result[0]) if result and len(result) > 0 and result[0] is not None else 0.00
        except Exception as e:
            logger.error(f"Error getting total prizes paid: {e}")
            return 0.00
    
    @classmethod
    async def get_total_games(cls) -> int:
        """Get total number of games"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("SELECT COUNT(*) as count FROM games")
                result = cursor.fetchone()
                if result and len(result) > 0:
                    return result[0]
                return 0
        except Exception as e:
            logger.error(f"Error getting total games: {e}")
            return 0
    
    @classmethod
    def _get_total_games(cls) -> int:
        """Get total number of games"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("SELECT COUNT(*) as count FROM games")
                result = cursor.fetchone()
                if result and len(result) > 0:
                    return result[0]
                return 0
        except Exception as e:
            logger.error(f"Error getting total games: {e}")
            return 0
    
    @classmethod
    async def get_total_users_balance(cls) -> float:
        """Get total balance of all users"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    SELECT SUM(balance) as total_balance 
                    FROM users 
                    WHERE balance > 0 AND deleted_at IS NULL
                """)
                row = cursor.fetchone()
                total_balance = float(row['total_balance'] or 0) if row else 0
                return total_balance
        except Exception as e:
            logger.error(f"Error getting total users balance: {e}")
            return 0.00
    
    @classmethod
    async def get_weekly_revenue(cls, weeks_back: int = 8) -> List[Dict]:
        """Get weekly revenue data from commission_records"""
        return await cls.get_weekly_commission(weeks_back)
    
    @classmethod
    async def get_this_week_commission(cls) -> float:
        """Get this week's commission from commission_records"""
        return await cls.get_this_week_commission()
    
    @classmethod
    async def get_total_commission(cls) -> float:
        """Get total commission from commission_records"""
        return await cls.get_total_commission()
    
    @classmethod
    async def get_game_commission(cls, game_id: str) -> Optional[Dict]:
        """Get commission for a specific game from commission_records"""
        return await cls.get_game_commission(game_id)
    
    @classmethod
    async def get_recent_transactions(cls, limit: int = 10) -> List[Dict]:
        """Get recent transactions"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    SELECT t.*, u.username, u.full_name
                    FROM transactions t
                    LEFT JOIN users u ON t.user_id = u.user_id
                    ORDER BY t.created_at DESC
                    LIMIT ?
                """, (limit,))
                rows = cursor.fetchall()
                
                transactions = []
                for row in rows:
                    trans = dict(row)
                    # Convert decimals to float
                    for key in ['amount', 'balance_after']:
                        if trans.get(key) is not None:
                            trans[key] = float(trans[key])
                    transactions.append(trans)
                
                return transactions
        except Exception as e:
            logger.error(f"Error getting recent transactions: {e}")
            return []
    @classmethod
    def _get_recent_transactions(cls, limit: int = 10) -> List[Dict]:
        """Get recent transactions"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    SELECT t.*, u.username, u.full_name
                    FROM transactions t
                    LEFT JOIN users u ON t.user_id = u.user_id
                    ORDER BY t.created_at DESC
                    LIMIT ?
                """, (limit,))
                rows = cursor.fetchall()
                
                transactions = []
                for row in rows:
                    trans = dict(row)
                    # Convert decimals to float
                    for key in ['amount', 'balance_after']:
                        if trans.get(key) is not None:
                            trans[key] = float(trans[key])
                    transactions.append(trans)
                
                return transactions
        except Exception as e:
            logger.error(f"Error getting recent transactions: {e}")
            return []
    #================================================
    @classmethod
    def _get_admin_stats_db(cls):
        """All DB-related admin stats (runs in thread)"""
        try:
            with cls.get_cursor() as cursor:

                # Total users
                total_users = Database._get_total_users()
                # Total games
                total_games = Database._get_total_games()
                # Today's revenue
                cursor.execute("""
                    SELECT COALESCE(SUM(commission_amount), 0)
                    FROM commission_records 
                    WHERE date(recorded_at) = date('now', 'localtime')
                """)
                today_revenue = float(cursor.fetchone()[0] or 0)

                # Total revenue
                cursor.execute("""
                    SELECT COALESCE(SUM(commission_amount), 0)
                    FROM commission_records
                """)
                total_revenue = float(cursor.fetchone()[0] or 0)

                # This week revenue
                cursor.execute("""
                    SELECT COALESCE(SUM(commission_amount), 0)
                    FROM commission_records 
                    WHERE recorded_at >= datetime('now', '-7 days')
                """)
                this_week_commission = float(cursor.fetchone()[0] or 0)

                # Total balance (real users with fallback)
                try:
                    cursor.execute("""
                        SELECT COALESCE(SUM(balance), 0)
                        FROM users 
                        WHERE balance > 0 
                        AND user_id > -1
                    """)
                    total_balance = float(cursor.fetchone()[0] or 0)
                except:
                    cursor.execute("""
                        SELECT COALESCE(SUM(balance), 0)
                        FROM users 
                        WHERE user_id > -1
                    """)
                    total_balance = float(cursor.fetchone()[0] or 0)

                return {
                    "total_games": total_games,
                    "total_users": total_users,
                    "today_revenue": today_revenue,
                    "total_revenue": total_revenue,
                    "this_week_commission": this_week_commission,
                    "total_balance": total_balance
                }

        except Exception as e:
            logger.error(f"DB error (admin stats): {e}")
            return {
                "error": str(e),
                "total_games": 0,
                "total_users": 0,
                "today_revenue": 0,
                "total_revenue": 0,
                "this_week_commission": 0,
                "total_balance": 0
            }
    @classmethod
    async def get_admin_users(cls, limit: int = 20, offset: int = 0) -> List[Dict]:
        """Get admin users with pagination"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    SELECT u.*,
                           (SELECT COUNT(*) FROM player_cards pc 
                            WHERE pc.user_id = u.user_id AND pc.is_active = 1) as total_cards,
                           (SELECT COUNT(*) FROM transactions t 
                            WHERE t.user_id = u.user_id AND t.transaction_type = 'winning') as total_wins,
                           (SELECT COALESCE(SUM(amount), 0) FROM transactions t 
                            WHERE t.user_id = u.user_id AND t.transaction_type = 'winning') as total_winnings_amount
                    FROM users u
                    WHERE u.deleted_at IS NULL
                        AND u.user_id > -1
                    ORDER BY u.created_at DESC
                    LIMIT ? OFFSET ?
                """, (limit, offset))
                rows = cursor.fetchall()
                
                users = []
                for row in rows:
                    user = dict(row)
                    # Convert decimals to float
                    for key in ['balance', 'total_winnings', 'total_winnings_amount']:
                        if user.get(key) is not None:
                            user[key] = float(user[key])
                    users.append(user)
                
                return users
        except Exception as e:
            logger.error(f"Error getting admin users: {e}")
            return []
    @classmethod
    def _get_admin_users(cls, limit: int = 20, offset: int = 0) -> List[Dict]:
        """Get admin users with pagination"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    SELECT u.*,
                           (SELECT COUNT(*) FROM player_cards pc 
                            WHERE pc.user_id = u.user_id AND pc.is_active = 1) as total_cards,
                           (SELECT COUNT(*) FROM transactions t 
                            WHERE t.user_id = u.user_id AND t.transaction_type = 'bingo_win') as total_wins,
                           (SELECT COALESCE(SUM(amount), 0) FROM transactions t 
                            WHERE t.user_id = u.user_id AND t.transaction_type = 'bingo_win') as total_winnings_amount
                    FROM users u
                    WHERE u.deleted_at IS NULL
                    ORDER BY u.created_at DESC
                    LIMIT ? OFFSET ?
                """, (limit, offset))
                rows = cursor.fetchall()
                
                users = []
                for row in rows:
                    user = dict(row)
                    # Convert decimals to float
                    for key in ['balance', 'total_winnings', 'total_winnings_amount']:
                        if user.get(key) is not None:
                            user[key] = float(user[key])
                    users.append(user)
                
                return users
        except Exception as e:
            logger.error(f"Error getting admin users: {e}")
            return []
    
    @classmethod
    async def get_admin_payments(cls, limit: int = 20, offset: int = 0, status: str = 'all') -> List[Dict]:
        """Get admin payments with pagination"""
        try:
            with cls.get_cursor() as cursor:
                if status == 'all':
                    cursor.execute("""
                        SELECT p.*, u.username, u.full_name, u.balance
                        FROM payments p
                        LEFT JOIN users u ON p.user_id = u.user_id
                        ORDER BY p.created_at DESC
                        LIMIT ? OFFSET ?
                    """, (limit, offset))
                else:
                    cursor.execute("""
                        SELECT p.*, u.username, u.full_name, u.balance
                        FROM payments p
                        LEFT JOIN users u ON p.user_id = u.user_id
                        WHERE p.status = ?
                        ORDER BY p.created_at DESC
                        LIMIT ? OFFSET ?
                    """, (status, limit, offset))
                
                rows = cursor.fetchall()
                
                payments = []
                for row in rows:
                    payment = dict(row)
                    # Convert decimals to float
                    for key in ['amount', 'balance']:
                        if payment.get(key) is not None:
                            payment[key] = float(payment[key])
                    payments.append(payment)
                
                return payments
        except Exception as e:
            logger.error(f"Error getting admin payments: {e}")
            return []
    @classmethod
    def _get_admin_payments(cls, limit: int = 20, offset: int = 0, status: str = 'all') -> List[Dict]:
        """Get admin payments with pagination"""
        try:
            with cls.get_cursor() as cursor:
                if status == 'all':
                    cursor.execute("""
                        SELECT p.*, u.username, u.full_name, u.balance
                        FROM payments p
                        LEFT JOIN users u ON p.user_id = u.user_id
                        ORDER BY p.created_at DESC
                        LIMIT ? OFFSET ?
                    """, (limit, offset))
                else:
                    cursor.execute("""
                        SELECT p.*, u.username, u.full_name, u.balance
                        FROM payments p
                        LEFT JOIN users u ON p.user_id = u.user_id
                        WHERE p.status = ?
                        ORDER BY p.created_at DESC
                        LIMIT ? OFFSET ?
                    """, (status, limit, offset))
                
                rows = cursor.fetchall()
                
                payments = []
                for row in rows:
                    payment = dict(row)
                    # Convert decimals to float
                    for key in ['amount', 'balance']:
                        if payment.get(key) is not None:
                            payment[key] = float(payment[key])
                    payments.append(payment)
                
                return payments
        except Exception as e:
            logger.error(f"Error getting admin payments: {e}")
            return []
    
    @classmethod
    async def get_admin_transactions(cls, limit: int = 20, offset: int = 0, 
                                     transaction_type: str = 'all') -> List[Dict]:
        """Get admin transactions with pagination"""
        try:
            with cls.get_cursor() as cursor:
                if transaction_type == 'all':
                    cursor.execute("""
                        SELECT t.*, u.username, u.full_name
                        FROM transactions t
                        LEFT JOIN users u ON t.user_id = u.user_id
                        ORDER BY t.created_at DESC
                        LIMIT ? OFFSET ?
                    """, (limit, offset))
                else:
                    cursor.execute("""
                        SELECT t.*, u.username, u.full_name
                        FROM transactions t
                        LEFT JOIN users u ON t.user_id = u.user_id
                        WHERE t.transaction_type = ?
                        ORDER BY t.created_at DESC
                        LIMIT ? OFFSET ?
                    """, (transaction_type, limit, offset))
                
                rows = cursor.fetchall()
                
                transactions = []
                for row in rows:
                    trans = dict(row)
                    # Convert decimals to float
                    for key in ['amount', 'balance_after']:
                        if trans.get(key) is not None:
                            trans[key] = float(trans[key])
                    transactions.append(trans)
                
                return transactions
        except Exception as e:
            logger.error(f"Error getting admin transactions: {e}")
            return []
    
    @classmethod
    async def get_total_payments(cls, status: str = 'all') -> int:
        """Get total number of payments"""
        try:
            with cls.get_cursor() as cursor:
                if status == 'all':
                    cursor.execute("SELECT COUNT(*) as count FROM payments")
                else:
                    cursor.execute("SELECT COUNT(*) as count FROM payments WHERE status = ?", (status,))
                
                result = cursor.fetchone()
                if result and len(result) > 0:
                    return result[0]
                return 0
        except Exception as e:
            logger.error(f"Error getting total payments: {e}")
            return 0
    @classmethod
    def _get_total_payments(cls, status: str = 'all') -> int:
        """Get total number of payments"""
        try:
            with cls.get_cursor() as cursor:
                if status == 'all':
                    cursor.execute("SELECT COUNT(*) as count FROM payments")
                else:
                    cursor.execute("SELECT COUNT(*) as count FROM payments WHERE status = ?", (status,))
                
                result = cursor.fetchone()
                if result and len(result) > 0:
                    return result[0]
                return 0
        except Exception as e:
            logger.error(f"Error getting total payments: {e}")
            return 0
    
    @classmethod
    async def get_total_transactions(cls, transaction_type: str = 'all') -> int:
        """Get total number of transactions"""
        try:
            with cls.get_cursor() as cursor:
                if transaction_type == 'all':
                    cursor.execute("SELECT COUNT(*) as count FROM transactions")
                else:
                    cursor.execute("SELECT COUNT(*) as count FROM transactions WHERE transaction_type = ?", (transaction_type,))
                
                result = cursor.fetchone()
                if result and len(result) > 0:
                    return result[0]
                return 0
        except Exception as e:
            logger.error(f"Error getting total transactions: {e}")
            return 0
        
        
        # Add these methods to the Database class in database/db.py

    @classmethod
    async def get_admin_transactions_filtered(cls, limit: int = 20, offset: int = 0, transaction_types: List[str] = None) -> List[Dict]:
        """
        Get transactions with filtering by type
        """
        try:
            with cls.get_cursor() as cursor:
                if transaction_types and len(transaction_types) > 0:
                    placeholders = ','.join(['?'] * len(transaction_types))
                    cursor.execute(f"""
                        SELECT t.*, u.username 
                        FROM transactions t
                        LEFT JOIN users u ON t.user_id = u.user_id
                        WHERE t.transaction_type IN ({placeholders})
                        ORDER BY t.created_at DESC
                        LIMIT ? OFFSET ?
                    """, (*transaction_types, limit, offset))
                else:
                    cursor.execute("""
                        SELECT t.*, u.username 
                        FROM transactions t
                        LEFT JOIN users u ON t.user_id = u.user_id
                        ORDER BY t.created_at DESC
                        LIMIT ? OFFSET ?
                    """, (limit, offset))
                rows = cursor.fetchall()
                transactions = []
                for row in rows:
                    transaction = dict(row)
                    if isinstance(transaction.get('amount'), decimal.Decimal):
                        transaction['amount'] = float(transaction['amount'])
                    transactions.append(transaction)
                return transactions
        except Exception as e:
            logger.error(f"Error getting filtered admin transactions: {e}")
            return []
    
    @classmethod
    def _get_admin_transactions_filtered(cls, limit: int = 20, offset: int = 0, transaction_types: List[str] = None) -> List[Dict]:
        """
        Get transactions with filtering by type
        """
        try:
            with cls.get_cursor() as cursor:
                if transaction_types and len(transaction_types) > 0:
                    placeholders = ','.join(['?'] * len(transaction_types))
                    cursor.execute(f"""
                        SELECT t.*, u.username 
                        FROM transactions t
                        LEFT JOIN users u ON t.user_id = u.user_id
                        WHERE t.transaction_type IN ({placeholders})
                        ORDER BY t.created_at DESC
                        LIMIT ? OFFSET ?
                    """, (*transaction_types, limit, offset))
                else:
                    cursor.execute("""
                        SELECT t.*, u.username 
                        FROM transactions t
                        LEFT JOIN users u ON t.user_id = u.user_id
                        ORDER BY t.created_at DESC
                        LIMIT ? OFFSET ?
                    """, (limit, offset))
                rows = cursor.fetchall()
                transactions = []
                for row in rows:
                    transaction = dict(row)
                    if isinstance(transaction.get('amount'), decimal.Decimal):
                        transaction['amount'] = float(transaction['amount'])
                    transactions.append(transaction)
                return transactions
        except Exception as e:
            logger.error(f"Error getting filtered admin transactions: {e}")
            return []

    @classmethod
    async def get_total_transactions_filtered(cls, transaction_types: List[str] = None) -> int:
        """
        Get total count of transactions with filtering by type
        """
        try:
            with cls.get_cursor() as cursor:
                if transaction_types and len(transaction_types) > 0:
                    placeholders = ','.join(['?'] * len(transaction_types))
                    cursor.execute(f"""
                        SELECT COUNT(*) as total 
                        FROM transactions 
                        WHERE transaction_type IN ({placeholders})
                    """, transaction_types)
                else:
                    cursor.execute("SELECT COUNT(*) as total FROM transactions")
            
                row = cursor.fetchone()
                return row[0] if row else 0
        except Exception as e:
             logger.error(f"Error getting filtered total transactions: {e}")
             return 0
    @classmethod
    def _get_total_transactions_filtered(cls, transaction_types: List[str] = None) -> int:
        """
        Get total count of transactions with filtering by type
        """
        try:
            with cls.get_cursor() as cursor:
                if transaction_types and len(transaction_types) > 0:
                    placeholders = ','.join(['?'] * len(transaction_types))
                    cursor.execute(f"""
                        SELECT COUNT(*) as total 
                        FROM transactions 
                        WHERE transaction_type IN ({placeholders})
                    """, transaction_types)
                else:
                    cursor.execute("SELECT COUNT(*) as total FROM transactions")
            
                row = cursor.fetchone()
                return row[0] if row else 0
        except Exception as e:
             logger.error(f"Error getting filtered total transactions: {e}")
             return 0
        
    @classmethod
    async def get_payment(cls, payment_id: int) -> Optional[Dict]:
        """Get payment by ID"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    SELECT p.*, u.username, u.full_name
                    FROM payments p
                    LEFT JOIN users u ON p.user_id = u.user_id
                    WHERE p.id = ?
                """, (payment_id,))
                row = cursor.fetchone()
                
                if row:
                    payment = dict(row)
                    if payment.get('amount') is not None:
                        payment['amount'] = float(payment['amount'])
                    return payment
                return None
        except Exception as e:
            logger.error(f"Error getting payment: {e}")
            return None
    
    # ==================== WITHDRAWAL METHODS ====================
    
    @classmethod
    async def create_withdrawal_request(cls, user_id: int, amount: float, 
                                        phone_number: str, method: str = 'tele_birr',
                                        full_name: str = None, payment_method: str = None) -> int:
        """Create a withdrawal request - FIXED VERSION with all columns"""
        try:
            with cls.get_cursor() as cursor:
                # First, create transaction (THIS ALREADY UPDATES THE BALANCE)
                transaction_id = await cls.add_transaction(
                    user_id, 
                    'withdrawal_request',
                    -amount, 
                    f"Withdrawal request via {method} to {phone_number}"
                )
                
                # Use payment_method from param or fallback to method
                pm = payment_method or method or 'tele_birr'
                
                # Then create withdrawal request
                cursor.execute('''
                    INSERT INTO withdrawal_requests 
                    (user_id, amount, phone_number, method, payment_method, full_name, status, transaction_id, requested_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ''', (user_id, amount, phone_number, method, pm, full_name, 'pending', transaction_id))
                
                request_id = cursor.lastrowid
                logger.info(f"Created withdrawal request {request_id} for user {user_id}, amount: {amount}")
                return request_id
        except Exception as e:
            logger.error(f"Error creating withdrawal request: {e}")
            return 0
    
    @classmethod
    async def get_withdrawals(cls, status: str = 'all', limit: int = 100, offset: int = 0) -> List[Dict]:
        """Get withdrawals with optional status filter - FIXED VERSION"""
        try:
            conn = cls.get_connection()
            cursor = conn.cursor()
            
            try:
                if status == 'all':
                    cursor.execute('''
                        SELECT wr.*, u.username, u.full_name, u.balance as user_balance
                        FROM withdrawal_requests wr
                        LEFT JOIN users u ON wr.user_id = u.user_id
                        ORDER BY wr.requested_at DESC
                        LIMIT ? OFFSET ?
                    ''', (limit, offset))
                else:
                    cursor.execute('''
                        SELECT wr.*, u.username, u.full_name, u.balance as user_balance
                        FROM withdrawal_requests wr
                        LEFT JOIN users u ON wr.user_id = u.user_id
                        WHERE wr.status = ?
                        ORDER BY wr.requested_at DESC
                        LIMIT ? OFFSET ?
                    ''', (status, limit, offset))
                
                rows = cursor.fetchall()
                withdrawals = []
                for row in rows:
                    withdrawal = dict(row)
                    # Convert decimals to float
                    if withdrawal.get('amount') is not None:
                        withdrawal['amount'] = float(withdrawal['amount'])
                    if withdrawal.get('user_balance') is not None:
                        withdrawal['user_balance'] = float(withdrawal['user_balance'])
                    withdrawals.append(withdrawal)
                
                conn.commit()
                return withdrawals
            finally:
                cursor.close()
        except Exception as e:
            logger.error(f"Error getting withdrawals: {e}")
            return []
    
    @classmethod
    async def get_user_withdrawal_requests(cls, user_id: int) -> List[Dict]:
        """Get user's withdrawal requests"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    SELECT * FROM withdrawal_requests 
                    WHERE user_id = ?
                    ORDER BY requested_at DESC
                """, (user_id,))
                rows = cursor.fetchall()
                
                requests = []
                for row in rows:
                    req = dict(row)
                    if req.get('amount') is not None:
                        req['amount'] = float(req['amount'])
                    requests.append(req)
                
                return requests
        except Exception as e:
            logger.error(f"Error getting user withdrawal requests: {e}")
            return []
    
    @classmethod
    async def get_pending_withdrawals(cls) -> List[Dict]:
        """Get all pending withdrawal requests"""
        return await cls.get_withdrawals(status='pending', limit=1000, offset=0)
    
    @classmethod
    async def approve_withdrawal(cls, withdrawal_id: int, admin_id: int) -> bool:
        """Approve a withdrawal request"""
        try:
            with cls.get_cursor() as cursor:
                # Get withdrawal details first
                cursor.execute("SELECT user_id, amount FROM withdrawal_requests WHERE id = ? AND status = 'pending'", 
                             (withdrawal_id,))
                result = cursor.fetchone()
                
                if not result or len(result) < 2:
                    return False
                
                user_id = result[0]
                amount = float(result[1])
                
                # Update withdrawal status
                cursor.execute('''
                    UPDATE withdrawal_requests 
                    SET status = 'approved', 
                        processed_by = ?,
                        processed_at = datetime('now'),
                        admin_notes = 'Withdrawal approved by admin'
                    WHERE id = ? AND status = 'pending'
                ''', (admin_id, withdrawal_id))
                
                if cursor.rowcount > 0:
                    # Record transaction for approved withdrawal
                    await cls.add_transaction(
                        user_id,
                        'withdrawal_approved',
                        -amount,
                        f"Withdrawal approved by admin {admin_id}",
                        None
                    )
                    
                    logger.info(f"Withdrawal {withdrawal_id} approved by admin {admin_id}")
                    return True
                
                return False
        except Exception as e:
            logger.error(f"Error approving withdrawal: {e}")
            return False
    
    @classmethod
    async def reject_withdrawal(cls, withdrawal_id: int, admin_id: int, reason: str = None) -> bool:
        """Reject a withdrawal request"""
        try:
            with cls.get_cursor() as cursor:
                # Get withdrawal details first
                cursor.execute("SELECT user_id, amount FROM withdrawal_requests WHERE id = ? AND status = 'pending'", 
                             (withdrawal_id,))
                result = cursor.fetchone()
                
                if not result or len(result) < 2:
                    return False
                
                user_id = result[0]
                amount = float(result[1])
                
                # Update withdrawal status
                cursor.execute('''
                    UPDATE withdrawal_requests 
                    SET status = 'rejected', 
                        processed_by = ?,
                        processed_at = datetime('now'),
                        admin_notes = ?
                    WHERE id = ? AND status = 'pending'
                ''', (admin_id, reason or 'Withdrawal rejected by admin', withdrawal_id))
                
                if cursor.rowcount > 0:
                    # Refund the amount back to user's balance
                    cursor.execute('''
                        UPDATE users 
                        SET balance = balance + ?
                        WHERE user_id = ?
                    ''', (amount, user_id))
                    
                    # Record transaction for the refund
                    await cls.add_transaction(
                        user_id,
                        'withdrawal_refund',
                        amount,
                        f"Withdrawal refunded: {reason or 'Withdrawal rejected'}",
                        None
                    )
                    
                    logger.info(f"Withdrawal {withdrawal_id} rejected by admin {admin_id}")
                    return True
                
                return False
        except Exception as e:
            logger.error(f"Error rejecting withdrawal: {e}")
            return False
    
    @classmethod
    async def process_withdrawal_request(cls, request_id: int, admin_id: int, 
                                         status: str = 'approved', notes: str = None) -> bool:
        """Process a withdrawal request - FIXED VERSION"""
        try:
            with cls.get_cursor() as cursor:
                # Get withdrawal details
                cursor.execute("""
                    SELECT user_id, amount, phone_number, method, payment_method 
                    FROM withdrawal_requests 
                    WHERE id = ? AND status = 'pending'
                """, (request_id,))
                result = cursor.fetchone()
                
                if not result or len(result) < 5:
                    return False
                
                user_id = result[0]
                amount = float(result[1])
                phone_number = result[2]
                method = result[3]
                payment_method = result[4] or method or 'tele_birr'
                
                # Update withdrawal status
                cursor.execute("""
                    UPDATE withdrawal_requests 
                    SET status = ?, 
                        admin_notes = ?, 
                        processed_by = ?, 
                        processed_at = datetime('now')
                    WHERE id = ?
                """, (status, notes, admin_id, request_id))
                
                if cursor.rowcount > 0:
                    if status == 'approved':
                        # Record transaction for approved withdrawal
                        await cls.add_transaction(
                            user_id,
                            'withdrawal_approved',
                            -amount,
                            f"Withdrawal approved via {payment_method} to {phone_number}"
                        )
                        
                        # Update user's total_withdrawals
                        cursor.execute("""
                            UPDATE users 
                            SET total_withdrawals = COALESCE(total_withdrawals, 0) + ?
                            WHERE user_id = ?
                        """, (amount, user_id))
                        
                        logger.info(f"Withdrawal {request_id} approved by admin {admin_id} for user {user_id}")
                    elif status == 'rejected':
                        # Refund amount back to user if rejected
                        cursor.execute("""
                            UPDATE users 
                            SET balance = balance + ? 
                            WHERE user_id = ?
                        """, (amount, user_id))
                        
                        # Record refund transaction
                        await cls.add_transaction(
                            user_id,
                            'withdrawal_refund',
                            amount,
                            f"Withdrawal rejected, refunded: {notes or 'Withdrawal rejected'}"
                        )
                        
                        logger.info(f"Withdrawal {request_id} rejected by admin {admin_id} for user {user_id}")
                    
                    return True
                
                return False
        except Exception as e:
            logger.error(f"Error processing withdrawal request: {e}")
            return False
    
    # ==================== PAYMENT METHODS ====================
    
    @classmethod
    async def create_payment_request(cls, user_id: int, amount: float, 
                                    payment_method: str, transaction_proof: str = None) -> int:
        """Create a payment request"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    INSERT INTO payments 
                    (user_id, amount, payment_method, status, transaction_id, admin_notes, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (user_id, amount, payment_method, 'pending', 
                     transaction_proof, 'Waiting for admin approval', datetime.now()))
                
                payment_id = cursor.lastrowid
                logger.info(f"Created payment request {payment_id} for user {user_id}, amount: {amount}")
                return payment_id
        except Exception as e:
            logger.error(f"Error creating payment request: {e}")
            return 0
    
    @classmethod
    async def get_pending_payments(cls) -> List[Dict]:
        """Get all pending payment requests"""
        return await cls.get_payments(status='pending', limit=1000, offset=0)
    
    @classmethod
    async def get_payments(cls, status: str = 'all', limit: int = 100, offset: int = 0) -> List[Dict]:
        """Get payments with optional status filter"""
        try:
            with cls.get_cursor() as cursor:
                if status == 'all':
                    cursor.execute("""
                        SELECT p.*, u.username, u.full_name, u.balance
                        FROM payments p
                        LEFT JOIN users u ON p.user_id = u.user_id
                        ORDER BY p.created_at DESC
                        LIMIT ? OFFSET ?
                    """, (limit, offset))
                else:
                    cursor.execute("""
                        SELECT p.*, u.username, u.full_name, u.balance
                        FROM payments p
                        LEFT JOIN users u ON p.user_id = u.user_id
                        WHERE p.status = ?
                        ORDER BY p.created_at DESC
                        LIMIT ? OFFSET ?
                    """, (status, limit, offset))
                
                rows = cursor.fetchall()
                payments = []
                for row in rows:
                    payment = dict(row)
                    if payment.get('amount') is not None:
                        payment['amount'] = float(payment['amount'])
                    if payment.get('balance') is not None:
                        payment['balance'] = float(payment['balance'])
                    payments.append(payment)
                
                return payments
        except Exception as e:
            logger.error(f"Error getting payments: {e}")
            return []
    
    @classmethod
    async def approve_payment(cls, payment_id: int, admin_id: str = 'system') -> bool:
        """Approve a payment"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    UPDATE payments 
                    SET status = 'approved', 
                        processed_by = ?,
                        processed_at = datetime('now'),
                        admin_notes = 'Payment approved by admin'
                    WHERE id = ? AND status = 'pending'
                """, (admin_id, payment_id))
                
                if cursor.rowcount > 0:
                    # Get payment details to update user balance
                    cursor.execute("SELECT user_id, amount FROM payments WHERE id = ?", (payment_id,))
                    result = cursor.fetchone()
                    
                    if result and len(result) >= 2:
                        user_id = result[0]
                        amount = float(result[1])
                        
                        # Add balance to user
                        await cls.add_transaction(
                            user_id,
                            'deposit',
                            amount,
                            f"Payment approved: ${amount:.2f}",
                            None
                        )
                    
                    logger.info(f"Payment {payment_id} approved by admin {admin_id}")
                    return True
                return False
        except Exception as e:
            logger.error(f"Error approving payment: {e}")
            return False
    
    @classmethod
    async def reject_payment(cls, payment_id: int, admin_id: str = 'system', reason: str = None) -> bool:
        """Reject a payment"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    UPDATE payments 
                    SET status = 'rejected', 
                        processed_by = ?,
                        processed_at = datetime('now'),
                        admin_notes = ?
                    WHERE id = ? AND status = 'pending'
                """, (admin_id, reason or 'Payment rejected by admin', payment_id))
                
                if cursor.rowcount > 0:
                    logger.info(f"Payment {payment_id} rejected by admin {admin_id}")
                    return True
                return False
        except Exception as e:
            logger.error(f"Error rejecting payment: {e}")
            return False
    
    # ==================== TELEBIRR TRANSACTIONS METHODS ====================
    
    @classmethod
    async def record_telebirr_transaction(cls, payment_id: int, user_id: int, 
                                         amount: float, transaction_id: str = None,
                                         sms_hash: str = None, status: str = 'pending',
                                         fraud_score: int = 0, admin_review: int = 0,
                                         api_response: str = None) -> int:
        """Record a Telebirr transaction for fraud detection - NEW METHOD with api_response"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    INSERT INTO telebirr_transactions 
                    (payment_id, user_id, amount, transaction_id, sms_hash,
                     status, fraud_score, admin_review, api_response, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (payment_id, user_id, amount, transaction_id, sms_hash,
                     status, fraud_score, admin_review, api_response, datetime.now()))
                
                tx_id = cursor.lastrowid
                logger.info(f"Recorded Telebirr transaction {tx_id} for payment {payment_id}")
                return tx_id
        except Exception as e:
            logger.error(f"Error recording Telebirr transaction: {e}")
            return 0
    
    @classmethod
    async def update_telebirr_transaction_status(cls, telebirr_tx_id: int, 
                                                 status: str, verified_at: datetime = None,
                                                 api_response: str = None) -> bool:
        """Update Telebirr transaction status - NEW METHOD"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    UPDATE telebirr_transactions 
                    SET status = ?, verified_at = ?, api_response = ?
                    WHERE id = ?
                """, (status, verified_at or datetime.now(), api_response, telebirr_tx_id))
                
                if cursor.rowcount > 0:
                    logger.info(f"Updated Telebirr transaction {telebirr_tx_id} to status: {status}")
                    return True
                return False
        except Exception as e:
            logger.error(f"Error updating Telebirr transaction status: {e}")
            return False
    
    @classmethod
    async def check_duplicate_sms_hash(cls, sms_hash: str) -> bool:
        """Check if SMS hash already exists - NEW METHOD"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    SELECT COUNT(*) as count FROM telebirr_transactions 
                    WHERE sms_hash = ? AND status != 'rejected'
                """, (sms_hash,))
                result = cursor.fetchone()
                return result and result[0] > 0
        except Exception as e:
            logger.error(f"Error checking duplicate SMS hash: {e}")
            return False
    
    @classmethod
    async def check_duplicate_transaction_id(cls, transaction_id: str) -> bool:
        """Check if transaction ID already exists - NEW METHOD"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    SELECT COUNT(*) as count FROM telebirr_transactions 
                    WHERE transaction_id = ? AND status = 'approved'
                """, (transaction_id,))
                result = cursor.fetchone()
                return result and result[0] > 0
        except Exception as e:
            logger.error(f"Error checking duplicate transaction ID: {e}")
            return False
    
    # ==================== FRAUD DETECTION METHODS ====================
    
    @classmethod
    async def update_user_fraud_detection(cls, user_id: int, suspicious_attempts: int = None,
                                         rejected_deposits: int = None, deposit_limit: float = None,
                                         daily_limit: float = None, restricted_until: datetime = None,
                                         notes: str = None) -> bool:
        """Update user fraud detection record - NEW METHOD"""
        try:
            with cls.get_cursor() as cursor:
                # Check if record exists
                cursor.execute("SELECT user_id FROM user_fraud_detection WHERE user_id = ?", (user_id,))
                exists = cursor.fetchone() is not None
                
                if exists:
                    # Update existing record
                    set_clauses = []
                    params = []
                    
                    if suspicious_attempts is not None:
                        set_clauses.append("suspicious_attempts = ?")
                        params.append(suspicious_attempts)
                    
                    if rejected_deposits is not None:
                        set_clauses.append("rejected_deposits = ?")
                        params.append(rejected_deposits)
                    
                    if deposit_limit is not None:
                        set_clauses.append("deposit_limit = ?")
                        params.append(deposit_limit)
                    
                    if daily_limit is not None:
                        set_clauses.append("daily_limit = ?")
                        params.append(daily_limit)
                    
                    if restricted_until is not None:
                        set_clauses.append("restricted_until = ?")
                        params.append(restricted_until)
                    
                    if notes is not None:
                        set_clauses.append("notes = ?")
                        params.append(notes)
                    
                    # Always update updated_at
                    set_clauses.append("updated_at = ?")
                    params.append(datetime.now())
                    
                    if set_clauses:
                        params.append(user_id)
                        query = f"UPDATE user_fraud_detection SET {', '.join(set_clauses)} WHERE user_id = ?"
                        cursor.execute(query, params)
                else:
                    # Insert new record
                    cursor.execute("""
                        INSERT INTO user_fraud_detection 
                        (user_id, suspicious_attempts, rejected_deposits, deposit_limit,
                         daily_limit, restricted_until, notes, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (user_id, suspicious_attempts or 0, rejected_deposits or 0,
                         deposit_limit or 1000.00, daily_limit or 5000.00,
                         restricted_until, notes, datetime.now(), datetime.now()))
                
                logger.info(f"Updated fraud detection for user {user_id}")
                return True
        except Exception as e:
            logger.error(f"Error updating user fraud detection: {e}")
            return False
    
    @classmethod
    async def get_user_fraud_detection(cls, user_id: int) -> Optional[Dict]:
        """Get user fraud detection record - NEW METHOD"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("SELECT * FROM user_fraud_detection WHERE user_id = ?", (user_id,))
                row = cursor.fetchone()
                
                if row:
                    fraud_data = dict(row)
                    # Convert decimals to float
                    for key in ['deposit_limit', 'daily_limit']:
                        if fraud_data.get(key) is not None:
                            fraud_data[key] = float(fraud_data[key])
                    
                    # Parse datetime
                    if fraud_data.get('restricted_until'):
                        try:
                            if isinstance(fraud_data['restricted_until'], str):
                                fraud_data['restricted_until'] = datetime.fromisoformat(fraud_data['restricted_until'])
                        except:
                            pass
                    
                    return fraud_data
                return None
        except Exception as e:
            logger.error(f"Error getting user fraud detection: {e}")
            return None
    
    @classmethod
    async def get_user_daily_deposits(cls, user_id: int) -> float:
        """Get user's total deposits for today - NEW METHOD"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    SELECT COALESCE(SUM(amount), 0) as daily_total
                    FROM payments 
                    WHERE user_id = ? 
                    AND status = 'approved'
                    AND DATE(created_at) = DATE('now')
                """, (user_id,))
                result = cursor.fetchone()
                return float(result[0]) if result and result[0] is not None else 0.00
        except Exception as e:
            logger.error(f"Error getting user daily deposits: {e}")
            return 0.00
    
    @classmethod
    async def get_user_successful_deposits_count(cls, user_id: int) -> int:
        """Get count of successful deposits for user - NEW METHOD"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    SELECT COUNT(*) as count FROM payments 
                    WHERE user_id = ? AND status = 'approved'
                """, (user_id,))
                result = cursor.fetchone()
                return result[0] if result and result[0] is not None else 0
        except Exception as e:
            logger.error(f"Error getting user successful deposits count: {e}")
            return 0
    
    # ==================== NOTIFICATION METHODS ====================
    
    @classmethod
    async def record_notification(cls, user_id: int = None, notification_type: str = "system",
                                  title: str = "", message: str = "") -> int:
        """Record a notification"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    INSERT INTO notifications (user_id, notification_type, title, message, created_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (user_id, notification_type, title, message, datetime.now()))
                
                return cursor.lastrowid
        except Exception as e:
            logger.error(f"Error recording notification: {e}")
            return 0
    
    # ==================== CLEANUP METHODS ====================
    
    @classmethod
    async def cleanup_old_games(cls, days_old: int = 30) -> int:
        """Clean up old completed games from database"""
        try:
            cutoff_date = datetime.now() - timedelta(days=days_old)
            
            with cls.get_cursor() as cursor:
                # Get old completed game IDs
                cursor.execute("""
                    SELECT game_id FROM games 
                    WHERE status = 'completed' 
                    AND completed_at < ?
                """, (cutoff_date,))
                old_games = cursor.fetchall()
                
                if not old_games:
                    return 0
                
                game_ids = [game[0] for game in old_games]
                cleaned_count = 0
                
                for game_id in game_ids:
                    # Delete related records
                    cursor.execute("DELETE FROM called_numbers WHERE game_id = ?", (game_id,))
                    cursor.execute("DELETE FROM drawn_numbers WHERE game_id = ?", (game_id,))
                    cursor.execute("DELETE FROM bingo_claims WHERE game_id = ?", (game_id,))
                    cursor.execute("DELETE FROM player_cards WHERE game_id = ?", (game_id,))
                    cursor.execute("DELETE FROM game_history WHERE game_id = ?", (game_id,))
                    cursor.execute("DELETE FROM commission_records WHERE game_id = ?", (game_id,))
                    
                    # Delete game
                    cursor.execute("DELETE FROM games WHERE game_id = ?", (game_id,))
                    
                    cleaned_count += 1
                
                logger.info(f"Cleaned up {cleaned_count} old games (older than {days_old} days)")
                return cleaned_count
                
        except Exception as e:
            logger.error(f"Error cleaning up old games: {e}")
            return 0
    
    @classmethod
    async def cleanup_orphaned_cards(cls) -> int:
        """Clean up orphaned cards (cards without games)"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    UPDATE player_cards 
                    SET is_active = 0
                    WHERE is_active = 1
                    AND NOT EXISTS (
                        SELECT 1 FROM games WHERE games.game_id = player_cards.game_id
                    )
                """)
                cleaned = cursor.rowcount
                if cleaned > 0:
                    logger.info(f"Cleaned up {cleaned} orphaned cards")
                return cleaned
                
        except Exception as e:
            logger.error(f"Error cleaning orphaned cards: {e}")
            return 0
    
    @classmethod
    async def archive_old_cards(cls, days_old: int = 7) -> int:
        """Archive old cards"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    UPDATE player_cards 
                    SET is_active = 0
                    WHERE purchase_time < datetime('now', ?)
                    AND is_active = 1
                """, (f'-{days_old} days',))
                archived = cursor.rowcount
                if archived > 0:
                    logger.info(f"Archived {archived} old cards")
                return archived
                
        except Exception as e:
            logger.error(f"Error archiving old cards: {e}")
            return 0
    
    # ==================== WINNER METHODS ====================
    
    @classmethod
    async def get_current_round_winners(cls, game_id: str) -> List[Dict]:
        """Get current round winners (cards with bingo)"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    SELECT pc.*, u.username, u.full_name 
                    FROM player_cards pc
                    LEFT JOIN users u ON pc.user_id = u.user_id
                    WHERE pc.game_id = ? AND pc.has_bingo = 1
                    ORDER BY pc.purchase_time ASC
                """, (game_id,))
                rows = cursor.fetchall()
                
                winners = []
                for row in rows:
                    winner = dict(row)
                    for key in ['prize_won', 'purchase_price']:
                        if winner.get(key) is not None:
                            winner[key] = float(winner[key])
                    
                    if winner.get('card_numbers'):
                        try:
                            winner['card_numbers'] = json.loads(winner['card_numbers'])
                        except:
                            winner['card_numbers'] = []
                    winners.append(winner)
                
                return winners
                
        except Exception as e:
            logger.error(f"Error getting current round winners: {e}")
            return []
    
    # ==================== BINGO CLAIM METHODS ====================
    
    @classmethod
    async def get_pending_bingo_claims(cls, game_id: str) -> List[Dict]:
        """Get pending bingo claims for a game"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    SELECT bc.*, u.username, u.full_name, pc.card_index, pc.card_numbers
                    FROM bingo_claims bc
                    LEFT JOIN users u ON bc.user_id = u.user_id
                    LEFT JOIN player_cards pc ON bc.card_id = pc.id
                    WHERE bc.game_id = ? AND bc.is_valid = 0
                    ORDER BY bc.claim_time ASC
                """, (game_id,))
                rows = cursor.fetchall()
                
                claims = []
                for row in rows:
                    claim = dict(row)
                    if claim.get('card_numbers'):
                        try:
                            claim['card_numbers'] = json.loads(claim['card_numbers'])
                        except:
                            claim['card_numbers'] = []
                    claims.append(claim)
                
                return claims
                
        except Exception as e:
            logger.error(f"Error getting pending bingo claims: {e}")
            return []
    
    @classmethod
    async def record_bingo_claim(cls, game_id: str, user_id: int, card_id: int,
                                is_valid: bool = False) -> int:
        """Record a bingo claim"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    INSERT INTO bingo_claims (
                        game_id, user_id, card_id, claim_time, is_valid
                    ) VALUES (?, ?, ?, ?, ?)
                """, (game_id, user_id, card_id, datetime.now(), 1 if is_valid else 0))
                
                return cursor.lastrowid
                
        except Exception as e:
            logger.error(f"Error recording bingo claim: {e}")
            return 0
    
    @classmethod
    async def verify_bingo_claim(cls, claim_id: int, is_valid: bool,
                                verified_by: str = "system", notes: str = None) -> bool:
        """Verify a bingo claim"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    UPDATE bingo_claims 
                    SET is_valid = ?, verified_by = ?, 
                        verification_time = datetime('now'), notes = ?
                    WHERE id = ?
                """, (1 if is_valid else 0, verified_by, notes, claim_id))
                
                return cursor.rowcount > 0
                
        except Exception as e:
            logger.error(f"Error verifying bingo claim: {e}")
            return False
    
    @classmethod
    async def reject_bingo_claim(cls, claim_id: int, reason: str) -> bool:
        """Reject a bingo claim"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    UPDATE bingo_claims 
                    SET is_valid = 0, notes = ?, verification_time = datetime('now')
                    WHERE id = ?
                """, (reason, claim_id))
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error rejecting bingo claim: {e}")
            return False
    
    @classmethod
    async def approve_bingo_claim(cls, claim_id: int, is_valid: bool) -> bool:
        """Approve a bingo claim"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    UPDATE bingo_claims 
                    SET is_valid = ?, verification_time = datetime('now')
                    WHERE id = ?
                """, (1 if is_valid else 0, claim_id))
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error approving bingo claim: {e}")
            return False
    
    @classmethod
    async def has_pending_bingo_claims(cls, game_id: str) -> bool:
        """Check if there are pending bingo claims for a game"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    SELECT COUNT(*) as count FROM bingo_claims 
                    WHERE game_id = ? AND is_valid = 0
                """, (game_id,))
                result = cursor.fetchone()
                return result and result[0] > 0
                
        except Exception as e:
            logger.error(f"Error checking pending bingo claims: {e}")
            return False
        
    @classmethod
    async def count_active_real_cards(cls, game_id: str) -> int:
        """Count number of active real cards in a game (excludes refunded)"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    SELECT COUNT(*) as count 
                    FROM player_cards 
                    WHERE game_id = ? AND is_fake = 0 AND is_active = 1
                """, (game_id,))
                result = cursor.fetchone()
                return result[0] if result and result[0] is not None else 0
        except Exception as e:
            logger.error(f"Error counting active real cards: {e}")
            return 0
    
  
     # ==================== CRITICAL FIX: CARD PURCHASE METHODS ====================
    
    @classmethod
    async def buy_card(cls, user_id: int, game_id: str, card_index: int) -> Dict[str, Any]:
         """
         Buy a card with full transaction handling, proper cursor management,
         and comprehensive error checking.
    
         Returns:
            Dict with success status, message, and updated data
         """
         # Create a new connection and cursor for this operation
         conn = None
         cursor = None
    
         try:
            conn = cls.get_connection()
            cursor = conn.cursor()
        
            # Start transaction
            cursor.execute("BEGIN TRANSACTION")
           
            # ===== STEP 1: Validate game exists and is in purchase phase =====
            cursor.execute("""
                SELECT status, round_number, card_price, prize_pool 
                FROM games 
                WHERE game_id = ?
            """, (game_id,))
           
            game = cursor.fetchone()
            if not game:
                cursor.execute("ROLLBACK")
                logger.error(f"Game {game_id} not found for user {user_id}")
                return {
                   'success': False, 
                    'message': 'Game not found',
                    'code': 'GAME_NOT_FOUND'
                }
          
            game_status, round_number, card_price, current_prize_pool = game
            card_price = float(card_price) if card_price else 10.00
          
            # Check game phase
            if game_status != 'card_purchase':
                cursor.execute("ROLLBACK")
                logger.warning(f"Game {game_id} is in {game_status} phase, not card_purchase")
                return {
                    'success': False, 
                    'message': f'Cannot buy cards during {game_status} phase',
                    'code': 'WRONG_PHASE',
                    'current_phase': game_status
                }
         
            # ===== STEP 2: Check if card index is valid =====
            if card_index < 1 or card_index > 400:
                cursor.execute("ROLLBACK")
                logger.error(f"Invalid card index {card_index} for game {game_id}")
                return {
                    'success': False, 
                    'message': f'Invalid card index {card_index}',
                    'code': 'INVALID_INDEX'
                }
         
            # ===== STEP 3: Check if card is already sold =====
            cursor.execute("""
                SELECT id, user_id FROM player_cards 
                WHERE game_id = ? AND card_index = ? AND is_active = 1
            """, (game_id, card_index))
         
            existing_card = cursor.fetchone()
            if existing_card:
                cursor.execute("ROLLBACK")
                logger.warning(f"Card {card_index} in game {game_id} is already sold to user {existing_card[1]}")
                return {
                    'success': False, 
                    'message': f'Card #{card_index} is already sold',
                    'code': 'CARD_SOLD',
                    'card_index': card_index
                }
           
            # ===== STEP 4: Check if user already has a card =====
            cursor.execute("""
                 SELECT id, card_index FROM player_cards 
                WHERE game_id = ? AND user_id = ? AND is_active = 1
            """, (game_id, user_id))
           
            user_card = cursor.fetchone()
            if user_card:
                cursor.execute("ROLLBACK")
                logger.info(f"User {user_id} already has card #{user_card[1]} in game {game_id}")
                return {
                    'success': False, 
                    'message': f'You already have card #{user_card[1]}',
                    'code': 'ALREADY_HAS_CARD',
                    'existing_card_index': user_card[1],
                    'existing_card_id': user_card[0]
                }
            
            # ===== STEP 5: Check user balance =====
            cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
            user = cursor.fetchone()
           
            if not user:
                cursor.execute("ROLLBACK")
                logger.error(f"User {user_id} not found")
                return {
                    'success': False, 
                    'message': 'User not found',
                    'code': 'USER_NOT_FOUND'
                }
          
            user_balance = float(user[0])
            if user_balance < card_price:
                cursor.execute("ROLLBACK")
                logger.warning(f"User {user_id} has insufficient balance: {user_balance} < {card_price}")
                return {
                    'success': False, 
                    'message': f'Insufficient balance. Need {card_price} birr, you have {user_balance:.2f} birr',
                    'code': 'INSUFFICIENT_BALANCE',
                    'required': card_price,
                    'available': user_balance
                }
          
            # ===== STEP 6: Generate card numbers =====
            card_numbers = cls._generate_bingo_numbers()
            
            # ===== STEP 7: Insert the card with ALL required fields =====
            now = datetime.now()
            card_numbers_json = json.dumps(card_numbers)
            
            # Card data with marked numbers array
            card_data = {
                'numbers': card_numbers,
                'grid': [card_numbers[i:i+5] for i in range(0, 25, 5)],
                'purchased_at': now.isoformat(),
                'marked_numbers': []
            }
            card_data_json = json.dumps(card_data)
            
            cursor.execute("""
                INSERT INTO player_cards (
                    game_id, user_id, card_index, card_numbers, 
                    card_data, purchase_price, purchase_time, 
                    created_at, is_active, is_fake,
                    has_bingo, prize_won
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                game_id, user_id, card_index, card_numbers_json,
                card_data_json, card_price, now,
                now, 1, 0,  # is_active=1, is_fake=0
                0, 0.00  # has_bingo=0, prize_won=0
            ))
            
            card_id = cursor.lastrowid
            
            # ===== STEP 8: Update game stats =====
            # Prize pool gets 80% of card price
            prize_pool_contribution = card_price * 0.8
            
            cursor.execute("""
                UPDATE games 
                SET total_cards_sold = total_cards_sold + 1,
                    prize_pool = prize_pool + ?,
                    total_sales = total_sales + ?,
                    real_cards_sold = real_cards_sold + 1,
                    total_players = (
                       SELECT COUNT(DISTINCT user_id) 
                       FROM player_cards 
                        WHERE game_id = ? AND is_active = 1 AND is_fake = 0
                    ),
                    updated_at = ?
                WHERE game_id = ?
             """, (prize_pool_contribution, card_price, game_id, now, game_id))
            
            # ===== STEP 9: Update user balance =====
            new_balance = user_balance - card_price
            
            cursor.execute("""
                UPDATE users 
                SET balance = ?,
                    total_games_played = total_games_played + 1,
                    updated_at = ?,
                    last_active = ?
                WHERE user_id = ?
            """, (new_balance, now, now, user_id))
            
            # ===== STEP 10: Create transaction record with ALL required fields =====
            cursor.execute("""
                INSERT INTO transactions (
                    user_id, amount, balance_after, transaction_type,
                    description, game_id, card_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                user_id, -card_price, new_balance, 'card_purchase',
                f'Purchased card #{card_index} in round {round_number}',
                game_id, card_id, now
            ))
            
            # ===== STEP 11: Get updated game stats =====
            cursor.execute("""
                SELECT 
                    prize_pool,
                     (SELECT COUNT(DISTINCT user_id) FROM player_cards 
                     WHERE game_id = ? AND is_active = 1 AND is_fake = 0) as real_players,
                    (SELECT COUNT(DISTINCT user_id) FROM player_cards 
                     WHERE game_id = ? AND is_active = 1 AND is_fake = 1) as fake_players,
                    total_cards_sold
                FROM games 
                WHERE game_id = ?
            """, (game_id, game_id, game_id))
            
            updated = cursor.fetchone()
           
            # Commit the transaction
            cursor.execute("COMMIT")
           
            logger.info(f"✅ User {user_id} successfully purchased card #{card_index} in game {game_id}")
         
            return {
                'success': True,
                'message': 'Card purchased successfully',
                'code': 'SUCCESS',
                'data': {
                    'card_id': card_id,
                    'card_index': card_index,
                    'card_numbers': card_numbers,
                    'new_balance': new_balance,
                    'prize_pool': float(updated[0]) if updated and updated[0] else current_prize_pool + prize_pool_contribution,
                    'real_players': updated[1] if updated else 0,
                    'fake_players': updated[2] if updated else 0,
                    'total_players': (updated[1] if updated else 0) + (updated[2] if updated else 0),
                    'total_cards_sold': updated[3] if updated else 0,
                    'round_number': round_number,
                    'purchase_time': now.isoformat()
                }
            }
            
         except Exception as e:
            # Rollback on any error
            if cursor:
                try:
                    cursor.execute("ROLLBACK")
                except:
                    pass
           
            logger.error(f"❌ Error in buy_card for user {user_id}, game {game_id}, card {card_index}: {e}", exc_info=True)
           
            return {
                'success': False,
                'message': f'Database error: {str(e)}',
                'code': 'DATABASE_ERROR',
                'error': str(e)
            }
        
         finally:
            # Always close cursor properly
            if cursor:
                try:
                    cursor.close()
                except:
                    pass
            
    @classmethod
    async def get_active_round_game(cls):
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    SELECT *
                    FROM games
                    WHERE status IN ('card_purchase','active','winner_display')
                    ORDER BY created_at DESC
                    LIMIT 1
                """)
                row = cursor.fetchone()

                if not row:
                    return None

                return dict(row)

        except Exception as e:
            logger.error(f"Error getting active round game: {e}")
            return None       
            
            
    @classmethod
    async def refund_card(cls, user_id: int, game_id: str, card_index: int) -> Dict[str, Any]:
        """
        Refund a card (80% of purchase price back to user)
        
        Returns:
            Dict with success status, message, and updated data
        """
        conn = None
        cursor = None
        
        try:
            conn = cls.get_connection()
            cursor = conn.cursor()
            
            # Start transaction
            cursor.execute("BEGIN TRANSACTION")
            
            # ===== STEP 1: Check if user owns this card =====
            cursor.execute("""
                SELECT pc.id, pc.purchase_price, g.card_price, g.round_number
                FROM player_cards pc
                JOIN games g ON pc.game_id = g.game_id
                WHERE pc.game_id = ? AND pc.user_id = ? AND pc.card_index = ? 
                  AND pc.is_active = 1
            """, (game_id, user_id, card_index))
            
            card = cursor.fetchone()
            if not card:
                cursor.execute("ROLLBACK")
                return {
                    'success': False,
                    'message': 'You do not own this card or it is not active',
                    'code': 'CARD_NOT_FOUND'
                }
            
            card_id = card[0]
            purchase_price = float(card[1])
            card_price = float(card[2]) if card[2] else 10.00
            round_number = card[3]
            
            # Refund amount (80% of purchase price)
            refund_amount = purchase_price * 0.8
            
            # ===== STEP 2: Deactivate the card =====
            now = datetime.now()
            cursor.execute("""
                UPDATE player_cards 
                SET is_active = 0, refunded_at = ? 
                WHERE id = ?
            """, (now, card_id))
            
            # ===== STEP 3: Update game stats =====
            cursor.execute("""
                UPDATE games 
                SET total_cards_sold = total_cards_sold - 1,
                    prize_pool = prize_pool - ?,
                    total_sales = total_sales - ?,
                    real_cards_sold = real_cards_sold - 1,
                    total_players = (
                        SELECT COUNT(DISTINCT user_id) 
                        FROM player_cards 
                        WHERE game_id = ? AND is_active = 1 AND is_fake = 0
                    ),
                    updated_at = ?
                WHERE game_id = ?
            """, (refund_amount, purchase_price, game_id, now, game_id))
            
            # ===== STEP 4: Refund user =====
            cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
            user = cursor.fetchone()
            current_balance = float(user[0]) if user else 0
            new_balance = current_balance + refund_amount
            
            cursor.execute("""
                UPDATE users 
                SET balance = ?,
                    total_games_played = total_games_played - 1,
                    updated_at = ?,
                    last_active = ?
                WHERE user_id = ?
            """, (new_balance, now, now, user_id))
            
            # ===== STEP 5: Create refund transaction =====
            cursor.execute("""
                INSERT INTO transactions (
                    user_id, amount, balance_after, transaction_type,
                    description, game_id, card_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                user_id, refund_amount, new_balance, 'refund',
                f'Refunded card #{card_index} in round {round_number}',
                game_id, card_id, now
            ))
            
            # ===== STEP 6: Get updated game stats =====
            cursor.execute("""
                SELECT 
                    prize_pool,
                    (SELECT COUNT(DISTINCT user_id) FROM player_cards 
                     WHERE game_id = ? AND is_active = 1 AND is_fake = 0) as real_players,
                    (SELECT COUNT(DISTINCT user_id) FROM player_cards 
                     WHERE game_id = ? AND is_active = 1 AND is_fake = 1) as fake_players,
                    total_cards_sold
                FROM games 
                WHERE game_id = ?
            """, (game_id, game_id, game_id))
            
            updated = cursor.fetchone()
            
            cursor.execute("COMMIT")
            
            logger.info(f"✅ User {user_id} successfully refunded card #{card_index} in game {game_id}")
            
            return {
                'success': True,
                'message': 'Card refunded successfully',
                'code': 'SUCCESS',
                'data': {
                    'new_balance': new_balance,
                    'refund_amount': refund_amount,
                    'prize_pool': float(updated[0]) if updated and updated[0] else 0,
                    'real_players': updated[1] if updated else 0,
                    'fake_players': updated[2] if updated else 0,
                    'total_players': (updated[1] if updated else 0) + (updated[2] if updated else 0),
                    'total_cards_sold': updated[3] if updated else 0,
                    'card_index': card_index,
                    'card_id': card_id
                }
            }
            
        except Exception as e:
            if cursor:
                try:
                    cursor.execute("ROLLBACK")
                except:
                    pass
            logger.error(f"❌ Error in refund_card: {e}", exc_info=True)
            return {
                'success': False,
                'message': f'Database error: {str(e)}',
                'code': 'DATABASE_ERROR'
            }
        finally:
            if cursor:
                try:
                    cursor.close()
                except:
                    pass

    @classmethod
    def _generate_bingo_numbers(cls) -> List[int]:
        """Generate a valid 5x5 bingo card (75 numbers, 25 spots)"""
        import random
        
        # Define ranges for each column
        ranges = [
            (1, 15),   # B
            (16, 30),  # I
            (31, 45),  # N
            (46, 60),  # G
            (61, 75)   # O
        ]
        
        card = []
        
        # Generate 5 numbers for each column
        for col_range in ranges:
            # Get 5 unique numbers from this range
            numbers = random.sample(range(col_range[0], col_range[1] + 1), 5)
            card.extend(numbers)
        
        # Mark the center as FREE (index 12 in flat array, row 3, col 3)
        card[12] = 0
        
        return card

    @classmethod
    async def can_user_buy_card(cls, game_id: str, user_id: int) -> Dict[str, Any]:
        """Enhanced check if user can buy a card in the current game"""
        try:
            with cls.get_cursor() as cursor:
                # Check if game exists and is in card purchase phase
                cursor.execute("""
                    SELECT status, purchase_end_time, round_number, card_price 
                    FROM games 
                    WHERE game_id = ?
                """, (game_id,))
                game_result = cursor.fetchone()
                
                if not game_result:
                    return {
                        'can_buy': False, 
                        'reason': 'Game not found',
                        'code': 'GAME_NOT_FOUND'
                    }
                
                status = game_result[0]
                purchase_end_time = game_result[1]
                round_number = game_result[2]
                card_price = float(game_result[3]) if game_result[3] else 10.00
                
                # Check game phase
                if status != 'card_purchase':
                    return {
                        'can_buy': False, 
                        'reason': f'Cannot buy cards during {status} phase',
                        'code': 'WRONG_PHASE',
                        'current_phase': status
                    }
                
                # Check purchase end time
                if purchase_end_time:
                    if isinstance(purchase_end_time, str):
                        try:
                            purchase_end = datetime.fromisoformat(purchase_end_time.replace('Z', '+00:00'))
                        except:
                            purchase_end = datetime.strptime(purchase_end_time, '%Y-%m-%d %H:%M:%S')
                    else:
                        purchase_end = purchase_end_time
                    
                    if purchase_end < datetime.now():
                        return {
                            'can_buy': False, 
                            'reason': 'Card purchase time has expired',
                            'code': 'TIME_EXPIRED'
                        }
                
                # Check if user already has an active card
                cursor.execute("""
                    SELECT COUNT(*) as count, card_index 
                    FROM player_cards 
                    WHERE game_id = ? AND user_id = ? AND is_active = 1
                """, (game_id, user_id))
                card_result = cursor.fetchone()
                
                if card_result and card_result[0] > 0:
                    return {
                        'can_buy': False, 
                        'reason': 'You already have a card in this round',
                        'code': 'ALREADY_HAS_CARD',
                        'existing_card_index': card_result[1]
                    }
                
                # Check user balance
                cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
                user_result = cursor.fetchone()
                
                if not user_result:
                    return {
                        'can_buy': False, 
                        'reason': 'User not found',
                        'code': 'USER_NOT_FOUND'
                    }
                
                balance = float(user_result[0]) if user_result[0] else 0.00
                
                if balance < card_price:
                    return {
                        'can_buy': False, 
                        'reason': f'Insufficient balance. Need {card_price} birr, you have {balance:.2f} birr',
                        'code': 'INSUFFICIENT_BALANCE',
                        'required': card_price,
                        'available': balance
                    }
                
                return {
                    'can_buy': True, 
                    'reason': '',
                    'code': 'OK',
                    'card_price': card_price,
                    'balance': balance,
                    'round_number': round_number
                }
                
        except Exception as e:
            logger.error(f"Error checking can user buy card: {e}")
            return {
                'can_buy': False, 
                'reason': 'Server error',
                'code': 'SERVER_ERROR',
                'error': str(e)
            }

    @classmethod
    async def get_available_cards(cls, game_id: str) -> Dict[str, Any]:
        """Get all available and sold cards for a game"""
        try:
            with cls.get_cursor() as cursor:
                # Get all active cards
                cursor.execute("""
                    SELECT card_index, user_id, is_fake 
                    FROM player_cards 
                    WHERE game_id = ? AND is_active = 1
                    ORDER BY card_index
                """, (game_id,))
                
                sold_cards = []
                sold_indices = []
                card_owners = {}
                
                for row in cursor.fetchall():
                    card_index = row[0]
                    user_id = row[1]
                    is_fake = row[2]
                    
                    sold_indices.append(card_index)
                    sold_cards.append({
                        'card_index': card_index,
                        'user_id': user_id,
                        'is_fake': bool(is_fake)
                    })
                    card_owners[str(card_index)] = user_id
                
                # Get user's card if any
                cursor.execute("""
                    SELECT user_id, card_index 
                    FROM player_cards 
                    WHERE game_id = ? AND is_active = 1
                """, (game_id,))
                
                user_cards = {}
                for row in cursor.fetchall():
                    user_cards[str(row[0])] = row[1]
                
                return {
                    'success': True,
                    'sold_cards': sold_indices,
                    'sold_cards_detail': sold_cards,
                    'user_cards': user_cards,
                    'card_owners': card_owners,
                    'total_sold': len(sold_indices)
                }
                
        except Exception as e:
            logger.error(f"Error getting available cards: {e}")
            return {
                'success': False,
                'message': str(e),
                'sold_cards': [],
                'sold_cards_detail': [],
                'user_cards': {},
                'card_owners': {},
                'total_sold': 0
            }

    @classmethod
    async def get_user_game_state(cls, user_id: int, game_id: str) -> Dict[str, Any]:
        """Get complete user state for a game"""
        try:
            with cls.get_cursor() as cursor:
                # Get user info
                cursor.execute("""
                    SELECT user_id, username, full_name, balance 
                    FROM users 
                    WHERE user_id = ?
                """, (user_id,))
                user = cursor.fetchone()
                
                if not user:
                    return {
                        'success': False,
                        'message': 'User not found',
                        'code': 'USER_NOT_FOUND'
                    }
                
                # Get user's card in this game
                cursor.execute("""
                    SELECT id, card_index, card_numbers, card_data, 
                           purchase_time, has_bingo, prize_won, purchase_price
                    FROM player_cards 
                    WHERE game_id = ? AND user_id = ? AND is_active = 1
                """, (game_id, user_id))
                
                card = cursor.fetchone()
                
                # Parse card data if exists
                card_data = None
                if card:
                    try:
                        card_numbers = json.loads(card[2]) if card[2] else []
                        card_data = {
                            'card_id': card[0],
                            'card_index': card[1],
                            'card_numbers': card_numbers,
                            'card_data': json.loads(card[3]) if card[3] else {},
                            'purchase_time': card[4].isoformat() if card[4] else None,
                            'has_bingo': bool(card[5]),
                            'prize_won': float(card[6]) if card[6] else 0,
                            'purchase_price': float(card[7]) if card[7] else 0
                        }
                    except:
                        card_data = None
                
                # Get game info
                cursor.execute("""
                    SELECT status, round_number, prize_pool, card_price,
                           (SELECT COUNT(DISTINCT user_id) FROM player_cards 
                            WHERE game_id = ? AND is_active = 1 AND is_fake = 0) as real_players,
                           (SELECT COUNT(DISTINCT user_id) FROM player_cards 
                            WHERE game_id = ? AND is_active = 1 AND is_fake = 1) as fake_players,
                           countdown_remaining
                    FROM games 
                    WHERE game_id = ?
                """, (game_id, game_id, game_id))
                
                game = cursor.fetchone()
                
                # Get called numbers
                cursor.execute("""
                    SELECT number FROM called_numbers 
                    WHERE game_id = ? 
                    ORDER BY called_at
                """, (game_id,))
                called = cursor.fetchall()
                called_numbers = [row[0] for row in called] if called else []
                
                # Get available cards
                available_cards = await cls.get_available_cards(game_id)
                
                return {
                    'success': True,
                    'user': {
                        'user_id': user[0],
                        'username': user[1],
                        'full_name': user[2],
                        'balance': float(user[3])
                    },
                    'has_card': card is not None,
                    'card': card_data,
                    'game': {
                        'status': game[0] if game else None,
                        'round_number': game[1] if game else 0,
                        'prize_pool': float(game[2]) if game and game[2] else 0,
                        'card_price': float(game[3]) if game and game[3] else 10.00,
                        'real_players': game[4] if game else 0,
                        'fake_players': game[5] if game else 0,
                        'total_players': (game[4] if game else 0) + (game[5] if game else 0),
                        'countdown_remaining': game[6] if game else 30
                    } if game else None,
                    'called_numbers': called_numbers,
                    'sold_cards': available_cards.get('sold_cards', []),
                    'sold_cards_detail': available_cards.get('sold_cards_detail', []),
                    'card_owners': available_cards.get('card_owners', {})
                }
                
        except Exception as e:
            logger.error(f"Error getting user game state: {e}")
            return {
                'success': False,
                'message': f'Database error: {str(e)}',
                'code': 'DATABASE_ERROR'
            }

    @classmethod
    async def ensure_card_purchase_tables(cls):
        """Ensure all tables have the required columns for card purchases"""
        try:
            with cls.get_cursor() as cursor:
                # Check player_cards table
                cursor.execute("PRAGMA table_info(player_cards)")
                columns = {col[1] for col in cursor.fetchall()}
                
                required_columns = {
                    'created_at': 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP',
                    'is_active': 'INTEGER DEFAULT 1',
                    'is_fake': 'INTEGER DEFAULT 0',
                    'has_bingo': 'INTEGER DEFAULT 0',
                    'prize_won': 'REAL DEFAULT 0.00',
                    'refunded_at': 'TIMESTAMP DEFAULT NULL'
                }
                
                for col_name, col_def in required_columns.items():
                    if col_name not in columns:
                        logger.info(f"Adding missing column {col_name} to player_cards")
                        cursor.execute(f"ALTER TABLE player_cards ADD COLUMN {col_name} {col_def}")
                
                # Check transactions table
                cursor.execute("PRAGMA table_info(transactions)")
                columns = {col[1] for col in cursor.fetchall()}
                
                tx_required = {
                    'created_at': 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP'
                }
                
                for col_name, col_def in tx_required.items():
                    if col_name not in columns:
                        logger.info(f"Adding missing column {col_name} to transactions")
                        cursor.execute(f"ALTER TABLE transactions ADD COLUMN {col_name} {col_def}")
                
                logger.info("✅ Database schema verified for card purchases")
                return True
                
        except Exception as e:
            logger.error(f"Error ensuring database schema: {e}")
            return False

    @classmethod
    async def debug_card_purchase(cls, user_id: int, game_id: str, card_index: int) -> Dict:
        """Debug method to check why card purchase is failing"""
        try:
            issues = []
            debug_info = {}
            
            with cls.get_cursor() as cursor:
                # Check game exists and phase
                cursor.execute("SELECT status, round_number, card_price FROM games WHERE game_id = ?", (game_id,))
                game = cursor.fetchone()
                if not game:
                    issues.append("Game not found")
                    debug_info['game_exists'] = False
                else:
                    debug_info['game_exists'] = True
                    debug_info['game_status'] = game[0]
                    debug_info['round_number'] = game[1]
                    debug_info['card_price'] = float(game[2]) if game[2] else 10.00
                    
                    if game[0] != 'card_purchase':
                        issues.append(f"Game phase is {game[0]}, not card_purchase")
                
                # Check if card is already sold
                cursor.execute("""
                    SELECT id, user_id FROM player_cards 
                    WHERE game_id = ? AND card_index = ? AND is_active = 1
                """, (game_id, card_index))
                existing = cursor.fetchone()
                if existing:
                    issues.append(f"Card {card_index} is already sold to user {existing[1]}")
                    debug_info['card_sold_to'] = existing[1]
                else:
                    debug_info['card_available'] = True
                
                # Check if user already has a card
                cursor.execute("""
                    SELECT id, card_index FROM player_cards 
                    WHERE game_id = ? AND user_id = ? AND is_active = 1
                """, (game_id, user_id))
                user_card = cursor.fetchone()
                if user_card:
                    issues.append(f"User already has card #{user_card[1]}")
                    debug_info['user_card_index'] = user_card[1]
                
                # Check user balance
                cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
                user = cursor.fetchone()
                if not user:
                    issues.append("User not found")
                    debug_info['user_exists'] = False
                else:
                    debug_info['user_exists'] = True
                    debug_info['user_balance'] = float(user[0])
                    card_price = debug_info.get('card_price', 10.00)
                    if float(user[0]) < card_price:
                        issues.append(f"Insufficient balance: {user[0]} birr, need {card_price} birr")
                
                # Check if card index is valid
                if card_index < 1 or card_index > 400:
                    issues.append(f"Invalid card index: {card_index}")
                
                # Check database connection
                debug_info['database_connected'] = True
                
            return {
                'user_id': user_id,
                'game_id': game_id,
                'card_index': card_index,
                'can_purchase': len(issues) == 0,
                'issues': issues,
                'debug_info': debug_info
            }
        except Exception as e:
            return {
                'error': str(e),
                'user_id': user_id,
                'game_id': game_id,
                'card_index': card_index,
                'can_purchase': False,
                'issues': [f'Exception: {str(e)}']
            }
    # ==================== UTILITY METHODS ====================
    
    @classmethod
    async def fetch_all(cls, query: str, params: tuple = ()) -> List[Dict]:
        """Execute query and fetch all results"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute(query, params)
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error executing fetch_all: {e}")
            return []
    
    @classmethod
    async def execute(cls, query: str, params: tuple = ()) -> bool:
        """Execute a query"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute(query, params)
                return True
        except Exception as e:
            logger.error(f"Error executing query: {e}")
            return False
    
    @classmethod
    async def close_connection(cls):
        """Close database connection"""
        if cls._conn:
            cls._conn.close()
            cls._conn = None
            logger.info("Database connection closed")
    
    @classmethod
    async def test_connection(cls):
        """Test database connection"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("SELECT 1")
                result = cursor.fetchone()
                return result is not None
        except Exception as e:
            logger.error(f"Database connection test failed: {e}")
            return False
    
    @classmethod
    def dict_factory(cls, cursor, row):
        """Convert SQLite row to dictionary"""
        d = {}
        for idx, col in enumerate(cursor.description):
            d[col[0]] = row[idx]
        return d