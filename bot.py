#!/usr/bin/env python3
"""
Haset Bingo Bot - Simplified Version
Only: User Registration, Deposit with Verification, and Balance Check
No admin commands or functions
"""

import asyncio
import logging
import sys
import os
import signal
import time
import hashlib
import json
import re
import unicodedata
import aiohttp
import uuid
import gc
import shutil
import tempfile
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlencode

# ==================== FIX FOR WINDOWS CONSOLE ====================
if sys.platform == "win32":
    os.system('chcp 65001 > nul')
    
    class UnicodeStdout:
        def __init__(self, stream):
            self.stream = stream
            self.encoding = 'utf-8'
            
        def write(self, text):
            try:
                self.stream.write(text)
            except UnicodeEncodeError:
                text = text.encode('ascii', 'ignore').decode('ascii')
                self.stream.write(text)
                
        def flush(self):
            self.stream.flush()
    
    sys.stdout = UnicodeStdout(sys.stdout)
    sys.stderr = UnicodeStdout(sys.stderr)

# ==================== CUSTOM LOG HANDLER FOR WINDOWS ====================
class WindowsSafeLogHandler(logging.StreamHandler):
    def emit(self, record):
        try:
            msg = self.format(record)
            try:
                self.stream.write(msg + self.terminator)
            except UnicodeEncodeError:
                msg = msg.encode('ascii', 'ignore').decode('ascii')
                self.stream.write(msg + self.terminator)
            self.flush()
        except Exception:
            self.handleError(record)

# ==================== SETUP LOGGING ====================
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.handlers.clear()

formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

if sys.platform == "win32":
    handler = WindowsSafeLogHandler()
else:
    handler = logging.StreamHandler()

handler.setFormatter(formatter)
root_logger.addHandler(handler)

file_handler = logging.FileHandler('habesha_bingo.log', encoding='utf-8')
file_handler.setFormatter(formatter)
root_logger.addHandler(file_handler)

logger = logging.getLogger(__name__)

# ==================== GLOBAL VARIABLES ====================
shutting_down = False
aiohttp_session = None
main_task = None
enhanced_payment_validator = None
bot = None
dp = None

# ==================== PAYMENT CONFIGURATION ====================
PAYMENT_PHONE_NUMBER = "+251989929742"
PAYMENT_RECEIVER_NAME = "Nebiyu Asefa"
SUPPORT_TELEGRAM_USER = "@Hasetbingosupport"

# API URLs and keys (will be loaded from config)
TELEBIRR_VERIFICATION_API_URL = "http://verifyapi.leulzenebe.pro/verify-telebirr"
TELEBIRR_VERIFICATION_API_URL_2 = "https://www.verify.openmella.com.et/verify-telebirr"
TELEBIRR_API_KEY = ""

