import sqlite3
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def fix_database():
    """Fix database schema issues"""
    try:
        conn = sqlite3.connect('habesha_bingo.db')
        cursor = conn.cursor()
        
        # Check withdrawal_requests table
        cursor.execute("PRAGMA table_info(withdrawal_requests)")
        columns = [col[1] for col in cursor.fetchall()]
        logger.info(f"Current withdrawal_requests columns: {columns}")
        
        # Add missing columns
        if 'phone_number' not in columns:
            cursor.execute("ALTER TABLE withdrawal_requests ADD COLUMN phone_number TEXT DEFAULT ''")
            logger.info("Added phone_number column")
        
        if 'method' not in columns:
            cursor.execute("ALTER TABLE withdrawal_requests ADD COLUMN method TEXT DEFAULT 'tele_birr'")
            logger.info("Added method column")
        
        if 'transaction_id' not in columns:
            cursor.execute("ALTER TABLE withdrawal_requests ADD COLUMN transaction_id INTEGER DEFAULT NULL")
            logger.info("Added transaction_id column")
        
        if 'requested_at' not in columns:
            cursor.execute("ALTER TABLE withdrawal_requests ADD COLUMN requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
            logger.info("Added requested_at column")
        
        if 'processed_by' not in columns:
            cursor.execute("ALTER TABLE withdrawal_requests ADD COLUMN processed_by INTEGER DEFAULT NULL")
            logger.info("Added processed_by column")
        
        conn.commit()
        conn.close()
        
        logger.info("✅ Database schema fixed successfully!")
        return True
        
    except Exception as e:
        logger.error(f"Error fixing database: {e}")
        return False

if __name__ == "__main__":
    fix_database()