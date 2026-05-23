# database/db.py - Simplified Database Schema
# Only: User registration, Deposit verification, Balance check
# All admin tables and methods removed

import sqlite3
import logging
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
    _db_path = os.path.join(os.getcwd(), os.getenv('DB_PATH', 'habesha_bingo.db'))
    _lock = asyncio.Lock() if 'asyncio' in dir() else None
    
    @classmethod
    def get_connection(cls):
        """Get or create database connection"""
        if cls._conn is None:
            try:
                db_path = cls._db_path
                db_dir = os.path.dirname(db_path)
                if db_dir:
                    os.makedirs(db_dir, exist_ok=True)
                
                cls._conn = sqlite3.connect(
                    db_path,
                    check_same_thread=False,
                    detect_types=sqlite3.PARSE_DECLTYPES
                )
                cls._conn.row_factory = sqlite3.Row
                cls._conn.execute("PRAGMA foreign_keys = ON")
                cls._conn.execute("PRAGMA journal_mode = WAL")
                
                logger.info(f"SQLite database connection created: {db_path}")
                cls._initialize_database()
                
            except Exception as e:
                logger.error(f"Failed to create database connection: {e}")
                raise
        return cls._conn
    
    @classmethod
    def _initialize_database(cls):
        """Initialize all database tables - SIMPLIFIED VERSION"""
        try:
            conn = cls.get_connection()
            cursor = conn.cursor()
            
            # 1. USERS TABLE - Basic user info and balance
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    full_name TEXT,
                    balance REAL DEFAULT 10.00,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_user_id ON users (user_id)")
            
            # 2. PAYMENTS TABLE - For deposit tracking
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
            
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_payments_user ON payments (user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_payments_status ON payments (status)")
            
            # 3. TELEBIRR_TRANSACTIONS TABLE - For verification tracking
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
                    verified_at TIMESTAMP DEFAULT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (payment_id) REFERENCES payments(id) ON DELETE CASCADE,
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
                )
            """)
            
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_telebirr_transactions_payment ON telebirr_transactions (payment_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_telebirr_transactions_user ON telebirr_transactions (user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_telebirr_transactions_txid ON telebirr_transactions (transaction_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_telebirr_transactions_sms_hash ON telebirr_transactions (sms_hash)")
            
            # 4. TRANSACTIONS TABLE - For balance history
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    amount REAL NOT NULL,
                    balance_after REAL NOT NULL,
                    transaction_type TEXT NOT NULL,
                    description TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
                )
            """)
            
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_transactions_user ON transactions (user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_transactions_created ON transactions (created_at)")
            
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
            return True
        except Exception as e:
            logger.error(f"Database initialization failed: {e}")
            return False
    
    @classmethod
    async def migrate_db(cls):
        """Run database migrations - SIMPLIFIED"""
        try:
            conn = cls.get_connection()
            cursor = conn.cursor()
            
            # Check if used_initial_balance column exists in users
            cursor.execute("PRAGMA table_info(users)")
            columns = [column[1] for column in cursor.fetchall()]
            
            if 'used_initial_balance' not in columns:
                logger.info("Adding used_initial_balance column to users table...")
                cursor.execute("ALTER TABLE users ADD COLUMN used_initial_balance INTEGER DEFAULT 0")
                conn.commit()
            
            logger.info("Database migrations completed successfully")
            
        except Exception as e:
            logger.error(f"Error running migrations: {e}")
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
    async def close_all_connections(cls):
        """Close database connection"""
        if cls._conn:
            cls._conn.close()
            cls._conn = None
            logger.info("Database connection closed")
    
    # ==================== USER MANAGEMENT METHODS ====================
    
    @classmethod
    async def create_user(cls, user_id: int, username: str = None, full_name: str = None) -> bool:
        """Create a new user with initial balance of 10 birr"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    INSERT OR REPLACE INTO users (
                        user_id, username, full_name, balance, 
                        created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))
                """, (user_id, username or f"User_{user_id}", full_name or f"User {user_id}", 10.00))
                
                # Log the initial balance transaction
                cursor.execute("""
                    INSERT INTO transactions (
                        user_id, amount, balance_after, transaction_type, description, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    user_id, 10.00, 10.00, 'initial_deposit', 
                    'Initial signup bonus', datetime.now()
                ))
                
                logger.info(f"Created new user {user_id} with initial balance 10.00")
                return True
                
        except Exception as e:
            logger.error(f"Error creating user: {e}")
            return False
    
    @classmethod
    async def get_user(cls, user_id: int) -> Optional[Dict]:
        """Get user by ID"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    SELECT user_id, username, full_name, balance, created_at, updated_at
                    FROM users 
                    WHERE user_id = ?
                """, (user_id,))
                
                row = cursor.fetchone()
                if not row:
                    logger.debug(f"User {user_id} not found")
                    return None
                
                user = dict(row)
                if user.get('balance') is not None:
                    user['balance'] = float(user['balance'])
                
                return user
                
        except Exception as e:
            logger.error(f"Error getting user {user_id}: {e}")
            return None
    
    @classmethod
    async def update_user_balance(cls, user_id: int, amount: float) -> bool:
        """Update user balance"""
        try:
            with cls.get_cursor() as cursor:
                if amount >= 0:
                    cursor.execute("""
                        UPDATE users SET balance = balance + ?, updated_at = datetime('now')
                        WHERE user_id = ?
                    """, (amount, user_id))
                else:
                    cursor.execute("""
                        UPDATE users 
                        SET balance = MAX(0, balance + ?), updated_at = datetime('now')
                        WHERE user_id = ?
                    """, (amount, user_id))
                
                return cursor.rowcount > 0
                
        except Exception as e:
            logger.error(f"Error updating user balance: {e}")
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
                    SET balance = balance + ?, updated_at = datetime('now')
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
                    notes or f"Balance added via {transaction_type}", 
                    datetime.now()
                ))
                
                logger.info(f"Added {amount} to user {user_id}, new balance: {new_balance}")
                return new_balance
        except Exception as e:
            logger.error(f"Error adding user balance: {e}")
            return 0.00
    
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
    async def get_payment(cls, payment_id: int) -> Optional[Dict]:
        """Get payment by ID"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    SELECT * FROM payments WHERE id = ?
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
    
    @classmethod
    async def get_pending_payments(cls) -> List[Dict]:
        """Get all pending payment requests"""
        try:
            with cls.get_cursor() as cursor:
                cursor.execute("""
                    SELECT p.*, u.username, u.full_name
                    FROM payments p
                    LEFT JOIN users u ON p.user_id = u.user_id
                    WHERE p.status = 'pending'
                    ORDER BY p.created_at DESC
                """)
                
                rows = cursor.fetchall()
                payments = []
                for row in rows:
                    payment = dict(row)
                    if payment.get('amount') is not None:
                        payment['amount'] = float(payment['amount'])
                    payments.append(payment)
                
                return payments
        except Exception as e:
            logger.error(f"Error getting pending payments: {e}")
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
                        admin_notes = 'Payment approved'
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
                        await cls.add_user_balance(
                            user_id,
                            amount,
                            'deposit',
                            f"Payment {payment_id} approved"
                        )
                    
                    logger.info(f"Payment {payment_id} approved")
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
                """, (admin_id, reason or 'Payment rejected', payment_id))
                
                if cursor.rowcount > 0:
                    logger.info(f"Payment {payment_id} rejected")
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
        """Record a Telebirr transaction for verification"""
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
        """Update Telebirr transaction status"""
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
        """Check if SMS hash already exists"""
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
        """Check if transaction ID already exists"""
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
    
    # ==================== TRANSACTION METHODS ====================
    
    @classmethod
    async def add_transaction(cls, user_id: int, transaction_type: str,
                              amount: float, description: str) -> int:
        """Add a transaction record"""
        try:
            with cls.get_cursor() as cursor:
                # Get current balance
                cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
                result = cursor.fetchone()
                current_balance = float(result[0]) if result and result[0] is not None else 0.00
                
                # Calculate new balance
                if transaction_type in ['deposit', 'initial_deposit', 'refund']:
                    new_balance = current_balance + amount
                elif transaction_type in ['withdrawal', 'purchase']:
                    new_balance = max(0, current_balance - abs(amount))
                else:
                    new_balance = current_balance + amount
                
                cursor.execute("""
                    INSERT INTO transactions 
                    (user_id, transaction_type, amount, balance_after, description, created_at)
                    VALUES (?, ?, ?, ?, ?, datetime('now'))
                """, (user_id, transaction_type, amount, new_balance, description))
                
                transaction_id = cursor.lastrowid
                logger.info(f"Added transaction {transaction_id} for user {user_id}: {transaction_type} {amount:.2f}")
                return transaction_id
              
        except Exception as e:
            logger.error(f"Error adding transaction for user {user_id}: {e}")
            return 0
    
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