# ==================== API CLIENTS ====================
class TelebirrVerificationApiClient:
    """Client for Telebirr verification API with dual endpoint support"""
    
    def __init__(self, api_url: str = TELEBIRR_VERIFICATION_API_URL, api_key: str = ""):
        self.primary_api_url = api_url
        self.secondary_api_url = TELEBIRR_VERIFICATION_API_URL_2
        self.api_key = api_key
        self.timeout = 30
        self._session = None
        
    async def _ensure_session(self):
        """Ensure we have an aiohttp session"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout))
        
    async def close(self):
        """Close the aiohttp session"""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
    
    async def verify_transaction_primary(self, transaction_id: str):
        """Verify transaction through primary Telebirr verification API (POST method)"""
        if not transaction_id or transaction_id == "WITHDRAW":
            logger.error(f"Invalid transaction ID for Telebirr API: {transaction_id}")
            return None
            
        try:
            await self._ensure_session()
            logger.info(f"🔍 Calling primary Telebirr verification API (POST) for transaction: {transaction_id}")
            
            headers = {
                "Content-Type": "application/json",
                "x-api-key": self.api_key
            }
            
            payload = {
                "reference": transaction_id
            }
            
            async with self._session.post(self.primary_api_url, headers=headers, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    logger.info(f"✅ Primary Telebirr API response received. success: {data.get('success', False)}")
                    return self._process_response(data, transaction_id)
                else:
                    error_text = await response.text()
                    logger.error(f"Primary Telebirr API Error {response.status}: {error_text}")
                    return None
                    
        except asyncio.TimeoutError:
            logger.error(f"Timeout verifying transaction {transaction_id} via primary Telebirr API")
            return None
        except Exception as e:
            logger.error(f"Error calling primary Telebirr API for {transaction_id}: {e}")
            return None
    
    async def verify_transaction_secondary(self, transaction_id: str):
        """Verify transaction through secondary Telebirr verification API (GET method)"""
        if not transaction_id or transaction_id == "WITHDRAW":
            logger.error(f"Invalid transaction ID for secondary Telebirr API: {transaction_id}")
            return None
            
        try:
            await self._ensure_session()
            logger.info(f"🔍 Calling secondary Telebirr verification API (GET) for transaction: {transaction_id}")
            
            # Build GET URL with query parameters
            params = {"reference": transaction_id}
            url = f"{self.secondary_api_url}?{urlencode(params)}"
            
            headers = {
                "x-api-key": self.api_key
            }
            
            async with self._session.get(url, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    logger.info(f"✅ Secondary Telebirr API response received. success: {data.get('success', False)}")
                    return self._process_response(data, transaction_id)
                else:
                    error_text = await response.text()
                    logger.error(f"Secondary Telebirr API Error {response.status}: {error_text}")
                    return None
                    
        except asyncio.TimeoutError:
            logger.error(f"Timeout verifying transaction {transaction_id} via secondary Telebirr API")
            return None
        except Exception as e:
            logger.error(f"Error calling secondary Telebirr API for {transaction_id}: {e}")
            return None
    
    async def verify_transaction(self, transaction_id: str):
        """
        Verify transaction through Telebirr verification API with fallback
        First tries primary API (POST), if fails tries secondary API (GET)
        """
        if not transaction_id or transaction_id == "WITHDRAW":
            logger.error(f"Invalid transaction ID for Telebirr API: {transaction_id}")
            return None
        
        # Try primary API first
        result = await self.verify_transaction_primary(transaction_id)
        
        # If primary API succeeded, return result
        if result and result.get('success', False):
            logger.info(f"✅ Primary Telebirr API verification successful for {transaction_id}")
            return result
        
        # If primary API failed, try secondary API
        logger.info(f"⚠️ Primary Telebirr API failed, trying secondary API for {transaction_id}")
        result = await self.verify_transaction_secondary(transaction_id)
        
        if result and result.get('success', False):
            logger.info(f"✅ Secondary Telebirr API verification successful for {transaction_id}")
            return result
        
        # Both APIs failed
        logger.error(f"❌ Both Telebirr APIs failed for transaction {transaction_id}")
        return None
    
    def _process_response(self, api_data: dict, transaction_id: str):
        """Process API response for bot use"""
        if not api_data:
            return None
            
        success = api_data.get('success', False)
        data = api_data.get('data', {})
        
        # Extract amount from settledAmount
        amount = 0.0
        settled_amount_str = data.get('settledAmount', '')
        if settled_amount_str and settled_amount_str != 'N/A':
            match = re.search(r'(\d+(?:\.\d+)?)', settled_amount_str)
            if match:
                try:
                    amount = float(match.group(1))
                except ValueError:
                    amount = 0.0
        
        # Extract receiver info
        receiver_phone_raw = data.get('creditedPartyAccountNo', '')
        receiver_name = data.get('creditedPartyName', '')
        transaction_status = data.get('transactionStatus', '')
        
        # Check phone match
        phone_match = False
        if receiver_phone_raw and receiver_phone_raw != 'N/A':
            admin_digits = re.sub(r'[^\d]', '', PAYMENT_PHONE_NUMBER)
            
            if '****' in receiver_phone_raw:
                visible_parts = receiver_phone_raw.split('****')
                if len(visible_parts) == 2:
                    prefix = visible_parts[0]
                    suffix = visible_parts[1]
                    if admin_digits.startswith(prefix) and admin_digits.endswith(suffix):
                        phone_match = True
            else:
                receiver_digits = re.sub(r'[^\d]', '', receiver_phone_raw)
                if admin_digits[-9:] == receiver_digits[-9:]:
                    phone_match = True
        
        # Check name match
        name_match = False
        if receiver_name and receiver_name != 'N/A' and PAYMENT_RECEIVER_NAME:
            receiver_name_norm = ' '.join(receiver_name.lower().split())
            payment_name_norm = ' '.join(PAYMENT_RECEIVER_NAME.lower().split())
            
            if (payment_name_norm in receiver_name_norm or 
                receiver_name_norm in payment_name_norm):
                name_match = True
        
        result = {
            'success': success,
            'transaction_id': transaction_id,
            'amount': amount,
            'receiver_name': receiver_name,
            'receiver_phone_raw': receiver_phone_raw,
            'transaction_status': transaction_status,
            'phone_match': phone_match,
            'name_match': name_match,
            'transaction_verified': success and bool(data),
            'raw_data': api_data,
            'scraped_successfully': success and transaction_status == 'Completed'
        }
        
        result['is_valid'] = (
            result['success'] and
            result.get('amount', 0) > 0 and
            result.get('phone_match') == True and
            result.get('transaction_status') == 'Completed'
        )
        
        return result

class TelebirrScraper:
    """SMS scraper for Ethio telecom receipts"""
    
    def extract_transaction_id(self, sms_text: str):
        """Extract transaction ID from SMS"""
        if not sms_text or sms_text == "WITHDRAW":
            return None
            
        sms_text = sms_text.replace('\n', ' ').replace('\r', ' ')
        sms_text = ' '.join(sms_text.split())
        
        patterns = [
            r'transactioninfo\.ethiotelecom\.et/receipt/([A-Z0-9]+)',
            r'receipt/([A-Z0-9]+)',
            r'የሂሳብ\s*እንቅስቃሴ\s*ቁጥርዎ\s*([A-Z0-9]{8,12})\s*ነዉ',
            r'ቁጥርዎ\s*([A-Z0-9]{8,12})\s*ነዉ',
            r'transaction\s*(?:No|ID|#)?[:\s]*([A-Z0-9]{8,12})',
            r'TX\s*(?:No|ID|#)?[:\s]*([A-Z0-9]{8,12})',
            r'(\b[A-Z0-9]{8,12}\b)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, sms_text, re.IGNORECASE)
            if match:
                tx_id = match.group(1).strip().upper()
                if self.validate_transaction_id(tx_id):
                    return tx_id
        
        return None
    
    def validate_transaction_id(self, tx_id: str):
        if not tx_id or len(tx_id) < 8:
            return False
        if not re.match(r'^[A-Z0-9]+$', tx_id):
            return False
        if tx_id.isdigit():
            return False
        if not re.search(r'[A-Z]', tx_id):
            return False
        return True
    
    def extract_amount(self, sms_text: str):
        """Extract amount from SMS"""
        if not sms_text or sms_text == "WITHDRAW":
            return None
            
        sms_text = sms_text.replace('\n', ' ').replace('\r', ' ')
        sms_text = ' '.join(sms_text.split())
        
        amount_patterns = [
            r'([\d,]+\.?\d*)\s*ብር\s*ልከዋል',
            r'([\d,]+\.?\d*)\s*ብር',
            r'ETB\s*([\d,]+\.?\d*)',
            r'BIRR\s*([\d,]+\.?\d*)',
            r'Amount\s*[:\s]*([\d,]+\.?\d*)',
            r'([\d,]+\.\d{2})',
        ]
        
        for pattern in amount_patterns:
            matches = re.findall(pattern, sms_text, re.IGNORECASE)
            if matches:
                for match in matches:
                    if isinstance(match, tuple):
                        match = match[0]
                    try:
                        amount_str = str(match).replace(',', '')
                        amount_float = float(amount_str)
                        if 1 <= amount_float <= 100000:
                            return amount_float
                    except ValueError:
                        continue
        
        return None
    
    def extract_info_from_sms(self, sms_text: str):
        """Extract all info from SMS"""
        result = {
            'transaction_id': None,
            'amount': None,
            'extracted': False
        }
        
        if not sms_text or sms_text == "WITHDRAW":
            return result
            
        sms_text = sms_text.replace('\n', ' ').replace('\r', ' ')
        sms_text = ' '.join(sms_text.split())
        
        result['transaction_id'] = self.extract_transaction_id(sms_text)
        result['amount'] = self.extract_amount(sms_text)
        
        result['extracted'] = all([
            result['transaction_id'] is not None,
            result['amount'] is not None
        ])
        
        logger.info(f"Telebirr SMS Extraction Result: {result}")
        return result


# ==================== ENHANCED PAYMENT VALIDATOR ====================
class EnhancedPaymentValidator:
    """Enhanced validator with SMS parsing and API verification"""
    
    def __init__(self, admin_phone: str, admin_name: str = None):
        self.admin_phone = admin_phone
        self.admin_name = admin_name or PAYMENT_RECEIVER_NAME
        self.admin_phone_digits = re.sub(r'[^\d]', '', admin_phone)
        self.telebirr_scraper = TelebirrScraper()
        self.telebirr_client = None
        
        logger.info("✅ Payment verification API clients initialized")
    
    async def initialize_clients(self, telebirr_api_key: str = ""):
        """Initialize API clients with proper session management"""
        self.telebirr_client = TelebirrVerificationApiClient(
            api_url=TELEBIRR_VERIFICATION_API_URL,
            api_key=telebirr_api_key
        )
        
        if telebirr_api_key:
            await self.telebirr_client._ensure_session()
    
    async def close(self):
        """Close all API client sessions"""
        if self.telebirr_client:
            await self.telebirr_client.close()
    
    def calculate_sms_hash(self, sms_text: str) -> str:
        """Create unique hash of SMS to prevent reuse"""
        if not sms_text or sms_text == "WITHDRAW":
            return ""
            
        normalized = unicodedata.normalize('NFKC', sms_text.strip())
        normalized = re.sub(r'\s+', ' ', normalized)
        normalized = normalized.lower().strip()
        return hashlib.sha256(normalized.encode('utf-8')).hexdigest()[:32]
    
    def mask_phone_number(self, phone: str) -> str:
        """Mask phone number for privacy"""
        if not phone or phone == 'N/A':
            return "****"
        
        digits = re.sub(r'[^\d]', '', phone)
        
        if len(digits) >= 9:
            return f"+2519****{digits[-4:]}"
        elif len(digits) >= 4:
            return f"****{digits[-4:]}"
        else:
            return "****"
    
    async def check_duplicate_transaction(self, transaction_id: str, sms_hash: str = None, payment_method: str = None) -> bool:
        """Check if transaction has already been used before"""
        if not transaction_id or transaction_id == "WITHDRAW":
            return False
            
        try:
            from database.db import Database
            
            with Database.get_cursor() as cursor:
                cursor.execute("""
                    SELECT id FROM telebirr_transactions 
                    WHERE transaction_id = ? AND status IN ('approved', 'pending')
                    LIMIT 1
                """, (transaction_id,))
                result = cursor.fetchone()
                
                if result:
                    return True
                
                if sms_hash:
                    cursor.execute("""
                        SELECT id FROM telebirr_transactions 
                        WHERE sms_hash = ? AND status IN ('approved', 'pending')
                        LIMIT 1
                    """, (sms_hash,))
                    result = cursor.fetchone()
                    
                    if result:
                        return True
            
            return False
        except Exception as e:
            logger.error(f"Error checking duplicate transaction: {e}")
            return False
    
    async def verify_telebirr_transaction(self, sms_text: str):
        """Verify Telebirr transaction using dual API with fallback"""
        try:
            if not sms_text or sms_text == "WITHDRAW":
                return False, None, ["Invalid SMS text provided"]
                
            sms_info = self.telebirr_scraper.extract_info_from_sms(sms_text)
            
            if not sms_info['extracted']:
                tx_id = self.telebirr_scraper.extract_transaction_id(sms_text)
                if not tx_id:
                    return False, None, ["Failed to extract transaction ID from SMS"]
                
                sms_info['transaction_id'] = tx_id
                sms_info['extracted'] = True
            
            sms_hash = self.calculate_sms_hash(sms_text)
            is_duplicate = await self.check_duplicate_transaction(sms_info['transaction_id'], sms_hash, 'Telebirr')
            
            if is_duplicate:
                return False, None, ["This transaction has already been used"]
            
            if not self.telebirr_client:
                return False, None, ["Telebirr client not initialized"]
            
            api_result = await self.telebirr_client.verify_transaction(sms_info['transaction_id'])
            
            if not api_result:
                return False, None, ["Failed to verify transaction via Telebirr API (both endpoints failed)"]
            
            if not api_result.get('transaction_verified', False):
                return False, None, ["Transaction verification failed"]
            
            errors = []
            api_settled_amount = api_result.get('amount')
            
            if api_settled_amount is None or api_settled_amount <= 0:
                errors.append("No valid settled amount found in receipt")
            elif sms_info.get('amount'):
                sms_amount = sms_info['amount']
                max_allowed_difference = 2.0
                if abs(sms_amount - api_settled_amount) > max_allowed_difference:
                    errors.append(f"Amount mismatch (SMS: {sms_amount:.2f} vs API: {api_settled_amount:.2f})")
            
            if not api_result.get('is_valid', False):
                if not api_result.get('phone_match'):
                    errors.append(f"Payment phone not found in receipt. Expected: {PAYMENT_PHONE_NUMBER}")
                else:
                    errors.append("Transaction not valid")
            
            if api_result.get('transaction_status') != 'Completed':
                errors.append("Transaction status is not completed")
            
            if errors:
                return False, api_settled_amount, errors
            else:
                return True, api_settled_amount, []
            
        except Exception as e:
            logger.error(f"Telebirr verification error: {e}", exc_info=True)
            return False, None, [f"Verification error: {str(e)}"]


# ==================== SHUTDOWN HANDLERS ====================
async def enhanced_shutdown(restart: bool = False):
    """Enhanced clean shutdown with optional restart flag"""
    global shutting_down, main_task, enhanced_payment_validator
    if shutting_down:
        return
    
    shutting_down = True
    
    logger.info(f"Initiating enhanced shutdown...")
    
    try:
        # Cancel main task
        if main_task and not main_task.done():
            main_task.cancel()
            try:
                await main_task
            except asyncio.CancelledError:
                pass
        
        # Close payment validator clients
        if enhanced_payment_validator:
            if hasattr(enhanced_payment_validator, 'telebirr_client'):
                await enhanced_payment_validator.telebirr_client.close()
                logger.info("✅ Closed Telebirr API client")
        
        # Stop bot polling
        try:
            from aiogram import Bot, Dispatcher
            global dp, bot
            if dp:
                await dp.stop_polling()
                logger.info("Stopped bot polling")
            
            if bot and hasattr(bot, 'session'):
                await bot.session.close()
                logger.info("Closed bot session")
        except:
            pass
        
        # Close database connections
        try:
            from database.db import Database
            await Database.close_all_connections()
            logger.info("Closed all database connections")
        except Exception as e:
            logger.warning(f"Could not close database connections: {e}")
        
        # Cancel all other tasks
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        
        logger.info("✅ Enhanced shutdown complete")
        
    except Exception as e:
        logger.error(f"Error during enhanced shutdown: {e}")
    finally:
        await asyncio.sleep(1)
        os._exit(0)

def handle_signal(signum, frame):
    """Handle system signals"""
    logger.info(f"Received signal {signum}, shutting down...")
    asyncio.create_task(enhanced_shutdown())

# ==================== GLOBAL VARIABLES ====================
currency = None

# ==================== NOTIFICATION FUNCTIONS ====================
async def send_notification_to_user(user_id: int, message: str) -> bool:
    """Send a notification message to a user"""
    try:
        from web_server import notification_queue
        return notification_queue.add_notification(user_id, message)
    except Exception as e:
        logger.error(f"Error sending notification via queue: {e}")
        return False

async def notify_deposit_request_submitted(user_id: int, amount: float, payment_id: int):
    """Notify user that deposit request was submitted"""
    global currency
    message = (
        "*📋 የገንዘብ ክፍያ ጥያቄ ተላልፏል*\n\n"
        f"*ፒሜንት መታወቂያ:* {payment_id}\n"
        f"*መጠን:* {amount:.2f} {currency}\n"
        f"*ሁኔታ:* በአስተዳዳሪዎች ፍቃድ በመጠባበቅ ላይ\n\n"
        "✅ የገንዘብ ክፍያ ጥያቄዎ ለአስተዳዳሪዎቻችን ለማረጋገጥ ቀርቧል።\n"
        "📬 እንዲፈቀድለት ወይም እንዲተው ሲደረግ ማሳወቂያ ይደርስዎታል።\n\n"
        "ለትዕግስትዎ እናመሰግናለን! 🎮"
    )
    return await send_notification_to_user(user_id, message)

async def notify_deposit_approved(user_id: int, amount: float, payment_id: int):
    """Notify user that deposit was approved"""
    global currency
    from database.db import Database
    user = await Database.get_user(user_id)
    new_balance = user.get('balance', 0.00) if user else 0.00
    
    message = (
        "*✅ የገንዘብ ክፍያ ፈቅዷል!*\n\n"
        f"*💰 የፒሜንት መታወቂያ:* {payment_id}\n"
        f"*💵 መጠን:* {amount:.2f} {currency}\n"
        f"*🏦 አዲስ ቀሪ ሒሳብ:* {new_balance:.2f} {currency}\n\n"
        "🎉 እንኳን ደስ አሎት! የገንዘብ ክፍያዎ ተሰርቶ በቀሪ ሒሳብዎ ላይ ታክሏል።\n"
        "🎮 አሁን /balance ብለው አዲሱን ቀሪ ሒሳብዎ ለመመልከት ይችላሉ!\n\n"
        "Haset Bingo ስለመረጡዎ እናመሰግናለን! 🎯"
    )
    return await send_notification_to_user(user_id, message)

async def notify_auto_approved_deposit(user_id: int, amount: float, payment_id: int, transaction_id: str, payment_method: str):
    """Notify user that deposit was auto-approved"""
    global currency, enhanced_payment_validator
    from database.db import Database
    user = await Database.get_user(user_id)
    new_balance = user.get('balance', 0.00) if user else 0.00
    
    message = (
        f"✅ *{payment_method} ክፍያዎ በራስ-ሰር ፈቅዷል!*\n\n"
        f"💰 *መጠን:* {amount:.2f} {currency}\n"
        f"📋 *የፒሜንት መታወቂያ:* {payment_id}\n"
        f"🔢 *የግብይት መታወቂያ:* {transaction_id[:12]}...\n"
        f"🏦 *አዲስ ቀሪ ሒሳብ:* {new_balance:.2f} {currency}\n\n"
        f"🎉 ገንዘብዎ በቀሪ ሒሳብዎ ላይ ተጨምሯል!\n"
    )
    
    return await send_notification_to_user(user_id, message)

# ==================== PAYMENT DATABASE METHODS ====================
async def create_payment_request(user_id: int, amount: float, payment_method: str, transaction_proof: str = None) -> int:
    """Create a payment (deposit) request"""
    try:
        from database.db import Database
        
        user = await Database.get_user(user_id)
        if not user:
            logger.error(f"Cannot create payment request: User {user_id} does not exist")
            return 0
        
        with Database.get_cursor() as cursor:
            cursor.execute("PRAGMA foreign_keys=OFF")
            
            cursor.execute("""
                INSERT INTO payments 
                (user_id, amount, payment_method, status, transaction_id, admin_notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (user_id, amount, payment_method, 'pending', transaction_proof, 'Waiting for admin approval', datetime.now()))
            
            payment_id = cursor.lastrowid
            
            cursor.execute("PRAGMA foreign_keys=ON")
            
            logger.info(f"Payment request {payment_id} created for user {user_id}, amount {amount}")
            
            return payment_id
    except Exception as e:
        logger.error(f"Error creating payment request: {e}")
        return 0

async def approve_payment(payment_id: int) -> bool:
    """Approve a payment (deposit) request - auto approval"""
    try:
        from database.db import Database
        
        with Database.get_cursor() as cursor:
            cursor.execute("""
                SELECT p.* FROM payments p
                WHERE p.id = ? AND p.status = 'pending'
            """, (payment_id,))
            payment = cursor.fetchone()
            
            if not payment:
                return False
            
            payment_dict = dict(payment)
            user_id = payment_dict['user_id']
            amount = payment_dict['amount']
            
            cursor.execute("""
                UPDATE payments 
                SET status = 'approved', 
                    processed_at = ?,
                    processed_by = 0,
                    admin_notes = 'Auto-approved'
                WHERE id = ?
            """, (datetime.now(), payment_id))
            
            await Database.add_user_balance(user_id, amount, 'deposit', f'Payment approved: {payment_id}')
            
            logger.info(f"Payment {payment_id} approved for user {user_id}, amount {amount}")
            
            await notify_deposit_approved(user_id, amount, payment_id)
            
            return True
            
    except Exception as e:
        logger.error(f"Error approving payment: {e}")
        return False

async def auto_approve_deposit(user_id: int, payment_id: int, amount: float, transaction_id: str, sms_text: str, api_data: dict = None, payment_method: str = "Telebirr") -> bool:
    """Auto-approve deposit after successful verification"""
    from database.db import Database
    
    try:
        sms_hash = enhanced_payment_validator.calculate_sms_hash(sms_text) if enhanced_payment_validator else ""
        
        with Database.get_cursor() as cursor:
            cursor.execute("""
                UPDATE payments 
                SET status = 'approved',
                    amount = ?,
                    processed_at = ?,
                    processed_by = 0,
                    admin_notes = ?
                WHERE id = ? AND status = 'pending'
            """, (
                amount,
                datetime.now(),
                f"AUTO-APPROVED via {payment_method} API: TX ID: {transaction_id}",
                payment_id
            ))
            
            if cursor.rowcount == 0:
                logger.error(f"No pending payment found with ID {payment_id}")
                return False
            
            api_json = json.dumps(api_data) if api_data else "{}"
            
            try:
                cursor.execute("""
                    INSERT INTO telebirr_transactions 
                    (payment_id, user_id, amount, transaction_id, sms_hash,
                     status, fraud_score, admin_review, api_response, verified_at, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    payment_id,
                    user_id,
                    amount,
                    transaction_id,
                    sms_hash,
                    'approved',
                    0,
                    0,
                    api_json,
                    datetime.now(),
                    datetime.now()
                ))
            except Exception as db_error:
                logger.error(f"Failed to insert into telebirr_transactions: {db_error}")
            
            await Database.add_user_balance(user_id, amount, 'deposit', f'Auto-approved via {payment_method}: {payment_id}')
        
        await notify_auto_approved_deposit(user_id, amount, payment_id, transaction_id, payment_method)
        
        logger.info(f"Deposit auto-approved via {payment_method} API: user {user_id}, payment {payment_id}, amount {amount}")
        return True
        
    except Exception as e:
        logger.error(f"Error auto-approving deposit: {e}", exc_info=True)
        return False

# ==================== MAIN FUNCTION ====================
async def main():
    """Main application entry point"""
    global currency, enhanced_payment_validator, main_task, bot, dp
    
    if sys.platform != "win32":
        signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    
    logger.info("Starting Haset Bingo Bot - Simplified Version...")
    
    try:
        from config import BOT_TOKEN, GAME_CONFIG, WEBSERVER_HOST, WEBSERVER_PORT, WEB_APP_URL
    except ImportError as e:
        logger.error(f"Failed to import config: {e}")
        return
    
    try:
        TELEBIRR_API_KEY = GAME_CONFIG.get('telebirr_api_key', '')
        if not TELEBIRR_API_KEY:
            logger.warning("⚠️ Telebirr API key not found in config.")
    except:
        TELEBIRR_API_KEY = ''
        logger.warning("⚠️ API keys not configured.")
    
    currency = GAME_CONFIG.get('currency', 'birr')
    
    enhanced_payment_validator = EnhancedPaymentValidator(
        PAYMENT_PHONE_NUMBER,
        PAYMENT_RECEIVER_NAME
    )
    
    await enhanced_payment_validator.initialize_clients(TELEBIRR_API_KEY)
    
    banner = """
╔══════════════════════════════════════════════════════════════╗
║                    HASET BINGO BOT                         ║
║                   SIMPLIFIED VERSION                         ║
║              REGISTER | DEPOSIT | BALANCE                    ║
║           WITH TELEBIRR API INTEGRATION                      ║
╚══════════════════════════════════════════════════════════════╝
    """
    print(banner)
    
    print("\n" + "="*60)
    print("🎯 HASET BINGO - SIMPLIFIED EDITION 🎯")
    print("="*60)
    print(f"💰 Currency: {currency.upper()}")
    print(f"📱 Payment Phone: {PAYMENT_PHONE_NUMBER}")
    print(f"👤 Receiver Name: {PAYMENT_RECEIVER_NAME}")
    print(f"🆘 Support: {SUPPORT_TELEGRAM_USER}")
    print(f"🛡️ Fraud Prevention: ENABLED")
    print(f"🌐 Telebirr Primary API: {TELEBIRR_VERIFICATION_API_URL} (POST)")
    print(f"🌐 Telebirr Secondary API: {TELEBIRR_VERIFICATION_API_URL_2} (GET)")
    print(f"🔑 Telebirr API Key: {'Configured' if TELEBIRR_API_KEY else 'Not Configured'}")
    print("="*60)
    
    from aiogram import Bot, Dispatcher, types
    from aiogram.contrib.fsm_storage.memory import MemoryStorage
    from aiogram.types import ParseMode
    from aiogram.dispatcher import FSMContext
    from aiogram.dispatcher.filters.state import State, StatesGroup
    from aiogram.dispatcher.filters import Command
    
    bot = Bot(token=BOT_TOKEN)
    
    # Initialize notification queue
    try:
        from web_server import notification_queue, set_bot_instance
        loop = asyncio.get_running_loop()
        notification_queue.set_bot(bot, loop)
        notification_queue.start(loop)
        set_bot_instance(bot)
        logger.info("✅ Registered bot with notification queue and web_server")
    except Exception as e:
        logger.error(f"❌ Failed to initialize notification queue: {e}")
    
    storage = MemoryStorage()
    dp = Dispatcher(bot, storage=storage)
    
    # Command States
    class DepositStates(StatesGroup):
        waiting_for_payment_method = State()
        waiting_for_transaction_proof = State()
    
    seen_start_users = set()
    
    # ==================== COMMAND HANDLERS ====================
    
    @dp.message_handler(Command("start"))
    async def cmd_start_enhanced(message: types.Message):
        user_id = message.from_user.id
        first_name = message.from_user.first_name or "ተጠቃሚ"
        
        from database.db import Database
        
        user = await Database.get_user(user_id)
        if not user:
            success = await Database.create_user(
                user_id=user_id,
                username=message.from_user.username or "",
                full_name=message.from_user.full_name or ""
            )
            if success:
                user_exists = False
            else:
                await message.answer("❌ ተጠቃሚ ለመፍጠር አልተቻለም። እባክዎ እንደገና ይሞክሩ።")
                return
        else:
            user_exists = True
        
        seen_start_users.add(user_id)
        
        if not user_exists:
            welcome_message = f"""
✨✨ *እንኳን ደህና መጡ {first_name}!* ✨✨

🎉 *ወደ Haset Bingo በደህና መጡ!* 🎉

✅ *መዝግብዎ ተሳክቷል!* 
💰 *የመጀመሪያ ስጦታዎ*: 10 {currency} ነፃ ቀሪ ሒሳብ ተሰጥቶዎታል!

📊 *ቀሪ ሒሳብዎን ለማየት*: /balance
💰 *ገንዘብ ለማስገባት*: /deposit
📖 *ህጎች ለማወቅ*: /instructions
🆘 *እርዳታ ለማግኘት*: /support

{f"💬 *ድጋፍ*: {SUPPORT_TELEGRAM_USER}" if SUPPORT_TELEGRAM_USER else ""}
            """
        else:
            welcome_message = f"""
✨✨ *እንኳን ተመለሱ {first_name}!* ✨✨

🎮 *Haset Bingo እንደገና አርበዎታል!* 🎮

🚀 *ፈጣን ትእዛዞች*:
• /balance - ቀሪ ሒሳብዎን ይመልከቱ
• /deposit - ገንዘብ ያስገቡ

{f"💬 *ድጋፍ*: {SUPPORT_TELEGRAM_USER}" if SUPPORT_TELEGRAM_USER else ""}
            """
        
        await message.answer(welcome_message, parse_mode=ParseMode.MARKDOWN)
    
    # ==================== DEPOSIT SECTION ====================
    
    @dp.message_handler(Command("deposit"))
    async def cmd_deposit_enhanced(message: types.Message, state: FSMContext):
        """Start deposit process with 3 attempts limit"""
        user_id = message.from_user.id
        
        keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, selective=True)
        keyboard.add("ቴሌ ብር")
        keyboard.add("Cancel")
        
        await message.answer(
            "💵 *የገንዘብ ክፍያ ሂደት*\n\n"
            "💳 እባክዎ የክፍያ ዘዴዎን ይምረጡ፡\n"
            "ገንዘብ ለማስገባት ቴሌብር ብቻ ይጠቀሙ።\n\n"
            "❌ *ለማቋረጥ*: 'Cancel' ቁልፉን ይጫኑ",
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN
        )
        
        await DepositStates.waiting_for_payment_method.set()
    
    @dp.message_handler(state=DepositStates.waiting_for_payment_method)
    async def process_deposit_method_enhanced(message: types.Message, state: FSMContext):
        """Handle payment method selection"""
        user_id = message.from_user.id
        
        if message.text and message.text.strip() == 'Cancel':
            await state.finish()
            await message.answer("❌ የገንዘብ ክፍያ ሂደት ተቋርጧል።", reply_markup=types.ReplyKeyboardRemove())
            return
        
        payment_method = message.text
        valid_methods = ["ቴሌ ብር"]
        
        if payment_method not in valid_methods:
            keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, selective=True)
            keyboard.add("ቴሌ ብር")
            keyboard.add("Cancel")
            
            await message.answer(
                "⚠️ እባክዎ ትክክለኛ የክፍያ ዘዴ ይምረጡ፡\n"
                "• ቴሌ ብር\n\n"
                "❌ *ለማቋረጥ*: 'Cancel' ቁልፉን ይጫኑ",
                reply_markup=keyboard
            )
            return
        
        payment_id = await create_payment_request(user_id, 0.00, payment_method, None)
        
        if not payment_id:
            await state.finish()
            await message.answer("❌ የፒሜንት ጥያቄ ለመፍጠር አልተቻለም። እባክዎ እንደገና ይሞክሩ።", reply_markup=types.ReplyKeyboardRemove())
            return
        
        await state.update_data(
            payment_id=payment_id,
            payment_method=payment_method,
            verification_attempts=0
        )
        
        masked_admin_phone = enhanced_payment_validator.mask_phone_number(PAYMENT_PHONE_NUMBER) if enhanced_payment_validator else PAYMENT_PHONE_NUMBER
        
        instructions = f"💳 *የቴሌብር ክፍያ መመሪያዎች*\n\n"
        instructions += f"🏦 ዘዴ: {payment_method}\n"
        instructions += f"📋 የፒሜንት መታወቂያ: {payment_id}\n\n"
        instructions += f"1️⃣ ቴሌብር አፕዎን ይክፈቱ\n"
        instructions += f"2️⃣ የሚፈልጉትን መጠን ወደዚህ ይላኩ፡\n"
        instructions += f"   📱 ስልክ: {PAYMENT_PHONE_NUMBER}\n"
        instructions += f"   👤 ስም: {PAYMENT_RECEIVER_NAME}\n\n"
        instructions += f"3️⃣ ከላኩ በኋላ፣ የማረጋገጫ መልእክት ይደርስዎታል\n"
        instructions += f"4️⃣ አጠቃላይ የግብይት መልእክቱን *COPY* ያድርጉ\n"
        instructions += f"5️⃣ እዚህ በቻት ውስጥ *PASTE* ያድርጉት\n\n"
        instructions += f"🔍 *ማስታወሻ:* ስርዓታችን በራስ-ሰር የግብይት መረጃዎን ያረጋግጣል!\n\n"
        instructions += f"❌ *ለማቋረጥ*: 'Cancel' ቁልፉን ይጫኑ"
        
        await message.answer(instructions, reply_markup=types.ReplyKeyboardRemove(), parse_mode=ParseMode.MARKDOWN)
        
        cancel_keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, selective=True)
        cancel_keyboard.add("Cancel")
        
        await message.answer(
            "📋 እባክዎ የግብይት ማረጋገጫዎን መልእክት ከላይ እንደተገለጸው ይላኩ።\n\n"
            "❌ *ለማቋረጥ*: 'Cancel' ቁልፉን ይጫኑ",
            reply_markup=cancel_keyboard
        )
        
        await DepositStates.waiting_for_transaction_proof.set()
    
    @dp.message_handler(state=DepositStates.waiting_for_transaction_proof)
    async def process_payment_sms_enhanced(message: types.Message, state: FSMContext):
        """Process SMS with 3 attempts limit"""
        user_id = message.from_user.id
        
        if message.text and message.text.strip() == 'Cancel':
            await state.finish()
            await message.answer("❌ የገንዘብ ክፍያ ሂደት ተቋርጧል።", reply_markup=types.ReplyKeyboardRemove())
            return
        
        data = await state.get_data()
        payment_id = data.get('payment_id')
        attempts = data.get('verification_attempts', 0)
        
        if not payment_id:
            await state.finish()
            await message.answer("❌ የፒሜንት መረጃ አልተገኘም። እንደገና ይሞክሩ።", reply_markup=types.ReplyKeyboardRemove())
            return
        
        if not message.text or message.text.strip() == "" or message.text.strip() == "WITHDRAW" or message.text.startswith('/'):
            attempts += 1
            await state.update_data(verification_attempts=attempts)
            
            if attempts >= 3:
                from database.db import Database
                with Database.get_cursor() as cursor:
                    cursor.execute("""
                        UPDATE payments 
                        SET status = 'rejected',
                            processed_at = ?,
                            processed_by = 0,
                            admin_notes = ?
                        WHERE id = ?
                    """, (
                        datetime.now(),
                        f"Auto-rejected: 3 failed attempts - invalid SMS format",
                        payment_id
                    ))
                
                await state.finish()
                
                await message.answer(
                    "🚨 *3 ጊዜ ሙከራ አልተሳካም!*\n\n"
                    "❌ የገንዘብ ክፍያ ጥያቄዎ ተቋርጧል።\n\n"
                    "📞 እባክዎ ድጋፍ ያግኙ: /support\n\n"
                    "💳 አዲስ ክፍያ ለመጠየቅ: /deposit",
                    reply_markup=types.ReplyKeyboardRemove(),
                    parse_mode=ParseMode.MARKDOWN
                )
                return
            
            cancel_keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, selective=True)
            cancel_keyboard.add("Cancel")
            
            await message.answer(
                f"❌ *ልክ ያልሆነ የክፍያ ማረጋገጫ!*\n\n"
                f"⚠️ እባክዎ እውነተኛ የቴሌብር ማረጋገጫ SMS ይላኩ።\n"
                f"🔁 *ሙከራ {attempts}/3*\n\n"
                f"❌ *ለማቋረጥ*: 'Cancel' ቁልፉን ይጫኑ",
                reply_markup=cancel_keyboard,
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        await process_telebirr_transaction_enhanced(user_id, payment_id, message, state, attempts)
    
    async def process_telebirr_transaction_enhanced(user_id: int, payment_id: int, message: types.Message, state: FSMContext, attempts: int):
        """Verify Telebirr transaction with 3 attempts limit"""
        
        tx_id = enhanced_payment_validator.telebirr_scraper.extract_transaction_id(message.text)
        
        if not tx_id:
            attempts += 1
            await state.update_data(verification_attempts=attempts)
            
            if attempts >= 3:
                from database.db import Database
                with Database.get_cursor() as cursor:
                    cursor.execute("""
                        UPDATE payments 
                        SET status = 'rejected',
                            processed_at = ?,
                            processed_by = 0,
                            admin_notes = ?
                        WHERE id = ?
                    """, (
                        datetime.now(),
                        f"Auto-rejected: 3 failed attempts - could not extract transaction ID",
                        payment_id
                    ))
                
                await state.finish()
                
                await message.answer(
                    "🚨 *3 ጊዜ ሙከራ አልተሳካም!*\n\n"
                    "❌ የግብይት መታወቂያ ማግኘት አልተቻለም።\n"
                    "የገንዘብ ክፍያ ጥያቄዎ ተቋርጧል።\n\n"
                    "📞 እባክዎ ድጋፍ ያግኙ: /support\n"
                    "💳 አዲስ ክፍያ ለመጠየቅ: /deposit",
                    reply_markup=types.ReplyKeyboardRemove(),
                    parse_mode=ParseMode.MARKDOWN
                )
                return
            
            cancel_keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, selective=True)
            cancel_keyboard.add("Cancel")
            
            await message.answer(
                f"❌ *የግብይት መታወቂያ ማግኘት አልተቻለም!*\n\n"
                f"⚠️ እባክዎ እውነተኛ የቴሌብር ማረጋገጫ SMS ይላኩ።\n"
                f"🔁 *ሙከራ {attempts}/3*\n\n"
                f"❌ *ለማቋረጥ*: 'Cancel' ቁልፉን ይጫኑ",
                reply_markup=cancel_keyboard,
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        if not TELEBIRR_API_KEY:
            await state.finish()
            from database.db import Database
            with Database.get_cursor() as cursor:
                cursor.execute("""
                    UPDATE payments 
                    SET amount = 0.00,
                        transaction_id = ?,
                        admin_notes = ?
                    WHERE id = ?
                """, (message.text[:500], "Pending manual verification (API key not configured)", payment_id))
            
            await notify_deposit_request_submitted(user_id, 0.00, payment_id)
            await message.answer(
                "⏳ *የገንዘብ ክፍያ ጥያቄ ተላልፏል!*\n\n"
                "🔧 ስርዓታችን በአሁኑ ጊዜ አውቶማቲክ ማረጋገጫ አይሰራም።\n"
                "👨‍💼 አስተዳዳሪዎች ጥያቄዎን በቅርቡ ያረጋግጣሉ።\n\n"
                "📬 እንዲፈቀድለት ወይም እንዲተው ሲደረግ ማሳወቂያ ይደርስዎታል።",
                reply_markup=types.ReplyKeyboardRemove()
            )
            return
        
        await message.answer(
            "🔍 *የቴሌብር ግብይት ማረጋገጫ በመስራት ላይ...*\n\n"
            f"📋 የፒሜንት መታወቂያ: {payment_id}\n"
            f"🔢 የግብይት መታወቂያ: {tx_id}\n\n"
            "⏳ እባክዎን ይጠበቁ፣ ይህ ጥቂት ሰከንዶች ሊወስድ ይችላል...",
            parse_mode=ParseMode.MARKDOWN
        )
        
        verified, amount, errors = await enhanced_payment_validator.verify_telebirr_transaction(message.text)
        
        api_result = None
        if verified and enhanced_payment_validator.telebirr_client:
            api_result = await enhanced_payment_validator.telebirr_client.verify_transaction(tx_id)
        
        from database.db import Database
        with Database.get_cursor() as cursor:
            cursor.execute("""
                UPDATE payments 
                SET amount = ?,
                    transaction_id = ?,
                    admin_notes = ?
                WHERE id = ?
            """, (amount if amount else 0.00, message.text[:500], f"Telebirr API: {'Success' if verified else 'Failed'}", payment_id))
        
        if not verified:
            attempts += 1
            await state.update_data(verification_attempts=attempts)
            
            if attempts >= 3:
                with Database.get_cursor() as cursor:
                    cursor.execute("""
                        UPDATE payments 
                        SET status = 'rejected',
                            processed_at = ?,
                            processed_by = 0,
                            admin_notes = ?
                        WHERE id = ?
                    """, (
                        datetime.now(),
                        f"Auto-rejected: 3 failed verification attempts: {', '.join(errors[:2]) if errors else 'Verification failed'}",
                        payment_id
                    ))
                
                await state.finish()
                
                error_list = "\n".join([f"• {err}" for err in errors[:3]]) if errors else "• Verification failed"
                
                await message.answer(
                    f"🚨 *3 ጊዜ ሙከራ አልተሳካም!*\n\n"
                    f"❌ የቴሌብር ክፍያ ማረጋገጫ አልተሳካም።\n\n"
                    f"📝 *ምክንያቶች:*\n{error_list}\n\n"
                    f"📞 እባክዎ ድጋፍ ያግኙ: /support\n"
                    f"💳 አዲስ ክፍያ ለመጠየቅ: /deposit",
                    reply_markup=types.ReplyKeyboardRemove(),
                    parse_mode=ParseMode.MARKDOWN
                )
                return
            
            cancel_keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, selective=True)
            cancel_keyboard.add("Cancel")
            
            error_message = f"❌ *ማረጋገጫ አልተሳካም!*\n\n"
            
            if errors:
                error_message += f"📝 *ምክንያቶች:*\n"
                for error in errors[:2]:
                    error_message += f"• {error}\n"
                error_message += "\n"
            
            error_message += f"🔁 *ሙከራ {attempts}/3*\n\n"
            error_message += f"❌ *ለማቋረጥ*: 'Cancel' ቁልፉን ይጫኑ"
            
            await message.answer(
                error_message,
                reply_markup=cancel_keyboard,
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # Verification successful - auto-approve
        success = await auto_approve_deposit(
            user_id, payment_id, amount, tx_id, message.text, api_result, "Telebirr"
        )
        
        await state.finish()
        
        if success:
            await message.answer(
                "🎉 *ቴሌብር ክፍያዎ በራስ-ሰር ፈቅዷል!*\n\n"
                f"✅ ገንዘብዎ በቀሪ ሒሳብዎ ላይ ተጨምሯል!\n"
                f"💰 *መጠን:* {amount:.2f} {currency}\n"
                f"📋 *የፒሜንት መታወቂያ:* {payment_id}\n"
                f"🔢 *የግብይት መታወቂያ:* {tx_id}\n\n"
                f"🔍 *የድር ማረጋገጫ ተሳክቷል!*\n\n"
                f"💰 ቀሪ ሒሳብ: /balance",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=types.ReplyKeyboardRemove()
            )
        else:
            await message.answer(
                "⚠️ *ስርዓት ስህተት*\n\n"
                "የቴሌብር ክፍያ በራስ-ሰር ለማጠናቀቅ አልተቻለም።\n"
                "አስተዳዳሪዎች በቅርቡ ያረጋግጡታል።",
                reply_markup=types.ReplyKeyboardRemove()
            )
        
        await state.finish()
    
    # ==================== BALANCE COMMAND ====================
    
    @dp.message_handler(Command("balance"))
    async def cmd_balance_enhanced(message: types.Message):
        user_id = message.from_user.id
        
        from database.db import Database
        user = await Database.get_user(user_id)
        
        if not user:
            await Database.create_user(
                user_id=user_id,
                username=message.from_user.username or "",
                full_name=message.from_user.full_name or ""
            )
            user = await Database.get_user(user_id)
        
        if user:
            balance = user.get('balance', 10.00)
            await message.answer(
                f"💰 *የእርስዎ ቀሪ ሒሳብ*\n\n"
                f"🏦 የአሁኑ ቀሪ ሒሳብ: {balance:.2f} {currency}\n\n"
                f"💳 *ገንዘብ ለማስገባት:* /deposit\n\n"
                f"🆘 እርዳታ ያስፈልግዎታል? /support",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await message.answer(f"⚠️ ቀሪ ሒሳብዎን ማግኘት አልተቻለም። እባክዎን እንደገና ይሞክሩ።")
    
    # ==================== SUPPORT AND INSTRUCTIONS ====================
    
    @dp.message_handler(Command("instructions"))
    async def cmd_instructions_enhanced(message: types.Message):
        await message.answer(
            "📖 *መመሪያዎች*\n\n"
            f"📊 *ቀሪ ሒሳብዎን ለማየት*: /balance\n"
            f"💰 *ገንዘብ ለማስገባት*: /deposit\n\n"
            f"🆘 ድጋፍ: {SUPPORT_TELEGRAM_USER}",
            parse_mode=ParseMode.MARKDOWN
        )
    
    @dp.message_handler(Command("support"))
    async def cmd_support_enhanced(message: types.Message):
        await message.answer(
            f"🆘 *ድጋፍ እና እርዳታ*\n\n"
            f"*📱 የቴሌግራም ድጋፍ:* {SUPPORT_TELEGRAM_USER}\n\n"
            "*📞 ለሚከተሉት እርዳታ ያግኙን:*\n"
            "• የገንዘብ ክፍያ ጥያቄዎች\n"
            "• የሂሳብ ችግሮች\n"
            "• የቴክኒካር ችግሮች\n\n"
            "*⏰ የድጋፍ ሰዓት:* 24/7",
            parse_mode=ParseMode.MARKDOWN
        )
    
    # Initialize database
    try:
        logger.info("Initializing enhanced database...")
        from database.db import Database
        await Database.init_db()
        logger.info("[OK] Database tables initialized!")
        
        await Database.migrate_db()
        logger.info("[OK] Database migrations completed!")
        
    except Exception as e:
        logger.error(f"[ERROR] Database initialization failed: {e}")
        import traceback
        traceback.print_exc()
    
    # Start web servers as background task
    try:
        from web_server import start_web_server
        import threading
        
        def run_web_server_in_thread():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(start_web_server())
            except Exception as e:
                logger.error(f"Web server thread error: {e}")
            finally:
                loop.close()
        
        web_server_thread = threading.Thread(target=run_web_server_in_thread, daemon=True)
        web_server_thread.start()
        
        logger.info(f"[OK] HTTP web server started in background thread on http://{WEBSERVER_HOST}:{WEBSERVER_PORT}")
        
    except Exception as e:
        logger.error(f"[ERROR] Failed to start HTTP web server: {e}")
    
    # Setup menu button
    try:
        from aiogram.types import MenuButtonCommands
        await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
        logger.info("[OK] Menu button configured!")
    except Exception as e:
        logger.warning(f"[WARNING] Could not set menu button: {e}")
    
    # Update bot commands
    try:
        from aiogram.types import BotCommand
        
        user_commands = [
            BotCommand(command="start", description="Start bot and see menu"),
            BotCommand(command="balance", description=f"Check your balance ({currency})"),
            BotCommand(command="deposit", description=f"Deposit money"),
            BotCommand(command="instructions", description="Instructions"),
            BotCommand(command="support", description="Get support"),
        ]
        
        await bot.set_my_commands(user_commands)
        logger.info("[OK] Bot commands registered!")
    except Exception as e:
        logger.warning(f"[WARNING] Could not register commands: {e}")
    
    # Show startup info
    print("\n" + "="*60)
    print("🚀 SIMPLIFIED BOT STARTUP COMPLETE")
    print("="*60)
    print(f"🤖 Bot: @habesh_bingo_bot")
    print(f"💰 Currency: {currency.upper()}")
    print(f"📱 Payment Phone: {PAYMENT_PHONE_NUMBER}")
    print(f"👤 Receiver Name: {PAYMENT_RECEIVER_NAME}")
    print(f"🆘 Support: {SUPPORT_TELEGRAM_USER}")
    print(f"🛡️ Fraud Prevention: ENABLED")
    print(f"🌐 Telebirr Primary API: {TELEBIRR_VERIFICATION_API_URL} (POST)")
    print(f"🌐 Telebirr Secondary API: {TELEBIRR_VERIFICATION_API_URL_2} (GET)")
    print(f"🔑 Telebirr API Key: {'Configured' if TELEBIRR_API_KEY else 'Not Configured'}")
    print(f"🌐 Web Interface: http://{WEBSERVER_HOST}:{WEBSERVER_PORT}/game.html")
    if WEB_APP_URL:
        print(f"🌍 Public URL: {WEB_APP_URL}/game.html")
    print(f"✅ Status: Ready with simplified features")
    print("="*60 + "\n")
    
    print("📋 COMMANDS:")
    print(f"    /start        - Register and see menu")
    print(f"    /balance      - Check your balance")
    print(f"    /deposit      - Deposit with SMS verification (3 attempts)")
    print(f"    /instructions - Instructions")
    print(f"    /support      - Get support")
    print("="*60 + "\n")
    
    # Register bot with web_server
    try:
        from web_server import set_bot_instance
        set_bot_instance(bot)
        logger.info("✅ Registered bot instance with web_server")
        
        import sys
        sys.modules['bot'] = sys.modules[__name__]
        sys.modules['bot'].bot = bot
        logger.info("✅ Also registered bot in sys.modules")
    except Exception as e:
        logger.error(f"❌ Failed to register bot with web_server: {e}")
    
    # Run bot
    try:
        logger.info("Starting bot polling...")
        main_task = asyncio.current_task()
        await dp.start_polling()
        
    except Exception as e:
        logger.error(f"Error starting bot: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        await enhanced_shutdown()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
        print("\nBot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error in bot: {e}", exc_info=True)
        print(f"\nFatal error in bot: {e}")