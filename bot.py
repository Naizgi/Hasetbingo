#!/usr/bin/env python3
"""
Haset Bingo Bot - Round-Based Game Only
Enhanced with Telebirr/CBE verification, fraud prevention, and Amharic support
"""

import asyncio
import logging
import sys
import os
import signal
import time
import random
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
runner = None
shutting_down = False
restart_flag = False
aiohttp_session = None
main_task = None
game_manager = None
enhanced_payment_validator = None
bot = None
dp = None

# ==================== PAYMENT CONFIGURATION ====================
MINIMUM_WITHDRAWAL_AMOUNT = 100.00
PAYMENT_PHONE_NUMBER = "+251989929742"
PAYMENT_RECEIVER_NAME = "Nebiyu Asefa"
SUPPORT_TELEGRAM_USER = "@Hasetbingosupport"

# API URLs and keys (will be loaded from config)
TELEBIRR_VERIFICATION_API_URL = "http://verifyapi.leulzenebe.pro/verify-telebirr"
TELEBIRR_VERIFICATION_API_URL_2 = "https://www.verify.openmella.com.et/verify-telebirr"
TELEBIRR_API_KEY = ""
CBE_BIRR_VERIFICATION_API_URL = "https://verifyapi.leulzenebe.pro/verify-cbebirr"
CBE_BIRR_API_KEY = ""

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
        """Process API response for bot use - FIXED to use settledAmount"""
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

class CbeBirrVerificationApiClient:
    """Client for CBE Birr verification API"""
    
    def __init__(self, api_url: str = CBE_BIRR_VERIFICATION_API_URL, api_key: str = ""):
        self.api_url = api_url
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
        
    async def verify_transaction(self, receipt_number: str, phone_number: str):
        """Verify transaction through CBE Birr verification API"""
        if not receipt_number or receipt_number == "WITHDRAW":
            logger.error(f"Invalid receipt number for CBE Birr API: {receipt_number}")
            return None
            
        try:
            await self._ensure_session()
            logger.info(f"🔍 Calling CBE Birr verification API for receipt: {receipt_number}")
            logger.info(f"📱 Phone number sent to API: {phone_number}")
            
            headers = {
                "Content-Type": "application/json",
                "x-api-key": self.api_key
            }
            
            phone_clean = re.sub(r'[^\d]', '', phone_number)
            if phone_clean.startswith('0'):
                phone_clean = '251' + phone_clean[1:]
            elif phone_clean.startswith('+251'):
                phone_clean = phone_clean[1:]
            
            if len(phone_clean) != 12 or not phone_clean.startswith('251'):
                logger.error(f"Invalid phone format after cleaning: {phone_clean}")
                return None
            
            payload = {
                "receiptNumber": receipt_number,
                "phoneNumber": phone_clean
            }
            
            logger.info(f"📦 API Payload: {payload}")
            
            async with self._session.post(self.api_url, headers=headers, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    logger.info(f"✅ CBE Birr API response received. Status: {data.get('transactionStatus', 'Unknown')}")
                    return self._process_response(data, receipt_number)
                else:
                    error_text = await response.text()
                    logger.error(f"CBE Birr API Error {response.status}: {error_text}")
                    return None
                    
        except asyncio.TimeoutError:
            logger.error(f"Timeout verifying CBE Birr receipt {receipt_number}")
            return None
        except Exception as e:
            logger.error(f"Error calling CBE Birr API: {e}")
            return None
    
    def _process_response(self, api_data: dict, receipt_number: str):
        """Process API response for bot use - UPDATED FOR NEW STRUCTURE"""
        if not api_data:
            return None
            
        transaction_status = api_data.get('transactionStatus', 'Unknown')
        
        amount = 0.0
        amount_str = api_data.get('amount', '0.00') or api_data.get('paidAmount', '0.00')
        if amount_str:
            try:
                amount_str_clean = re.sub(r'[^\d.]', '', amount_str)
                amount = float(amount_str_clean)
            except ValueError:
                amount = 0.0
        
        credit_account = api_data.get('creditAccount', '')
        receiver_name = api_data.get('receiverName', '')
        customer_name = api_data.get('customerName', '')
        
        phone_match = False
        phone_number = ""
        
        if credit_account and ' - ' in credit_account:
            possible_phone = credit_account.split(' - ')[0].strip()
            phone_number = re.sub(r'[^\d]', '', possible_phone)
        
        if not phone_number and receiver_name:
            match = re.search(r'(\d{12})', receiver_name)
            if match:
                phone_number = match.group(1)
        
        admin_digits = re.sub(r'[^\d]', '', PAYMENT_PHONE_NUMBER)
        if phone_number and admin_digits and len(phone_number) >= 12:
            if phone_number[-9:] == admin_digits[-9:]:
                phone_match = True
        
        name_match = False
        name_to_check = ""
        
        if customer_name:
            name_to_check = customer_name
        elif receiver_name:
            name_to_check = re.sub(r'\d{12}\s*-\s*', '', receiver_name).strip()
        
        if name_to_check and PAYMENT_RECEIVER_NAME:
            receiver_name_norm = ' '.join(name_to_check.lower().split())
            payment_name_norm = ' '.join(PAYMENT_RECEIVER_NAME.lower().split())
            
            if (payment_name_norm in receiver_name_norm or 
                receiver_name_norm in payment_name_norm):
                name_match = True
        
        result = {
            'success': transaction_status == 'Completed',
            'transaction_status': transaction_status,
            'receipt_number': receipt_number,
            'amount': amount,
            'credit_account': credit_account,
            'receiver_name': receiver_name,
            'customer_name': customer_name,
            'phone_match': phone_match,
            'name_match': name_match,
            'phone_number': phone_number,
            'raw_data': api_data
        }
        
        result['is_valid'] = (
            result['success'] and
            result.get('amount', 0) > 0 and
            result.get('phone_match') == True and
            result.get('transaction_status') == 'Completed'
        )
        
        return result

# ==================== SMS SCRAPERS ====================
class TelebirrScraper:
    """SMS-only scraper for Ethio telecom receipts"""
    
    def extract_transaction_id(self, sms_text: str):
        if not sms_text or sms_text == "WITHDRAW":
            return None
            
        sms_text = sms_text.replace('\n', ' ').replace('\r', ' ')
        sms_text = ' '.join(sms_text.split())
        
        patterns = [
            r'transactioninfo\.ethiotelecom\.et/receipt/([A-Z0-9]+)',
            r'receipt/([A-Z0-9]+)',
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
    
    def extract_info_from_sms(self, sms_text: str):
        result = {
            'transaction_id': None,
            'amount': None,
            'receiver_name': None,
            'receiver_phone': None,
            'extracted': False
        }
        
        if not sms_text or sms_text == "WITHDRAW":
            return result
            
        sms_text = sms_text.replace('\n', ' ').replace('\r', ' ')
        sms_text = ' '.join(sms_text.split())
        
        result['transaction_id'] = self.extract_transaction_id(sms_text)
        
        amount_patterns = [
            r'ETB\s*([\d,]+\.?\d*)',
            r'ብር\s*([\d,]+\.?\d*)',
            r'BIRR\s*([\d,]+\.?\d*)',
            r'([\d,]+\.?\d{2})\s*(?:ETB|ብር|BIRR)?'
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
                        if amount_float > 0.1:
                            result['amount'] = amount_float
                            break
                    except ValueError:
                        continue
        
        phone_patterns = [
            r'to\s+[^\(]*\((\+?2519\d{8}|09\d{8}|2519\*\*\*\*\d{4})\)',
            r'receiver\s*[:\s]*(\+?2519\d{8}|09\d{8}|2519\*\*\*\*\d{4})',
            r'(\+2519\d{8})',
            r'(09\d{8})',
        ]
        
        for pattern in phone_patterns:
            match = re.search(pattern, sms_text, re.IGNORECASE)
            if match:
                phone = match.group(1).strip()
                if '****' in phone:
                    result['receiver_phone'] = phone
                elif '2519' in phone or '09' in phone:
                    if phone.startswith('09'):
                        phone = '+251' + phone[1:]
                    elif phone.startswith('251'):
                        phone = '+' + phone
                    elif not phone.startswith('+'):
                        phone = '+251' + phone[-9:] if len(phone) >= 9 else phone
                    result['receiver_phone'] = phone
                break
        
        result['extracted'] = all([
            result['transaction_id'] is not None,
            result['amount'] is not None,
            result['receiver_phone'] is not None
        ])
        
        return result

class CbeBirrScraper:
    """SMS scraper for CBE Birr receipts - UPDATED FOR NEW SMS FORMAT"""
    
    def extract_receipt_number(self, sms_text: str):
        if not sms_text or sms_text == "WITHDRAW":
            return None
            
        sms_text = sms_text.replace('\n', ' ').replace('\r', ' ')
        sms_text = ' '.join(sms_text.split())
        
        patterns = [
            r'Txn\s*ID\s*([A-Z0-9]{10,15})',
            r'Receipt\s*(?:No|Number|#)?[:\s]*([A-Z0-9]{8,15})',
            r'receipt\s*(?:No|Number|#)?[:\s]*([A-Z0-9]{8,15})',
            r'(\b[A-Z0-9]{10,15}\b)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, sms_text, re.IGNORECASE)
            if match:
                receipt_no = match.group(1).strip().upper()
                if self.validate_receipt_number(receipt_no):
                    return receipt_no
        
        return None
    
    def validate_receipt_number(self, receipt_no: str):
        if not receipt_no or len(receipt_no) < 8:
            return False
        if not re.match(r'^[A-Z0-9]+$', receipt_no):
            return False
        return True
    
    def extract_phone_number(self, sms_text: str):
        if not sms_text or sms_text == "WITHDRAW":
            return None
            
        sms_text = sms_text.replace('\n', ' ').replace('\r', ' ')
        sms_text = ' '.join(sms_text.split())
        
        phone_patterns = [
            r'PH=(\d{12})',
            r'Phone\s*(?:No|Number)?[:\s]*(\+?251\d{9})',
            r'phone\s*(?:No|Number)?[:\s]*(\+?251\d{9})',
            r'(\+251\d{9})',
            r'(09\d{8})'
        ]
        
        for pattern in phone_patterns:
            match = re.search(pattern, sms_text, re.IGNORECASE)
            if match:
                phone = match.group(1).strip()
                
                phone_clean = re.sub(r'[^\d]', '', phone)
                
                if phone_clean.startswith('09') and len(phone_clean) == 10:
                    phone_clean = '251' + phone_clean[2:]
                elif phone_clean.startswith('+251'):
                    phone_clean = phone_clean[1:]
                elif phone_clean.startswith('251') and len(phone_clean) == 12:
                    pass
                elif len(phone_clean) == 9:
                    phone_clean = '251' + phone_clean
                elif len(phone_clean) == 12 and phone_clean.startswith('251'):
                    pass
                
                if len(phone_clean) == 12 and phone_clean.startswith('251'):
                    logger.info(f"📱 Extracted and formatted phone for CBE API: {phone_clean}")
                    return phone_clean
                else:
                    logger.warning(f"⚠️ Phone format incorrect after processing: {phone_clean}")
        
        logger.warning(f"⚠️ No valid phone number found in SMS: {sms_text[:100]}...")
        return None
    
    def extract_amount(self, sms_text: str):
        if not sms_text or sms_text == "WITHDRAW":
            return None
            
        sms_text = sms_text.replace('\n', ' ').replace('\r', ' ')
        sms_text = ' '.join(sms_text.split())
        
        amount_patterns = [
            r'sent\s*([\d,]+\.?\d*)\s*Br',
            r'Amount\s*[:\s]*([\d,]+\.?\d*)',
            r'amount\s*[:\s]*([\d,]+\.?\d*)',
            r'ETB\s*([\d,]+\.?\d*)',
            r'([\d,]+\.\d{2})\s*(?:ETB|ብር|BIRR|Br)?'
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
                        if amount_float > 0.1:
                            return amount_float
                    except ValueError:
                        continue
        
        return None
    
    def extract_receiver_name(self, sms_text: str):
        if not sms_text or sms_text == "WITHDRAW":
            return None
            
        sms_text = sms_text.replace('\n', ' ').replace('\r', ' ')
        sms_text = ' '.join(sms_text.split())
        
        pattern = r'to\s+([A-Z\s]+?)(?:\s+on\s+|\s*,\s*|\.)'
        match = re.search(pattern, sms_text, re.IGNORECASE)
        if match:
            name = match.group(1).strip()
            if name and len(name) > 2:
                return name
        
        return None
    
    def extract_info_from_sms(self, sms_text: str):
        result = {
            'receipt_number': None,
            'phone_number': None,
            'amount': None,
            'receiver_name': None,
            'extracted': False
        }
        
        if not sms_text or sms_text == "WITHDRAW":
            return result
            
        result['receipt_number'] = self.extract_receipt_number(sms_text)
        result['phone_number'] = self.extract_phone_number(sms_text)
        result['amount'] = self.extract_amount(sms_text)
        result['receiver_name'] = self.extract_receiver_name(sms_text)
        
        result['extracted'] = all([
            result['receipt_number'] is not None,
            result['phone_number'] is not None,
            result['amount'] is not None
        ])
        
        logger.info(f"CBE SMS Extraction Result: {result}")
        return result

# ==================== ENHANCED PAYMENT VALIDATOR ====================
class EnhancedPaymentValidator:
    """Enhanced validator with SMS parsing and API verification"""
    
    def __init__(self, admin_phone: str, admin_name: str = None):
        self.admin_phone = admin_phone
        self.admin_name = admin_name or PAYMENT_RECEIVER_NAME
        self.admin_phone_digits = re.sub(r'[^\d]', '', admin_phone)
        self.telebirr_scraper = TelebirrScraper()
        self.cbebirr_scraper = CbeBirrScraper()
        self.telebirr_client = None
        self.cbebirr_client = None
        
        logger.info("✅ Payment verification API clients initialized")
    
    async def initialize_clients(self, telebirr_api_key: str = "", cbebirr_api_key: str = ""):
        """Initialize API clients with proper session management"""
        self.telebirr_client = TelebirrVerificationApiClient(
            api_url=TELEBIRR_VERIFICATION_API_URL,
            api_key=telebirr_api_key
        )
        
        self.cbebirr_client = CbeBirrVerificationApiClient(
            api_url=CBE_BIRR_VERIFICATION_API_URL,
            api_key=cbebirr_api_key
        )
        
        if telebirr_api_key:
            await self.telebirr_client._ensure_session()
        if cbebirr_api_key:
            await self.cbebirr_client._ensure_session()
    
    async def close(self):
        """Close all API client sessions"""
        if self.telebirr_client:
            await self.telebirr_client.close()
        if self.cbebirr_client:
            await self.cbebirr_client.close()
    
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
            
            # Use the verify_transaction method that tries both APIs with fallback
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
    
    async def verify_cbebirr_transaction(self, sms_text: str):
        """Verify CBE Birr transaction - UPDATED"""
        try:
            if not sms_text or sms_text == "WITHDRAW":
                return False, None, ["Invalid SMS text provided"]
                
            sms_info = self.cbebirr_scraper.extract_info_from_sms(sms_text)
            
            logger.info(f"CBE Birr SMS info extracted: {sms_info}")
            
            if not sms_info['extracted']:
                receipt_no = self.cbebirr_scraper.extract_receipt_number(sms_text)
                if not receipt_no:
                    return False, None, ["Failed to extract receipt number from SMS"]
                
                sms_info['receipt_number'] = receipt_no
                sms_info['phone_number'] = self.cbebirr_scraper.extract_phone_number(sms_text)
                sms_info['amount'] = self.cbebirr_scraper.extract_amount(sms_text)
            
            if not sms_info.get('receipt_number'):
                return False, None, ["Receipt number not found in SMS"]
                
            if not sms_info.get('phone_number'):
                logger.error(f"No phone number extracted from SMS: {sms_text[:100]}...")
                return False, None, ["Phone number not found in SMS"]
            
            sms_hash = self.calculate_sms_hash(sms_text)
            is_duplicate = await self.check_duplicate_transaction(sms_info['receipt_number'], sms_hash, 'CBE Birr')
            
            if is_duplicate:
                return False, None, ["This transaction has already been used"]
            
            if not self.cbebirr_client:
                return False, None, ["CBE Birr client not initialized"]
            
            api_result = await self.cbebirr_client.verify_transaction(
                sms_info['receipt_number'], 
                sms_info['phone_number']
            )
            
            if not api_result:
                return False, None, ["Failed to verify transaction via CBE Birr API"]
            
            if not api_result.get('success', False):
                return False, None, ["Transaction verification failed"]
            
            errors = []
            api_amount = api_result.get('amount')
            
            if api_amount is None or api_amount <= 0:
                errors.append("No valid amount found in receipt")
            elif sms_info.get('amount'):
                sms_amount = sms_info['amount']
                max_allowed_difference = 2.0
                if abs(sms_amount - api_amount) > max_allowed_difference:
                    errors.append(f"Amount mismatch (SMS: {sms_amount:.2f} vs API: {api_amount:.2f})")
            
            if not api_result.get('is_valid', False):
                if not api_result.get('phone_match'):
                    errors.append(f"Payment phone not found in receipt. Expected: {PAYMENT_PHONE_NUMBER}")
                else:
                    errors.append("Transaction not valid")
            
            if api_result.get('transaction_status') != 'Completed':
                errors.append("Transaction status is not completed")
            
            if sms_info.get('receiver_name') and api_result.get('customer_name'):
                receiver_name_norm = ' '.join(sms_info['receiver_name'].lower().split())
                customer_name_norm = ' '.join(api_result['customer_name'].lower().split())
                payment_name_norm = ' '.join(PAYMENT_RECEIVER_NAME.lower().split())
                
                name_matches = (
                    payment_name_norm in customer_name_norm or 
                    customer_name_norm in payment_name_norm or
                    payment_name_norm in receiver_name_norm or
                    receiver_name_norm in payment_name_norm
                )
                
                if not name_matches:
                    errors.append(f"Receiver name mismatch. Expected: {PAYMENT_RECEIVER_NAME}")
            
            if errors:
                return False, api_amount, errors
            else:
                return True, api_amount, []
            
        except Exception as e:
            logger.error(f"CBE Birr verification error: {e}", exc_info=True)
            return False, None, [f"Verification error: {str(e)}"]

# ==================== SHUTDOWN HANDLERS ====================
async def enhanced_shutdown(restart: bool = False):
    """Enhanced clean shutdown with optional restart flag"""
    global shutting_down, main_task, enhanced_payment_validator, restart_flag
    if shutting_down:
        return
    
    restart_flag = restart
    shutting_down = True
    
    logger.info(f"Initiating enhanced shutdown... {'(RESTART MODE)' if restart else ''}")
    
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
            
            if hasattr(enhanced_payment_validator, 'cbebirr_client'):
                await enhanced_payment_validator.cbebirr_client.close()
                logger.info("✅ Closed CBE Birr API client")
        
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
        if restart:
            logger.info("🔄 Restarting bot...")
            os.execv(sys.executable, ['python'] + sys.argv)
        else:
            os._exit(0)

def handle_signal(signum, frame):
    """Handle system signals"""
    logger.info(f"Received signal {signum}, shutting down...")
    asyncio.create_task(enhanced_shutdown())

# ==================== GLOBAL VARIABLES ====================
currency = None

# ==================== NOTIFICATION FUNCTIONS ====================
async def send_notification_to_user(user_id: int, message: str) -> bool:
    """Send a notification message to a user - USING QUEUE SYSTEM"""
    try:
        # Import the web_server notification queue
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
        "📬 እንዲፈቀድለት ወይም እንዲተው ሲደረግ ማሳወቂያ ይደርስዎታል።\n"
        "⏰ የማቀነባበሪያ ጊዜ፡ ብዙውን ጊዜ በ24 ሰዓታት ውስጥ\n\n"
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
        "🎮 አሁን /balance ብለው አዲሱን ቀሪ ሒሳብዎ ለመመልከት እና መጫወት መጀመር ይችላሉ!\n\n"
        "Haset Bingo ስለመረጡዎ እናመሰግናለን! 🎯"
    )
    return await send_notification_to_user(user_id, message)

async def notify_deposit_rejected(user_id: int, amount: float, payment_id: int, reason: str):
    """Notify user that deposit was rejected"""
    global currency
    message = (
        "*❌ የገንዘብ ክፍያ ተቀብሏል*\n\n"
        f"*📋 የፒሜንት መታወቂያ:* {payment_id}\n"
        f"*💵 መጠን:* {amount:.2f} {currency}\n\n"
        "⚠️ የገንዘብ ክፍያ ጥያቄዎ ተቀብሏል።\n"
        "🔄 እባክዎ እውነተኛ የቴሌብር ማረጋገጫ SMS ይላኩ።\n\n"
        "አዲስ የገንዘብ ክፍያ ጥያቄ ለመጨመር በ /deposit መጠቀም ይችላሉ\n"
        "ወይም ለእርዳታ ድጋፍ ያግኙ።"
    )
    return await send_notification_to_user(user_id, message)

async def notify_auto_approved_deposit(user_id: int, amount: float, payment_id: int, transaction_id: str, payment_method: str):
    """Notify user that deposit was auto-approved - FIXED"""
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
        f"🚀 አሁን ቢንጎ መጫወት መጀመር ይችላሉ!"
    )
    
    return await send_notification_to_user(user_id, message)

# ==================== PAYMENT DATABASE METHODS ====================
async def create_payment_request(user_id: int, amount: float, payment_method: str, transaction_proof: str = None) -> int:
    """Create a payment (deposit) request - FIXED FOREIGN KEY ISSUE"""
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

async def approve_payment(payment_id: int, admin_id: int) -> bool:
    """Approve a payment (deposit) request"""
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
                    processed_by = ?,
                    admin_notes = 'Approved by admin ' || ?
                WHERE id = ?
            """, (datetime.now(), admin_id, str(admin_id), payment_id))
            
            # FIXED: Add transaction_type parameter
            await Database.add_user_balance(user_id, amount, 'deposit', f'Payment approved: {payment_id}')
            
            logger.info(f"Payment {payment_id} approved for user {user_id}, amount {amount}")
            
            await notify_deposit_approved(user_id, amount, payment_id)
            
            return True
            
    except Exception as e:
        logger.error(f"Error approving payment: {e}")
        return False

async def reject_payment(payment_id: int, admin_id: int, reason: str) -> bool:
    """Reject a payment (deposit) request"""
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
                SET status = 'rejected', 
                    processed_at = ?,
                    processed_by = ?,
                    admin_notes = ?
                WHERE id = ?
            """, (datetime.now(), admin_id, f'Rejected by admin {admin_id}: {reason}', payment_id))
            
            logger.info(f"Payment {payment_id} rejected")
            
            await notify_deposit_rejected(user_id, amount, payment_id, reason)
            
            return True
            
    except Exception as e:
        logger.error(f"Error rejecting payment: {e}")
        return False

async def auto_approve_deposit(user_id: int, payment_id: int, amount: float, transaction_id: str, sms_text: str, api_data: dict = None, payment_method: str = "Telebirr") -> bool:
    """Auto-approve deposit after successful verification - FIXED FOR DATABASE SCHEMA"""
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
            
            # FIXED: Remove receiver_phone, receiver_name, payment_method - these columns don't exist in schema
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
            
            # FIXED: Add transaction_type parameter
            await Database.add_user_balance(user_id, amount, 'deposit', f'Auto-approved via {payment_method}: {payment_id}')
        
        await notify_auto_approved_deposit(user_id, amount, payment_id, transaction_id, payment_method)
        
        logger.info(f"Deposit auto-approved via {payment_method} API: user {user_id}, payment {payment_id}, amount {amount}")
        return True
        
    except Exception as e:
        logger.error(f"Error auto-approving deposit: {e}", exc_info=True)
        return False

# ==================== WITHDRAWAL DATABASE METHODS - COMPLETELY FIXED ====================
async def create_withdrawal_request(user_id: int, amount: float, payment_method: str, full_name: str = None, phone_number: str = None) -> int:
    """Create a withdrawal request with full name and phone - COMPLETE FIX with all columns"""
    try:
        from database.db import Database
        
        user = await Database.get_user(user_id)
        if not user or user.get('balance', 0) < amount:
            return 0
        
        with Database.get_cursor() as cursor:
            # First, create transaction (THIS ALREADY UPDATES THE BALANCE)
            transaction_id = await Database.add_transaction(
                user_id,
                'withdrawal_request',
                -amount,
                f"Withdrawal request via {payment_method} to {phone_number}"
            )
            
            # Create withdrawal request with ALL available columns
            # Check which columns exist in the table
            cursor.execute("PRAGMA table_info(withdrawal_requests)")
            columns = cursor.fetchall()
            column_names = [col[1] for col in columns]
            
            # Build the INSERT statement dynamically based on existing columns
            if 'full_name' in column_names and 'payment_method' in column_names:
                # New schema with all columns
                cursor.execute('''
                    INSERT INTO withdrawal_requests 
                    (user_id, amount, phone_number, method, payment_method, full_name, status, transaction_id, requested_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ''', (user_id, amount, phone_number, payment_method, payment_method, full_name, 'pending', transaction_id))
            elif 'full_name' in column_names:
                # Has full_name but not payment_method
                cursor.execute('''
                    INSERT INTO withdrawal_requests 
                    (user_id, amount, phone_number, method, full_name, status, transaction_id, requested_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ''', (user_id, amount, phone_number, payment_method, full_name, 'pending', transaction_id))
            elif 'payment_method' in column_names:
                # Has payment_method but not full_name
                cursor.execute('''
                    INSERT INTO withdrawal_requests 
                    (user_id, amount, phone_number, method, payment_method, status, transaction_id, requested_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ''', (user_id, amount, phone_number, payment_method, payment_method, 'pending', transaction_id))
            else:
                # Minimal schema
                cursor.execute('''
                    INSERT INTO withdrawal_requests 
                    (user_id, amount, phone_number, method, status, transaction_id, requested_at)
                    VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
                ''', (user_id, amount, phone_number, payment_method, 'pending', transaction_id))
            
            withdrawal_id = cursor.lastrowid
            
            logger.info(f"Withdrawal request {withdrawal_id} created for user {user_id}, amount {amount}")
            
            return withdrawal_id
            
    except Exception as e:
        logger.error(f"Error creating withdrawal request: {e}")
        import traceback
        traceback.print_exc()
        return 0

async def process_withdrawal_request(withdrawal_id: int, admin_id: int, approve: bool = True, reason: str = "") -> bool:
    """Process a withdrawal request (approve or reject) - COMPLETE FIX"""
    try:
        from database.db import Database
        
        with Database.get_cursor() as cursor:
            cursor.execute("""
                SELECT wr.* FROM withdrawal_requests wr
                WHERE wr.id = ? AND wr.status = 'pending'
            """, (withdrawal_id,))
            withdrawal = cursor.fetchone()
            
            if not withdrawal:
                return False
            
            withdrawal_dict = dict(withdrawal)
            user_id = withdrawal_dict['user_id']
            amount = withdrawal_dict['amount']
            payment_method = withdrawal_dict.get('payment_method', withdrawal_dict.get('method', 'Unknown'))
            phone_number = withdrawal_dict.get('phone_number', 'N/A')
            full_name = withdrawal_dict.get('full_name', 'N/A')
            
            if approve:
                # APPROVE WITHDRAWAL
                cursor.execute("""
                    UPDATE withdrawal_requests 
                    SET status = 'approved', 
                        processed_at = ?,
                        processed_by = ?,
                        admin_notes = 'Approved by admin ' || ?
                    WHERE id = ?
                """, (datetime.now(), admin_id, str(admin_id), withdrawal_id))
                
                if cursor.rowcount > 0:
                    # Record transaction for approved withdrawal
                    await Database.add_transaction(
                        user_id,
                        'withdrawal_approved',
                        -amount,
                        f"Withdrawal approved via {payment_method} to {phone_number}"
                    )
                    
                    # Update user's total_withdrawals (if column exists)
                    try:
                        cursor.execute("""
                            UPDATE users 
                            SET total_withdrawals = COALESCE(total_withdrawals, 0) + ?
                            WHERE user_id = ?
                        """, (amount, user_id))
                    except Exception as column_err:
                        logger.warning(f"Could not update total_withdrawals: {column_err}")
                    
                    logger.info(f"Withdrawal {withdrawal_id} approved by admin {admin_id} for user {user_id}, amount {amount}")
                    
                    # Send success notification to user
                    await send_notification_to_user(user_id, 
                        f"✅ *የገንዘብ ማውጣት ፈቅዷል!*\n\n"
                        f"💰 *መጠን:* {amount:.2f} {currency}\n"
                        f"📋 *የማውጣት መታወቂያ:* {withdrawal_id}\n"
                        f"🏦 *ዘዴ:* {payment_method}\n"
                        f"👤 *ስም:* {full_name}\n"
                        f"📱 *ስልክ:* {phone_number}\n\n"
                        f"💳 ገንዘብዎ በቅርቡ ይላካል።\n"
                        f"⏰ በ24 ሰዓታት ውስጥ መቀበል ይጠበቃል።"
                    )
                    return True
            else:
                # REJECT WITHDRAWAL
                cursor.execute("""
                    UPDATE withdrawal_requests 
                    SET status = 'rejected', 
                        processed_at = ?,
                        processed_by = ?,
                        admin_notes = ?
                    WHERE id = ?
                """, (datetime.now(), admin_id, f'Rejected by admin {admin_id}: {reason}', withdrawal_id))
                
                if cursor.rowcount > 0:
                    # REFUND the amount back to user
                    await Database.add_transaction(
                        user_id,
                        'withdrawal_refund',
                        amount,
                        f"Withdrawal rejected, refunded: {reason}"
                    )
                    
                    logger.info(f"Withdrawal {withdrawal_id} rejected by admin {admin_id}, refunded {amount} to user {user_id}")
                    
                    # Send rejection notification to user
                    await send_notification_to_user(user_id,
                        f"❌ *የገንዘብ ማውጣት ተቋርጧል!*\n\n"
                        f"💰 *መጠን:* {amount:.2f} {currency}\n"
                        f"📋 *የማውጣት መታወቂያ:* {withdrawal_id}\n\n"
                        f"📝 *ምክንያት:* {reason}\n\n"
                        f"🔄 እባክዎ አዲስ የገንዘብ ማውጣት ጥያቄ ይጀምሩ /withdraw"
                    )
                    return True
            
            return False
            
    except Exception as e:
        logger.error(f"Error processing withdrawal request: {e}")
        import traceback
        traceback.print_exc()
        return False

# ==================== SAFE DATABASE RESTORE FUNCTION ====================
async def restore_database_from_file(file_path: str, admin_id: int, original_message, status_msg) -> Tuple[bool, str]:
    """
    Safely restore database from a backup file with complete shutdown
    
    This function:
    1. Validates the uploaded file
    2. Stops ALL database operations
    3. Creates a backup of current database
    4. Safely replaces the database file
    5. Restarts the bot to ensure clean state
    
    Args:
        file_path: Path to the uploaded database file
        admin_id: Admin ID performing the restore
        original_message: Original message from user
        status_msg: Status message to update
    
    Returns:
        Tuple of (success, message)
    """
    try:
        from database.db import Database
        import time
        
        logger.warning(f"⚠️ DATABASE RESTORE INITIATED by admin {admin_id}")
        
        # ========== STEP 1: VALIDATE FILE ==========
        logger.info("Step 1: Validating uploaded database file...")
        
        # Update status
        try:
            await status_msg.edit_text(
                "⏳ SAFE RESTORE PROCESS\n\n"
                "✅ Step 1/6: File downloaded\n"
                "✅ Step 2/6: Basic validation passed\n"
                "🔄 Step 3/6: Testing database integrity..."
            )
        except:
            pass
        
        # Validate file exists
        if not os.path.exists(file_path):
            return False, "❌ Database file not found"
        
        # Validate file size (prevent huge files)
        file_size = os.path.getsize(file_path)
        if file_size > 100 * 1024 * 1024:  # 100 MB limit
            return False, "❌ File too large (max 100 MB)"
        
        # Validate it's a SQLite database by checking header
        with open(file_path, 'rb') as f:
            header = f.read(16)
            if header[:16] != b'SQLite format 3\x00':
                return False, "❌ Invalid database file format - not a SQLite database"
        
        # Try to open the database to ensure it's valid
        try:
            test_conn = sqlite3.connect(file_path)
            test_conn.execute("SELECT name FROM sqlite_master WHERE type='table' LIMIT 1")
            test_conn.close()
            logger.info("✅ Uploaded database file is valid")
        except Exception as e:
            return False, f"❌ Corrupted database file: {str(e)[:100]}"
        
        # Get current database path
        current_db_path = getattr(Database, '_db_path', 'habesha_bingo.db')
        logger.info(f"Current database path: {current_db_path}")
        
        # Update status
        try:
            await status_msg.edit_text(
                "⏳ SAFE RESTORE PROCESS\n\n"
                "✅ Step 1/6: File downloaded\n"
                "✅ Step 2/6: Basic validation passed\n"
                "✅ Step 3/6: Database integrity verified\n"
                "🔄 Step 4/6: Creating backup..."
            )
        except:
            pass
        
        # ========== STEP 2: CREATE BACKUP ==========
        logger.info("Step 2: Creating backup of current database...")
        
        # Create backup with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = f"{current_db_path}.backup_{timestamp}"
        
        if os.path.exists(current_db_path):
            # Use copy2 to preserve metadata
            shutil.copy2(current_db_path, backup_path)
            logger.info(f"✅ Backup created at: {backup_path}")
            backup_size = os.path.getsize(backup_path)
            logger.info(f"Backup size: {backup_size / (1024*1024):.2f} MB")
        else:
            logger.warning("⚠️ No existing database found to backup")
            backup_path = None
        
        # Update status
        try:
            await status_msg.edit_text(
                "⏳ SAFE RESTORE PROCESS\n\n"
                "✅ Step 1/6: File downloaded\n"
                "✅ Step 2/6: Basic validation passed\n"
                "✅ Step 3/6: Database integrity verified\n"
                "✅ Step 4/6: Backup created\n"
                "🔄 Step 5/6: Shutting down bot..."
            )
        except:
            pass
        
        # ========== STEP 3: GRACEFUL SHUTDOWN ==========
        logger.info("Step 3: Performing graceful shutdown of all bot components...")
        
        global shutting_down, dp, bot, main_task, enhanced_payment_validator
        
        # Set shutdown flag to prevent new operations
        original_shutdown_state = shutting_down
        shutting_down = True
        logger.info("✅ Shutdown flag set")
        
        # Stop accepting new requests
        logger.info("Stopping bot polling...")
        if dp:
            try:
                await dp.stop_polling()
                logger.info("✅ Bot polling stopped")
            except Exception as e:
                logger.warning(f"Error stopping polling: {e}")
        
        # Close bot session
        if bot and hasattr(bot, 'session') and bot.session:
            try:
                await bot.session.close()
                logger.info("✅ Bot session closed")
            except Exception as e:
                logger.warning(f"Error closing bot session: {e}")
        
        # Close payment validator clients
        if enhanced_payment_validator:
            try:
                await enhanced_payment_validator.close()
                logger.info("✅ Payment validator closed")
            except Exception as e:
                logger.warning(f"Error closing payment validator: {e}")
        
        # CRITICAL: Close ALL database connections
        logger.info("Closing all database connections...")
        try:
            await Database.close_all_connections()
            logger.info("✅ All database connections closed")
        except Exception as e:
            logger.warning(f"Error closing database connections: {e}")
        
        # Force garbage collection to ensure all connections are released
        gc.collect()
        logger.info("✅ Garbage collection completed")
        
        # Wait to ensure all operations complete
        logger.info("Waiting 3 seconds for all operations to settle...")
        await asyncio.sleep(3)
        
        # Update status
        try:
            await status_msg.edit_text(
                "⏳ SAFE RESTORE PROCESS\n\n"
                "✅ Step 1/6: File downloaded\n"
                "✅ Step 2/6: Basic validation passed\n"
                "✅ Step 3/6: Database integrity verified\n"
                "✅ Step 4/6: Backup created\n"
                "✅ Step 5/6: Bot shutdown complete\n"
                "🔄 Step 6/6: Replacing database..."
            )
        except:
            pass
        
        # ========== STEP 4: SAFELY REPLACE DATABASE ==========
        logger.info("Step 4: Safely replacing database file...")
        
        # Create a temporary file for the new database
        temp_restore_path = f"{current_db_path}.restore_temp"
        
        # Copy uploaded file to temp location
        shutil.copy2(file_path, temp_restore_path)
        logger.info(f"✅ Copied uploaded file to temp location: {temp_restore_path}")
        
        # On Unix, rename is atomic; on Windows, we need to be careful
        try:
            # Remove old database if it exists
            if os.path.exists(current_db_path):
                os.remove(current_db_path)
                logger.info("✅ Removed old database file")
            
            # Rename temp file to actual database file (atomic on Unix)
            os.rename(temp_restore_path, current_db_path)
            logger.info(f"✅ New database file placed at: {current_db_path}")
            
        except Exception as e:
            logger.error(f"❌ Error replacing database: {e}")
            
            # If something went wrong, try to restore from backup
            if backup_path and os.path.exists(backup_path):
                logger.info("🔄 Attempting to restore from backup...")
                if os.path.exists(current_db_path):
                    os.remove(current_db_path)
                shutil.copy2(backup_path, current_db_path)
                logger.info("✅ Restored from backup")
            
            return False, f"❌ Failed to replace database: {str(e)[:100]}"
        
        # Verify new database is readable
        try:
            test_conn = sqlite3.connect(current_db_path)
            test_conn.execute("SELECT name FROM sqlite_master WHERE type='table' LIMIT 1")
            test_conn.close()
            logger.info("✅ New database is readable and valid")
        except Exception as e:
            logger.error(f"❌ New database is corrupted: {e}")
            
            # Restore from backup
            if backup_path and os.path.exists(backup_path):
                logger.info("🔄 Restoring from backup...")
                if os.path.exists(current_db_path):
                    os.remove(current_db_path)
                shutil.copy2(backup_path, current_db_path)
                logger.info("✅ Restored from backup")
            
            return False, f"❌ Restored database is corrupted: {str(e)[:100]}"
        
        # Update final status
        try:
            await status_msg.edit_text(
                "✅ SAFE RESTORE PROCESS COMPLETE\n\n"
                "✅ Step 1/6: File downloaded\n"
                "✅ Step 2/6: Basic validation passed\n"
                "✅ Step 3/6: Database integrity verified\n"
                "✅ Step 4/6: Backup created\n"
                "✅ Step 5/6: Bot shutdown complete\n"
                "✅ Step 6/6: Database replaced successfully\n\n"
                f"📁 Backup saved: {os.path.basename(backup_path) if backup_path else 'None'}\n"
                f"📊 New database size: {file_size / (1024*1024):.2f} MB\n\n"
                "🔄 Bot is restarting now..."
            )
        except:
            pass
        
        # ========== STEP 5: LOG THE RESTORE ACTION ==========
        logger.info("Step 5: Logging restore action...")
        
        # Try to log to the new database (may fail if admin_actions table doesn't exist)
        try:
            with Database.get_cursor() as cursor:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS admin_actions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        admin_id INTEGER NOT NULL,
                        action_type TEXT NOT NULL,
                        details TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                cursor.execute("""
                    INSERT INTO admin_actions (admin_id, action_type, details)
                    VALUES (?, ?, ?)
                """, (admin_id, 'database_restore', f'Database restored from backup. Backup saved as: {os.path.basename(backup_path) if backup_path else "None"}'))
            logger.info("✅ Restore action logged")
        except Exception as e:
            logger.warning(f"Could not log restore action: {e}")
        
        # Wait a moment for final message
        await asyncio.sleep(2)
        
        # ========== STEP 6: RESTART BOT ==========
        logger.info("Step 6: Restarting bot...")
        
        # Perform full restart
        logger.info("🚀 Executing bot restart...")
        await enhanced_shutdown(restart=True)
        
        # This line will never be reached
        return True, "Database restored successfully. Bot restarting..."
        
    except Exception as e:
        logger.error(f"Error in database restore: {e}", exc_info=True)
        return False, f"❌ Error: {str(e)[:200]}"

# ==================== MAIN FUNCTION ====================
async def main():
    """Main application entry point"""
    global runner, currency, enhanced_payment_validator, game_manager, main_task, bot, dp
    
    import sys
    if sys.platform != "win32":
        signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    
    logger.info("Starting Haset Bingo Bot - Enhanced with Fraud Prevention...")
    
    try:
        from config import BOT_TOKEN, GAME_CONFIG, WEBSERVER_HOST, WEBSERVER_PORT, WEB_APP_URL, ADMIN_IDS
    except ImportError as e:
        logger.error(f"Failed to import config: {e}")
        return
    
    try:
        TELEBIRR_API_KEY = GAME_CONFIG.get('telebirr_api_key', '')
        CBE_BIRR_API_KEY = GAME_CONFIG.get('cbebirr_api_key', '')
        if not TELEBIRR_API_KEY:
            logger.warning("⚠️ Telebirr API key not found in config.")
        if not CBE_BIRR_API_KEY:
            logger.warning("⚠️ CBE Birr API key not found in config.")
    except:
        TELEBIRR_API_KEY = ''
        CBE_BIRR_API_KEY = ''
        logger.warning("⚠️ API keys not configured.")
    
    currency = GAME_CONFIG.get('currency', 'birr')
    card_price = GAME_CONFIG.get('card_price', 10.00)
    
    enhanced_payment_validator = EnhancedPaymentValidator(
        PAYMENT_PHONE_NUMBER,
        PAYMENT_RECEIVER_NAME
    )
    
    await enhanced_payment_validator.initialize_clients(TELEBIRR_API_KEY, CBE_BIRR_API_KEY)
    
    banner = """
╔══════════════════════════════════════════════════════════════╗
║                    HASET BINGO BOT                         ║
║                     ROUND-BASED GAME                         ║
║                   FRAUD PREVENTION SYSTEM                    ║
║           WITH TELEBIRR & CBE BIRR API INTEGRATION           ║
║                WITH SAFE DATABASE RESTORE                    ║
╚══════════════════════════════════════════════════════════════╝
    """
    print(banner)
    
    print("\n" + "="*60)
    print("🎯 HASET BINGO - ENHANCED EDITION 🎯")
    print("="*60)
    print(f"💰 Currency: {currency.upper()}")
    print(f"🎟️  Card Price: {card_price:.2f} {currency}")
    print(f"💸 Minimum Withdrawal: {MINIMUM_WITHDRAWAL_AMOUNT:.2f} {currency}")
    print(f"📱 Payment Phone: {PAYMENT_PHONE_NUMBER}")
    print(f"👤 Receiver Name: {PAYMENT_RECEIVER_NAME}")
    print(f"🆘 Support: {SUPPORT_TELEGRAM_USER}")
    print(f"🛡️ Fraud Prevention: ENABLED")
    print(f"🌐 Telebirr Primary API: {TELEBIRR_VERIFICATION_API_URL} (POST)")
    print(f"🌐 Telebirr Secondary API: {TELEBIRR_VERIFICATION_API_URL_2} (GET)")
    print(f"🌐 CBE Birr API: {CBE_BIRR_VERIFICATION_API_URL}")
    print(f"🔑 Telebirr API Key: {'Configured' if TELEBIRR_API_KEY else 'Not Configured'}")
    print(f"🔑 CBE Birr API Key: {'Configured' if CBE_BIRR_API_KEY else 'Not Configured'}")
    print("="*60)
    
    from aiogram import Bot, Dispatcher, types
    from aiogram.contrib.fsm_storage.memory import MemoryStorage
    from aiogram.types import ParseMode
    from aiogram.dispatcher import FSMContext
    from aiogram.dispatcher.filters.state import State, StatesGroup
    from aiogram.dispatcher.filters import Command
    
    bot = Bot(token=BOT_TOKEN)
    
    # ==================== INITIALIZE NOTIFICATION QUEUE ====================
    try:
        from web_server import notification_queue, set_bot_instance
        # Get the current event loop
        loop = asyncio.get_running_loop()
        # Set bot and loop in queue
        notification_queue.set_bot(bot, loop)
        # Start the queue processor
        notification_queue.start(loop)
        # Register bot instance for backward compatibility
        set_bot_instance(bot)
        logger.info("✅ Registered bot with notification queue and web_server")
    except Exception as e:
        logger.error(f"❌ Failed to initialize notification queue: {e}")
        import traceback
        traceback.print_exc()
    
    storage = MemoryStorage()
    dp = Dispatcher(bot, storage=storage)
    
    # ==================== ENHANCED COMMAND STATES ====================
    class DepositStates(StatesGroup):
        waiting_for_payment_method = State()
        waiting_for_transaction_proof = State()

    class WithdrawalStates(StatesGroup):
        waiting_for_amount = State()
        waiting_for_payment_method = State()
        waiting_for_full_name = State()
        waiting_for_phone_number = State()

    # New state for database restore
    class DatabaseRestoreStates(StatesGroup):
        waiting_for_file = State()

    seen_start_users = set()

    # ==================== ENHANCED COMMAND HANDLERS ====================

    @dp.message_handler(Command("start"))
    async def cmd_start_enhanced(message: types.Message):
        user_id = message.from_user.id
        first_name = message.from_user.first_name or "ተጫዋች"
        
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

🌟 *እንዴት መጀመር እንደሚቻለ*:
1️⃣ /play ብለው ጨዋታውን ይጀምሩ
2️⃣ ከ 400 የተለያዩ ካርዶች ውስጥ አንዱን ይምረጡ
3️⃣ ቁጥሮች ሲጠሩ በካርድዎ ላይ ያድርጉባቸው
4️⃣ 5 ቁጥሮች በአንድ መስመር ሲያስተካክሉ - ቢንጎ! 🎯

⏰ *የግዢ ጊዜ*: 30 ሰከንድ በእያንዳንዱ ሮውንድ

📊 *ቀሪ ሒሳብዎን ለማየት*: /balance
📖 *ህጎች ለማወቅ*: /instructions
🆘 *እርዳታ ለማግኘት*: /support

{f"💬 *ድጋፍ*: {SUPPORT_TELEGRAM_USER}" if SUPPORT_TELEGRAM_USER else ""}
            """
        else:
            welcome_message = f"""
✨✨ *እንኳን ተመለሱ {first_name}!* ✨✨

🎮 *Haset Bingo እንደገና አርበዎታል!* 🎮

🚀 *ፈጣን ትእዛዞች*:
• /play - አዲስ ጨዋታ ይጀምሩ
• /balance - ቀሪ ሒሳብዎን ይመልከቱ
• /deposit - ገንዘብ ያስገቡ
• /withdraw - ገንዘብ ያውጡ

🌟 *አዲስ ባህሪያት*:
• ⭐ አዲስ ካርዶች በእያንዳንዱ ጨዋታ
• 🏆 የድል ማስታወቂያዎች
• 🔄 ለሁሉም ተጫዋቾች እኩል እድል

{f"💬 *ድጋፍ*: {SUPPORT_TELEGRAM_USER}" if SUPPORT_TELEGRAM_USER else ""}
            """
        
        from config import ADMIN_IDS
        is_admin = user_id in ADMIN_IDS
        
        if is_admin:
            welcome_message += f"\n\n👑 *የአስተዳዳሪ ትእዛዞች:*\n"
            welcome_message += "• /admin - አስተዳዳሪ ፓነል\n"
            welcome_message += "• /adminpanel - ድር ፓነል ይክፈቱ\n"
            welcome_message += "• /stats - ስታቲስቲክስ\n"
            welcome_message += "• /pendingdeposits - በመጠባበቅ ላይ ያሉ ክፍያዎች\n"
            welcome_message += "• /getdb - የውሂብ ጎታ ያውርዱ (Download database)\n"
            welcome_message += "• /restoredb - የውሂብ ጎታ ወደነበረበት ይመልሱ (SAFE - Restore & Restart)\n"
        
        welcome_message += f"\n💡 *ምክር*: 'Play Bingo' የሚለውን ሜኑ ቁልፍ ጫን ሁሉም የሚገኙ ትእዛዞችን ለማየት!"
        
        await message.answer(welcome_message, parse_mode=ParseMode.MARKDOWN)

    @dp.message_handler(Command("deposit"))
    async def cmd_deposit_enhanced(message: types.Message, state: FSMContext):
        user_id = message.from_user.id
        
        # Create keyboard with Cancel button - ONLY TELEBIRR OPTION (CBE BIRR REMOVED)
        keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, selective=True)
        keyboard.add("ቴሌ ብር")
        keyboard.add("Cancel")
        
        await message.answer(
            f"💵 *የገንዘብ ክፍያ ሂደት*\n\n"
            f"💳 እባክዎ የክፍያ ዘዴዎን ይምረጡ፡\n"
            f"ገንዘብ ለማስገባት ቴሌብር ብቻ ይጠቀሙ።\n\n"
            f"❌ *ለማቋረጥ*: 'Cancel' ቁልፉን ይጫኑ",
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN
        )
        
        await DepositStates.waiting_for_payment_method.set()

    @dp.message_handler(state=DepositStates.waiting_for_payment_method)
    async def process_deposit_method_enhanced(message: types.Message, state: FSMContext):
        user_id = message.from_user.id
        
        # Check for Cancel at payment method selection
        if message.text and message.text.strip() == 'Cancel':
            await state.finish()
            await message.answer("❌ የገንዘብ ክፍያ ሂደት ተቋርጧል።", reply_markup=types.ReplyKeyboardRemove())
            return
        
        payment_method = message.text
        valid_methods = ["ቴሌ ብር"]  # ONLY TELEBIRR
        if payment_method not in valid_methods:
            # Re-show keyboard with Cancel
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
            await message.answer("❌ የፒሜንት ጥያቄ ለመፍጠር አልተቻለም። እባክዎ እንደገና ይሞክሩ።")
            return
        
        await state.update_data(payment_method=payment_method, payment_id=payment_id)
        
        masked_admin_phone = enhanced_payment_validator.mask_phone_number(PAYMENT_PHONE_NUMBER) if enhanced_payment_validator else PAYMENT_PHONE_NUMBER
        
        if payment_method == "ቴሌ ብር":
            instructions = f"💳 *የቴሌብር ክፍያ መመሪያዎች*\n\n"
            instructions += f"🏦 ዘዴ: {payment_method}\n"
            instructions += f"📋 የፒሜንት መታወቂያ: {payment_id}\n\n"
            instructions += f"1️⃣ ቴሌብር አፕዎን ይክፈቱ\n"
            instructions += f"2️⃣ የሚፈልጉትን መጠን ወደዚህ ይላኩ፡\n"
            instructions += f"   📱 ስልክ:+251989929742\n"
            instructions += f"   👤 ስም:Nebiyu \n\n"
            instructions += f"3️⃣ ከላኩ በኋላ፣ የማረጋገጫ መልእክት ይደርስዎታል\n"
            instructions += f"4️⃣ አጠቃላይ የግብይት መልእክቱን *COPY* ያድርጉ\n"
            instructions += f"5️⃣ እዚህ በቻት ውስጥ *PASTE* ያድርጉት\n\n"
        
        instructions += f"🔍 *ማስታወሻ:* ስርዓታችን በራስ-ሰር የግብይት መረጃዎን ያረጋግጣል!\n\n"
        instructions += f"እባክዎ የግብይት መልእክቱን ከታች ይጣበቁ፡\n"
        instructions += f"(❌ *ለማቋረጥ*: 'Cancel' ቁልፉን ይጫኑ)"
        
        # Remove keyboard before showing instructions
        await message.answer(instructions, reply_markup=types.ReplyKeyboardRemove(), parse_mode=ParseMode.MARKDOWN)
        
        # Show keyboard with Cancel for transaction proof
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
        user_id = message.from_user.id
        
        # Check for Cancel at transaction proof step
        if message.text and message.text.strip() == 'Cancel':
            await state.finish()
            await message.answer("❌ የገንዘብ ክፍያ ሂደት ተቋርጧል።", reply_markup=types.ReplyKeyboardRemove())
            return
        
        data = await state.get_data()
        payment_id = data.get('payment_id')
        payment_method = data.get('payment_method')
        
        if not payment_id:
            await state.finish()
            await message.answer("❌ የፒሜንት መረጃ አልተገኘም። እንደገና ይሞክሩ።")
            return
        
        if not message.text or message.text.strip() == "" or message.text.strip() == "WITHDRAW" or message.text.startswith('/'):
            # Show keyboard with Cancel again
            cancel_keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, selective=True)
            cancel_keyboard.add("Cancel")
            
            await message.answer(
                "❌ *ልክ ያልሆነ የክፍያ ማረጋገጫ!*\n\n"
                "⚠️ እባክዎ እውነተኛ የቴሌብር ማረጋገጫ SMS ይላኩ።\n\n"
                "❌ *ለማቋረጥ*: 'Cancel' ቁልፉን ይጫኑ",
                reply_markup=cancel_keyboard
            )
            return
        
        if payment_method == "ቴሌ ብር":
            await process_telebirr_transaction_enhanced(user_id, payment_id, message, state)
        else:
            await state.finish()
            await message.answer("❌ ያልተሰራ የክፍያ ዘዴ።")

    async def process_telebirr_transaction_enhanced(user_id: int, payment_id: int, message: types.Message, state: FSMContext):
        tx_id = enhanced_payment_validator.telebirr_scraper.extract_transaction_id(message.text)
        
        if not tx_id:
            await state.finish()
            await message.answer(
                "❌ *የግብይት መታወቂያ ማግኘት አልተቻለም!*\n\n"
                "⚠️ እባክዎ እውነተኛ የቴሌብር ማረጋገጫ SMS ይላኩ።\n",
                reply_markup=types.ReplyKeyboardRemove()
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
        
        # Remove keyboard during processing
        await message.answer(
            "🔍 *የቴሌብር ግብይት ማረጋገጫ በመስራት ላይ...*\n\n"
            f"📋 የፒሜንት መታወቂያ: {payment_id}\n"
            f"🔢 የግብይት መታወቂያ: {tx_id}\n\n"
            "⏳ እባክዎን ይጠበቁ፣ ይህ ጥቂት ሰከንዶች ሊወስድ ይችላል...",
            reply_markup=types.ReplyKeyboardRemove()
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
            await state.finish()
            
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
                    f"Auto-rejected: {', '.join(errors[:2]) if errors else 'Verification failed'}",
                    payment_id
                ))
            
            error_message = "🚨 *የቴሌብር ክፍያ ጥያቄ ተቋርጧል!*\n\n"
            error_message += "❌ የቴሌብር SMS ማረጋገጫዎ ተቀባይነት አላገኘም።\n\n"
            
            if errors:
                error_message += f"📝 *ምክንያቶች:*\n"
                for error in errors[:3]:
                    error_message += f"• {error}\n"
                error_message += "\n"
            
            error_message += "🔄 *እባክዎ፡*\n"
            error_message += "1. እውነተኛ የቴሌብር ማረጋገጫ SMS ይላኩ\n"
            error_message += "2. አዲስ የገንዘብ ክፍያ ጥያቄ ይጀምሩ\n\n"
            error_message += "🔒 *ማስታወሻ:* ብዙ የተቀቡ ጥያቄዎች ሂሳብዎን ሊያገዱ ይችላሉ!"
            
            await message.answer(error_message, parse_mode=ParseMode.MARKDOWN, reply_markup=types.ReplyKeyboardRemove())
            return
        
        success = await auto_approve_deposit(
            user_id, payment_id, amount, tx_id, message.text, api_result, "Telebirr"
        )
        
        if success:
            await message.answer(
                "🎉 *ቴሌብር ክፍያዎ በራስ-ሰር ፈቅዷል!*\n\n"
                f"✅ ገንዘብዎ በቀሪ ሒሳብዎ ላይ ተጨምሯል!\n"
                f"💰 *መጠን:* {amount:.2f} {currency}\n"
                f"📋 *የፒሜንት መታወቂያ:* {payment_id}\n"
                f"🔢 *የግብይት መታወቂያ:* {tx_id}\n\n"
                f"🔍 *የድር ማረጋገጫ ተሳክቷል!*\n\n"
                f"🚀 አሁን ቢንጎ መጫወት መጀመር ይችላሉ!\n"
                f"🎮 ለመጫወት: /play\n"
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

    @dp.message_handler(Command("withdraw"))
    async def cmd_withdraw_enhanced(message: types.Message, state: FSMContext):
        user_id = message.from_user.id
        
        from database.db import Database
        user = await Database.get_user(user_id)
        
        if not user:
            await message.answer("❌ በመጀመሪያ መዝግበዎ ያስፈልጋል። /start ብለው ይጀምሩ።")
            return
        
        balance = user.get('balance', 0.00)
        
        if balance < MINIMUM_WITHDRAWAL_AMOUNT:
            await message.answer(
                f"⚠️ *ዝቅተኛ ቀሪ ሒሳብ!*\n\n"
                f"💰 የእርስዎ ቀሪ ሒሳብ: {balance:.2f} {currency}\n"
                f"📊 ዝቅተኛ ማውጣት: {MINIMUM_WITHDRAWAL_AMOUNT:.2f} {currency}\n\n"
                f"💳 ቀሪ ሒሳብዎን ለመጨመር: /deposit"
            )
            return
        
        keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, selective=True)
        keyboard.add("Cancel")
        
        await message.answer(
            f"💸 *የገንዘብ ማውጣት ሂደት*\n\n"
            f"💰 የእርስዎ ቀሪ ሒሳብ: {balance:.2f} {currency}\n"
            f"📊 ዝቅተኛ ማውጣት: {MINIMUM_WITHDRAWAL_AMOUNT:.2f} {currency}\n\n"
            f"📝 እባክዎ የሚያውጡትን የገንዘብ መጠን ያስገቡ፡\n\n"
            f"❌ *ለማቋረጥ*: 'Cancel' ቁልፉን ይጫኑ",
            reply_markup=keyboard
        )
        
        await WithdrawalStates.waiting_for_amount.set()

    @dp.message_handler(state=WithdrawalStates.waiting_for_amount)
    async def process_withdrawal_amount_enhanced(message: types.Message, state: FSMContext):
        user_id = message.from_user.id
        
        if message.text and message.text.strip() == 'Cancel':
            await state.finish()
            await message.answer("❌ የገንዘብ ማውጣት ሂደት ተቋርጧል።", reply_markup=types.ReplyKeyboardRemove())
            return
        
        try:
            amount = float(message.text.replace(',', '').strip())
            
            if amount < MINIMUM_WITHDRAWAL_AMOUNT:
                keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, selective=True)
                keyboard.add("Cancel")
                
                await message.answer(
                    f"⚠️ *ዝቅተኛ የማውጣት መጠን!*\n\n"
                    f"💰 የጠየቁት መጠን: {amount:.2f} {currency}\n"
                    f"📊 ዝቅተኛ ማውጣት: {MINIMUM_WITHDRAWAL_AMOUNT:.2f} {currency}\n\n"
                    f"📝 እባክዎ ከ {MINIMUM_WITHDRAWAL_AMOUNT:.2f} በላይ መጠን ያስገቡ።\n\n"
                    f"❌ *ለማቋረጥ*: 'Cancel' ቁልፉን ይጫኑ",
                    reply_markup=keyboard
                )
                return
            
            from database.db import Database
            user = await Database.get_user(user_id)
            balance = user.get('balance', 0.00)
            
            if amount > balance:
                keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, selective=True)
                keyboard.add("Cancel")
                
                await message.answer(
                    f"⚠️ *በቂ ቀሪ ሒሳብ የለም!*\n\n"
                    f"💰 የጠየቁት መጠን: {amount:.2f} {currency}\n"
                    f"🏦 የእርስዎ ቀሪ ሒሳብ: {balance:.2f} {currency}\n\n"
                    f"💳 ቀሪ ሒሳብዎን ለመጨመር: /deposit\n\n"
                    f"❌ *ለማቋረጥ*: 'Cancel' ቁልፉን ይጫኑ",
                    reply_markup=keyboard
                )
                return
            
            await state.update_data(withdrawal_amount=amount)
            
            keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, selective=True)
            keyboard.add("ቴሌ ብር")
            # CBE BIRR OPTION REMOVED FROM WITHDRAWAL
            keyboard.add("Cancel")
            
            await message.answer(
                f"✅ *መጠን ተቀብሏል!*\n\n"
                f"💰 የጠየቁት መጠን: {amount:.2f} {currency}\n\n"
                f"💳 እባክዎ የክፍያ ዘዴዎን ይምረጡ፡\n\n"
                f"❌ *ለማቋረጥ*: 'Cancel' ቁልፉን ይጫኑ",
                reply_markup=keyboard
            )
            
            await WithdrawalStates.waiting_for_payment_method.set()
            
        except ValueError:
            keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, selective=True)
            keyboard.add("Cancel")
            
            await message.answer(
                "❌ *ልክ ያልሆነ መጠን!*\n\n"
                "📝 እባክዎ ትክክለኛ የገንዘብ መጠን ያስገቡ።\n"
                "ምሳሌ: 100, 150.50, 200.00\n\n"
                f"❌ *ለማቋረጥ*: 'Cancel' ቁልፉን ይጫኑ",
                reply_markup=keyboard
            )

    @dp.message_handler(state=WithdrawalStates.waiting_for_payment_method)
    async def process_withdrawal_method_enhanced(message: types.Message, state: FSMContext):
        user_id = message.from_user.id
        
        if message.text and message.text.strip() == 'Cancel':
            await state.finish()
            await message.answer("❌ የገንዘብ ማውጣት ሂደት ተቋርጧል።", reply_markup=types.ReplyKeyboardRemove())
            return
        
        payment_method = message.text
        valid_methods = ["ቴሌ ብር"]  # ONLY TELEBIRR FOR WITHDRAWAL
        
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
        
        await state.update_data(payment_method=payment_method)
        
        keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, selective=True)
        keyboard.add("Cancel")
        
        await message.answer(
            f"✅ *የክፍያ ዘዴ ተመርጧል!*\n\n"
            f"🏦 ዘዴ: {payment_method}\n\n"
            f"📝 እባክዎ ሙሉ ስምዎን ያስገቡ፡\n"
            f"(ምሳሌ: አብዲስ አበባ)\n\n"
            f"❌ *ለማቋረጥ*: 'Cancel' ቁልፉን ይጫኑ",
            reply_markup=keyboard
        )
        
        await WithdrawalStates.waiting_for_full_name.set()

    @dp.message_handler(state=WithdrawalStates.waiting_for_full_name)
    async def process_withdrawal_full_name_enhanced(message: types.Message, state: FSMContext):
        user_id = message.from_user.id
        
        if message.text and message.text.strip() == 'Cancel':
            await state.finish()
            await message.answer("❌ የገንዘብ ማውጣት ሂደት ተቋርጧል።", reply_markup=types.ReplyKeyboardRemove())
            return
        
        full_name = message.text.strip()
        
        if len(full_name) < 2:
            keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, selective=True)
            keyboard.add("Cancel")
            
            await message.answer(
                "❌ *ሙሉ ስም ልክ ያልሆነ!*\n\n"
                "📝 እባክዎ ትክክለኛ ሙሉ ስምዎን ያስገቡ።\n\n"
                f"❌ *ለማቋረጥ*: 'Cancel' ቁልፉን ይጫኑ",
                reply_markup=keyboard
            )
            return
        
        await state.update_data(full_name=full_name)
        
        keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, selective=True)
        keyboard.add("Cancel")
        
        await message.answer(
            f"✅ *ሙሉ ስም ተቀብሏል!*\n\n"
            f"👤 ሙሉ ስም: {full_name}\n\n"
            f"📱 እባክዎ ስልክ ቁጥርዎን ያስገቡ፡\n"
            f"(ምሳሌ: +25190000000 ወይም 0900000000)\n\n"
            f"❌ *ለማቋረጥ*: 'Cancel' ቁልፉን ይጫኑ",
            reply_markup=keyboard
        )
        
        await WithdrawalStates.waiting_for_phone_number.set()

    @dp.message_handler(state=WithdrawalStates.waiting_for_phone_number)
    async def process_withdrawal_phone_number_enhanced(message: types.Message, state: FSMContext):
        user_id = message.from_user.id
        
        if message.text and message.text.strip() == 'Cancel':
            await state.finish()
            await message.answer("❌ የገንዘብ ማውጣት ሂደት ተቋርጧል።", reply_markup=types.ReplyKeyboardRemove())
            return
        
        phone_number = message.text.strip()
        
        phone_clean = re.sub(r'[^\d]', '', phone_number)
        
        if not (phone_clean.startswith('2519') and len(phone_clean) == 12) and \
           not (phone_clean.startswith('09') and len(phone_clean) == 10):
            keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, selective=True)
            keyboard.add("Cancel")
            
            await message.answer(
                "❌ *ልክ ያልሆነ ስልክ ቁጥር!*\n\n"
                "📱 እባክዎ ትክክለኛ ስልክ ቁጥር ያስገቡ።\n"
                "ምሳሌ: +251900000000 ወይም 0900000000\n\n"
                f"❌ *ለማቋረጥ*: 'Cancel' ቁልፉን ይጫኑ",
                reply_markup=keyboard
            )
            return
        
        data = await state.get_data()
        amount = data.get('withdrawal_amount')
        payment_method = data.get('payment_method')
        full_name = data.get('full_name')
        
        if phone_clean.startswith('09'):
            formatted_phone = '+251' + phone_clean[1:]
        elif phone_clean.startswith('251'):
            formatted_phone = '+' + phone_clean
        else:
            formatted_phone = phone_number
        
        withdrawal_id = await create_withdrawal_request(user_id, amount, payment_method, full_name, formatted_phone)
        
        if not withdrawal_id:
            await state.finish()
            await message.answer("❌ የገንዘብ ማውጣት ጥያቄ ለመፍጠር አልተቻለም። እባክዎ እንደገና ይሞክሩ።")
            return
        
        await state.finish()
        
        await message.answer(
            f"✅ *የገንዘብ ማውጣት ጥያቄ ተላልፏል!*\n\n"
            f"📋 *የማውጣት መታወቂያ:* {withdrawal_id}\n"
            f"💰 *መጠን:* {amount:.2f} {currency}\n"
            f"🏦 *ዘዴ:* {payment_method}\n"
            f"👤 *ሙሉ ስም:* {full_name}\n"
            f"📱 *ስልክ:* {formatted_phone}\n\n"
            f"⏳ *ሁኔታ:* በአስተዳዳሪዎች ፍቃድ በመጠባበቅ ላይ\n\n"
            f"✅ የገንዘብ ማውጣት ጥያቄዎ ለአስተዳዳሪዎቻችን ለማረጋገጥ ቀርቧል።\n"
            f"📬 እንዲፈቀድለት ወይም እንዲተው ሲደረግ ማሳወቂያ ይደርስዎታል።\n"
            f"⏰ የማቀነባበሪያ ጊዜ፡ ብዙውን ጊዜ በ24 ሰዓታት ውስጥ",
            reply_markup=types.ReplyKeyboardRemove()
        )
        
        from config import ADMIN_IDS
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(
                    admin_id,
                    f"📢 *አዲስ የገንዘብ ማውጣት ጥያቄ!*\n\n"
                    f"👤 ተጠቃሚ: {user_id}\n"
                    f"📋 መታወቂያ: {withdrawal_id}\n"
                    f"💰 መጠን: {amount:.2f} {currency}\n"
                    f"🏦 ዘዴ: {payment_method}\n"
                    f"👤 ስም: {full_name}\n"
                    f"📱 ስልክ: {formatted_phone}\n\n"
                    f"📊 ለማረጋገጥ: /pendingwithdrawals",
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception as e:
                logger.error(f"Failed to notify admin {admin_id}: {e}")

    @dp.message_handler(Command("play"))
    async def cmd_play_enhanced(message: types.Message):
        user_id = message.from_user.id
        
        from config import WEB_APP_URL, WEBSERVER_HOST, WEBSERVER_PORT
        if WEB_APP_URL:
            webapp_url = f"{WEB_APP_URL}/game.html?user_id={user_id}"
        else:
            webapp_url = f"http://{WEBSERVER_HOST}:{WEBSERVER_PORT}/game.html?user_id={user_id}"
        
        keyboard = types.InlineKeyboardMarkup(
            inline_keyboard=[
                [types.InlineKeyboardButton(
                    text="🎮 ቢንጎ ተጫውት",
                    web_app=types.WebAppInfo(url=webapp_url)
                )]
            ]
        )
        
        await message.answer(
            "🎯 ቢንጎ 🎯\n\n"
            "✨ ጨዋታውን ለመጀመር ከታች ያለውን ቁልፍ ይጫኑ!\n\n"
            f"🎟️ የካርድ ዋጋ: {card_price:.2f} {currency}",
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN
        )

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
                f"💳 *ገንዘብ ለማስገባት:* /deposit\n"
                f"💸 *ገንዘብ ለማውጣት:* /withdraw\n\n"
                f"🆘 እርዳታ ያስፈልግዎታል? /support",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await message.answer(f"⚠️ ቀሪ ሒሳብዎን ማግኘት አልተቻለም። እባክዎን እንደገና ይሞክሩ።")

    @dp.message_handler(Command("instructions"))
    async def cmd_instructions_enhanced(message: types.Message):
        from config import GAME_CONFIG
        card_price = GAME_CONFIG.get('card_price', 10.00)
        
        await message.answer(
            "📖 *የቢንጎ ጨዋታ ህጎች እና መመሪያዎች*\n\n"
            f"🎟️ የካርድ ዋጋ: {card_price:.2f} {currency}\n"
            f"💰 ዝቅተኛ ማውጣት: {MINIMUM_WITHDRAWAL_AMOUNT:.2f} {currency}\n\n"
            "🎮 እንዴት መጫወት እንደሚቻል:\n"
            "1️⃣ /play ብለው ጨዋታውን ይጀምሩ\n"
            "2️⃣ ካርድ ይግዙ\n"
            "3️⃣ ቁጥሮች ሲጠሩ በካርድዎ ላይ ምልክት ያድርጉ\n"
            "4️⃣ 5 ቁጥሮች በአንድ መስመር ሲያስተካክሉ - ቢንጎ! 🎯\n\n"
            f"🆘 ድጋፍ: {SUPPORT_TELEGRAM_USER}",
            parse_mode=ParseMode.MARKDOWN
        )

    @dp.message_handler(Command("support"))
    async def cmd_support_enhanced(message: types.Message):
        await message.answer(
            f"🆘 *ድጋፍ እና እርዳታ*\n\n"
            f"*📱 የቴሌግራም ድጋፍ:* {SUPPORT_TELEGRAM_USER}\n\n"
            "*📞 ለሚከተሉት እርዳታ ያግኙን:*\n"
            "• የጨዋታ ችግሮች\n"
            "• የገንዘብ ክፍያ/ማውጣት ጥያቄዎች\n"
            "• የሂሳብ ችግሮች\n"
            "• የቴክኒካር ችግሮች\n\n"
            "*⏰ የድጋፍ ሰዓት:* 24/7",
            parse_mode=ParseMode.MARKDOWN
        )

    @dp.message_handler(Command("history"))
    async def cmd_history_enhanced(message: types.Message):
        user_id = message.from_user.id
        
        try:
            from database.db import Database
            user = await Database.get_user(user_id)
            
            if not user:
                await message.answer("❌ መጀመሪያ መዝግበዎ ያስፈልጋል። /start ብለው ይጀምሩ።")
                return
            
            with Database.get_cursor() as cursor:
                cursor.execute("PRAGMA table_info(games)")
                columns = cursor.fetchall()
                
                if not columns:
                    await message.answer("📜 እስካሁን ምንም የጨዋታ ታሪክ የሎትም።\n\n🎮 መጀመሪያ ጨዋታዎን ይጀምሩ: /play")
                    return
                
                cursor.execute("""
                    SELECT id, card_numbers, status, created_at 
                    FROM games 
                    WHERE user_id = ? 
                    ORDER BY created_at DESC 
                    LIMIT 10
                """, (user_id,))
                games = cursor.fetchall()
                
                if not games:
                    await message.answer("📜 እስካሁን ምንም የጨዋታ ታሪክ የሎትም።\n\n🎮 መጀመሪያ ጨዋታዎን ይጀምሩ: /play")
                    return
                
                history_text = "📜 *የጨዋታ ታሪክዎ*\n\n"
                
                for game in games:
                    game_id = game['id'] if 'id' in game else 0
                    card_numbers = game['card_numbers'] if 'card_numbers' in game else "N/A"
                    status = game['status'] if 'status' in game else "unknown"
                    created_at = game['created_at'] if 'created_at' in game else ""
                    
                    time_str = ""
                    try:
                        if isinstance(created_at, str):
                            if created_at:
                                time_str = created_at[:16]
                            else:
                                time_str = "Unknown"
                        elif hasattr(created_at, 'strftime'):
                            time_str = created_at.strftime('%Y-%m-%d %H:%M')
                        else:
                            time_str = str(created_at)[:16]
                    except:
                        time_str = "Unknown"
                    
                    if status.lower() == 'won':
                        status_emoji = "🏆"
                        status_text = "ደስተኛ"
                    elif status.lower() == 'lost':
                        status_emoji = "💔"
                        status_text = "የተሸነፈ"
                    elif status.lower() == 'active':
                        status_emoji = "⏳"
                        status_text = "በሂደት ላይ"
                    else:
                        status_emoji = "📋"
                        status_text = status
                    
                    card_display = card_numbers
                    if len(card_numbers) > 30:
                        card_display = card_numbers[:27] + "..."
                    
                    history_text += f"{status_emoji} *ጨዋታ {game_id}* - {time_str}\n"
                    history_text += f"📋 ሁኔታ: {status_text}\n"
                    history_text += f"🎟️ ካርድ: {card_display}\n"
                    history_text += "─" * 20 + "\n"
            
            history_text += f"\n🎮 አዲስ ጨዋታ ለመጀመር: /play"
            
            await message.answer(history_text, parse_mode=ParseMode.MARKDOWN)
            
        except Exception as e:
            logger.error(f"Error fetching history for user {user_id}: {e}")
            await message.answer("⚠️ የጨዋታ ታሪክዎን ማግኘት አልተቻለም። እባክዎ ቆይተው እንደገና ይሞክሩ።")

    @dp.message_handler(Command("admin"))
    async def cmd_admin_enhanced(message: types.Message):
        from config import ADMIN_IDS
        
        user_id = message.from_user.id
        if user_id not in ADMIN_IDS:
            await message.answer("⛔ ይህ ትእዛዝ ለአስተዳዳሪዎች ብቻ ነው።")
            return
        
        from database.db import Database
        
        with Database.get_cursor() as cursor:
            cursor.execute("SELECT COUNT(*) as count FROM users")
            user_count = cursor.fetchone()['count']
            
            cursor.execute("SELECT COUNT(*) as count FROM games WHERE status = 'active'")
            active_games = cursor.fetchone()['count']
            
            cursor.execute("SELECT SUM(amount) as total FROM transactions WHERE transaction_type = 'card_purchase'")
            card_sales = cursor.fetchone()['total'] or 0
            
            cursor.execute("SELECT COUNT(*) as count FROM payments WHERE status = 'pending'")
            pending_deposits = cursor.fetchone()['count']
            
            cursor.execute("SELECT COUNT(*) as count FROM withdrawal_requests WHERE status = 'pending'")
            pending_withdrawals = cursor.fetchone()['count']
        
        admin_panel = f"""
👑 *አስተዳዳሪ ፓነል*

📊 *ስታቲስቲክስ*
👥 ተጠቃሚዎች: {user_count}
🎮 ንቁ ጨዋታዎች: {active_games}
💰 ካርድ ሽያጭ: {card_sales:.2f} {currency}
⏳ በመጠባበቅ ላይ ያሉ ክፍያዎች: {pending_deposits}
⏳ በመጠባበቅ ላይ ያሉ የገንዘብ ማውጣቶች: {pending_withdrawals}

⚡ *ፈጣን ትእዛዞች*
• /pendingdeposits - በመጠባበቅ ላይ ያሉ ክፍያዎች
• /pendingwithdrawals - በመጠባበቅ ላይ ያሉ የገንዘብ ማውጣቶች
• /stats - ዝርዝር ስታቲስቲክስ
• /adminpanel - ድር ፓነል ይክፈቱ
• /getdb - የውሂብ ጎታ ያውርዱ (Download database)
• /restoredb - የውሂብ ጎታ ወደነበረበት ይመልሱ (SAFE - Restore & Restart)
    """
        
        await message.answer(admin_panel, parse_mode=ParseMode.MARKDOWN)

    # ==================== DATABASE BACKUP COMMAND ====================
    @dp.message_handler(Command("getdb"))
    async def cmd_get_database(message: types.Message):
        """Admin command to download database file"""
        from config import ADMIN_IDS
        
        user_id = message.from_user.id
        if user_id not in ADMIN_IDS:
            await message.answer("⛔ This command is for admins only.")
            return
        
        # Send "processing" message (plain text, no markdown)
        status_msg = await message.answer("📦 Preparing database file...")
        
        try:
            from database.db import Database
            import os
            import tempfile
            import shutil
            from datetime import datetime
            
            # Get database path from Database class
            db_path = getattr(Database, '_db_path', 'habesha_bingo.db')
            logger.info(f"Looking for database at: {db_path}")
            
            # If path doesn't exist, try common locations
            if not os.path.exists(db_path):
                possible_paths = [
                    'habesha_bingo.db',
                    '/app/habesha_bingo.db',
                    './habesha_bingo.db',
                    '/data/habesha_bingo.db',
                    os.path.join(os.getcwd(), 'habesha_bingo.db')
                ]
                for path in possible_paths:
                    if os.path.exists(path):
                        db_path = path
                        logger.info(f"Found database at: {db_path}")
                        break
            
            if not os.path.exists(db_path):
                await status_msg.edit_text(
                    "❌ Database file not found!\n\n"
                    f"🔍 Searched in:\n- " + "\n- ".join(possible_paths)
                )
                return
            
            # Create a temporary copy with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            temp_dir = tempfile.mkdtemp()
            temp_path = os.path.join(temp_dir, f"habesha_bingo_{timestamp}.db")
            
            # Copy database to temp location (to avoid locking issues)
            shutil.copy2(db_path, temp_path)
            logger.info(f"Created temp copy at: {temp_path}")
            
            # Get file size
            file_size_bytes = os.path.getsize(temp_path)
            file_size_mb = file_size_bytes / (1024 * 1024)
            
            # Get record counts
            records = []
            try:
                with Database.get_cursor() as cursor:
                    tables = ['users', 'games', 'player_cards', 'transactions', 'commission_records']
                    for table in tables:
                        try:
                            cursor.execute(f"SELECT COUNT(*) as count FROM {table}")
                            result = cursor.fetchone()
                            if result:
                                records.append(f"{table}: {result['count']}")
                        except:
                            pass
                record_counts = " | ".join(records) if records else "N/A"
            except:
                record_counts = "N/A"
            
            await status_msg.edit_text(
                f"✅ Database prepared!\n"
                f"📁 Size: {file_size_mb:.2f} MB\n"
                f"📊 {record_counts}\n"
                f"⏱️ Sending file..."
            )
            
            # Send the file with PLAIN TEXT caption (no markdown)
            with open(temp_path, 'rb') as f:
                await message.reply_document(
                    document=f,
                    caption=f"📊 Haset Bingo Database Backup\n"
                           f"🕐 {timestamp}\n"
                           f"📁 Size: {file_size_mb:.2f} MB\n"
                           f"📊 {record_counts}"
                )
            
            # Clean up temp directory
            shutil.rmtree(temp_dir, ignore_errors=True)
            logger.info("Temporary files cleaned up")
            
            await status_msg.delete()
            
        except Exception as e:
            await status_msg.edit_text(f"❌ Error: {str(e)[:200]}")
            logger.error(f"Error sending database: {e}", exc_info=True)

    # ==================== DATABASE RESTORE COMMAND (SAFE VERSION WITH FIXED MARKDOWN) ====================
    @dp.message_handler(Command("restoredb"))
    async def cmd_restore_database(message: types.Message, state: FSMContext):
        """Admin command to safely restore database from backup file with auto-restart"""
        from config import ADMIN_IDS
        
        user_id = message.from_user.id
        if user_id not in ADMIN_IDS:
            await message.answer("⛔ This command is for admins only.")
            return
        
        # Send warning message with proper escaping
        warning_msg = (
            "⚠️ ⚠️ DATABASE RESTORE WARNING ⚠️\n\n"
            "This will COMPLETELY REPLACE the current database with the uploaded file.\n\n"
            "SAFE RESTORE PROCESS:\n"
            "✅ Automatically creates backup of current database\n"
            "✅ Gracefully shuts down all bot operations\n"
            "✅ Closes all database connections\n"
            "✅ Validates uploaded file for corruption\n"
            "✅ Safely replaces the database file\n"
            "✅ Automatically restarts the bot\n\n"
            "IMPORTANT:\n"
            "• All current data will be REPLACED\n"
            "• Bot will RESTART automatically\n"
            "• Users will be temporarily disconnected\n\n"
            "Please upload the database file you want to restore.\n"
            "(Supported format: SQLite .db files, max 100 MB)\n\n"
            "❌ Type /cancel to abort."
        )
        
        await message.answer(warning_msg)
        
        # Create keyboard with Cancel button
        keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, selective=True)
        keyboard.add("Cancel")
        
        await message.answer(
            "📤 Please upload the database file:",
            reply_markup=keyboard
        )
        
        await DatabaseRestoreStates.waiting_for_file.set()

    @dp.message_handler(state=DatabaseRestoreStates.waiting_for_file, content_types=types.ContentTypes.DOCUMENT)
    async def process_database_restore_file(message: types.Message, state: FSMContext):
        """Process uploaded database file for safe restore"""
        from config import ADMIN_IDS
        
        user_id = message.from_user.id
        if user_id not in ADMIN_IDS:
            await state.finish()
            await message.answer("⛔ Unauthorized.", reply_markup=types.ReplyKeyboardRemove())
            return
        
        document = message.document
        
        # Check if it's a database file
        if not document.file_name.endswith('.db'):
            await message.answer(
                "❌ Invalid file type. Please upload a SQLite database file (.db)",
                reply_markup=types.ReplyKeyboardRemove()
            )
            await state.finish()
            return
        
        # Send initial processing message (this will be our status message) - WITHOUT MARKDOWN
        status_msg = await message.answer(
            "⏳ SAFE RESTORE PROCESS INITIATED\n\n"
            "⬇️ Step 1/6: Downloading file...",
            reply_markup=types.ReplyKeyboardRemove()
        )
        
        try:
            # Create temp directory
            temp_dir = tempfile.mkdtemp()
            temp_file_path = os.path.join(temp_dir, document.file_name)
            
            # Download file
            file = await bot.get_file(document.file_id)
            await bot.download_file(file.file_path, temp_file_path)
            
            logger.info(f"Admin {user_id} uploaded database file for restore: {document.file_name} ({file.file_size} bytes)")
            
            # Update status - Step 2 - WITHOUT MARKDOWN
            try:
                await status_msg.edit_text(
                    "⏳ SAFE RESTORE PROCESS\n\n"
                    "✅ Step 1/6: File downloaded\n"
                    "🔄 Step 2/6: Validating file...\n"
                    f"📁 File: {document.file_name}\n"
                    f"📊 Size: {file.file_size / (1024*1024):.2f} MB"
                )
            except Exception as e:
                # If edit fails, send new message
                logger.warning(f"Could not edit message, sending new one: {e}")
                status_msg = await message.answer(
                    "⏳ SAFE RESTORE PROCESS\n\n"
                    "✅ Step 1/6: File downloaded\n"
                    "🔄 Step 2/6: Validating file...\n"
                    f"📁 File: {document.file_name}\n"
                    f"📊 Size: {file.file_size / (1024*1024):.2f} MB"
                )
            
            # Call the safe restore function
            success, message_text = await restore_database_from_file(temp_file_path, user_id, message, status_msg)
            
            # Clean up temp directory
            shutil.rmtree(temp_dir, ignore_errors=True)
            
            if success:
                # This message may not be sent if bot restarts immediately
                try:
                    await message.answer(
                        f"✅ {message_text}\n\n"
                        f"🔄 Bot is restarting..."
                    )
                except:
                    pass
            else:
                await message.answer(f"❌ {message_text}")
            
        except Exception as e:
            logger.error(f"Error in database restore: {e}", exc_info=True)
            await message.answer(f"❌ Error: {str(e)[:200]}")
            
        await state.finish()

    @dp.message_handler(state=DatabaseRestoreStates.waiting_for_file, content_types=types.ContentTypes.TEXT)
    async def process_database_restore_cancel(message: types.Message, state: FSMContext):
        """Handle cancel during file upload"""
        if message.text and message.text.strip() == 'Cancel':
            await state.finish()
            await message.answer("❌ Database restore cancelled.", reply_markup=types.ReplyKeyboardRemove())
        else:
            # User sent text instead of file
            keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, selective=True)
            keyboard.add("Cancel")
            
            await message.answer(
                "❌ Please upload a database file (.db) or type Cancel to abort.",
                reply_markup=keyboard
            )

    @dp.message_handler(Command("pendingdeposits"))
    async def cmd_pendingdeposits_enhanced(message: types.Message):
        from config import ADMIN_IDS
        
        user_id = message.from_user.id
        if user_id not in ADMIN_IDS:
            await message.answer("⛔ ይህ ትእዛዝ ለአስተዳዳሪዎች ብቻ ነው።")
            return
        
        try:
            from database.db import Database
            pending_payments = await Database.get_pending_payments()
            
            if not pending_payments:
                await message.answer("✅ ምንም በመጠባበቅ ላይ ያሉ ክፍያዎች የሉም።")
                return
            
            response = "⏳ *በመጠባበቅ ላይ ያሉ ክፍያዎች*\n\n"
            
            for payment in pending_payments:
                payment_id = payment['id']
                user_id_val = payment['user_id']
                amount = payment['amount']
                method = payment['payment_method']
                created = payment['created_at']
                
                if isinstance(created, str):
                    time_str = created
                else:
                    time_str = created.strftime('%Y-%m-%d %H:%M')
                
                response += f"📋 *ፒሜንት {payment_id}*\n"
                response += f"👤 ተጠቃሚ: {user_id_val}\n"
                response += f"💰 መጠን: {amount:.2f} {currency}\n"
                response += f"🏦 ዘዴ: {method}\n"
                response += f"⏰ ጊዜ: {time_str}\n"
                response += f"✅ ለማጽደቅ: /approvedeposit {payment_id}\n"
                response += "─" * 20 + "\n"
            
            await message.answer(response, parse_mode=ParseMode.MARKDOWN)
            
        except Exception as e:
            await message.answer(f"❌ ስህተት: {str(e)[:100]}")

    @dp.message_handler(Command("pendingwithdrawals"))
    async def cmd_pendingwithdrawals_enhanced(message: types.Message):
        from config import ADMIN_IDS
        
        user_id = message.from_user.id
        if user_id not in ADMIN_IDS:
            await message.answer("⛔ ይህ ትእዛዝ ለአስተዳዳሪዎች ብቻ ነው።")
            return
        
        try:
            from database.db import Database
            pending_withdrawals = await Database.get_pending_withdrawals()
            
            if not pending_withdrawals:
                await message.answer("✅ ምንም በመጠባበቅ ላይ ያሉ የገንዘብ ማውጣቶች የሉም።")
                return
            
            response = "⏳ *በመጠባበቅ ላይ ያሉ የገንዘብ ማውጣቶች*\n\n"
            
            for withdrawal in pending_withdrawals:
                withdrawal_id = withdrawal['id']
                user_id_val = withdrawal['user_id']
                amount = withdrawal['amount']
                method = withdrawal.get('payment_method', withdrawal.get('method', 'Unknown'))
                full_name = withdrawal.get('full_name', 'N/A')
                phone = withdrawal.get('phone_number', 'N/A')
                created = withdrawal.get('created_at') or withdrawal.get('requested_at')
                
                if isinstance(created, str):
                    time_str = created
                else:
                    time_str = created.strftime('%Y-%m-%d %H:%M') if created else 'Unknown'
                
                response += f"📋 *ማውጣት {withdrawal_id}*\n"
                response += f"👤 ተጠቃሚ: {user_id_val}\n"
                response += f"💰 መጠን: {amount:.2f} {currency}\n"
                response += f"🏦 ዘዴ: {method}\n"
                response += f"👤 ስም: {full_name}\n"
                response += f"📱 ስልክ: {phone}\n"
                response += f"⏰ ጊዜ: {time_str}\n"
                response += f"✅ ለማጽደቅ: /approvewithdrawal {withdrawal_id}\n"
                response += "─" * 20 + "\n"
        
            await message.answer(response, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            await message.answer(f"❌ ስህተት: {str(e)[:100]}")

    @dp.message_handler(Command("adminpanel"))
    async def cmd_adminpanel_miniapp(message: types.Message):
        from config import ADMIN_IDS, WEB_APP_URL, WEBSERVER_HOST, WEBSERVER_PORT

        user_id = message.from_user.id
        if user_id not in ADMIN_IDS:
            await message.answer("⛔ ይህ ትእዛዝ ለአስተዳዳሪዎች ብቻ ነው።")
            return

        if WEB_APP_URL:
            admin_url = f"{WEB_APP_URL}/admin.html"
        else:
            admin_url = f"http://{WEBSERVER_HOST}:{WEBSERVER_PORT}/admin.html"

        try:
            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(
                types.InlineKeyboardButton(
                    text="🛡️ አስተዳዳሪ ፓነል ይክፈቱ",
                    web_app=types.WebAppInfo(url=admin_url)
                )
            )
            
            message_text = (
                f"👑 <b>አስተዳዳሪ ፓነል</b>\n\n"
                f"ፓነሉን በቴሌግራም ውስጥ ለመክፈት ከታች ያለውን ቁልፍ ይጫኑ።"
            )
            
            await message.answer(message_text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
            
        except Exception as e:
            logger.error(f"Error creating admin panel Mini App: {e}")
            
            try:
                keyboard = types.InlineKeyboardMarkup()
                keyboard.add(types.InlineKeyboardButton("🛡️ አስተዳዳሪ ፓነል ይክፈቱ", url=admin_url))
                
                await message.answer(
                    f"👑 አስተዳዳሪ ፓነል\n\n"
                    f"🌐 {admin_url}\n\n"
                    f"ፓነሉን ለመክፈት ከታች ያለውን ቁልፍ ይጫኑ።",
                    reply_markup=keyboard
                )
            except Exception as e2:
                logger.error(f"Fallback also failed: {e2}")
                await message.answer(f"👑 አስተዳዳሪ ፓነል\n\n🌐 {admin_url}")

    @dp.message_handler(Command("approvedeposit"))
    async def cmd_approvedeposit_enhanced(message: types.Message):
        from config import ADMIN_IDS
        
        user_id = message.from_user.id
        if user_id not in ADMIN_IDS:
            await message.answer("⛔ ይህ ትእዛዝ ለአስተዳዳሪዎች ብቻ ነው።")
            return
        
        args = message.text.split()
        if len(args) < 2:
            await message.answer("📋 አጠቃቀም: /approvedeposit <payment_id>\n\n📝 ምሳሌ: /approvedeposit 123")
            return
        
        try:
            payment_id = int(args[1])
            success = await approve_payment(payment_id, user_id)
            
            if success:
                await message.answer(f"✅ ፒሜንት {payment_id} ፈቅዷል!")
            else:
                await message.answer(f"❌ ፒሜንት {payment_id} ማጽደቅ አልተቻለም።")
            
        except ValueError:
            await message.answer("❌ እባክዎ ትክክለኛ የፒሜንት መታወቂያ ያስገቡ።")
        except Exception as e:
            await message.answer(f"❌ ስህተት: {str(e)[:100]}")

    @dp.message_handler(Command("approvewithdrawal"))
    async def cmd_approvewithdrawal_enhanced(message: types.Message):
        from config import ADMIN_IDS
        
        user_id = message.from_user.id
        if user_id not in ADMIN_IDS:
            await message.answer("⛔ ይህ ትእዛዝ ለአስተዳዳሪዎች ብቻ ነው።")
            return
        
        args = message.text.split()
        if len(args) < 2:
            await message.answer("📋 አጠቃቀም: /approvewithdrawal <withdrawal_id>\n\n📝 ምሳሌ: /approvewithdrawal 123")
            return
        
        try:
            withdrawal_id = int(args[1])
            success = await process_withdrawal_request(withdrawal_id, user_id, approve=True)
            
            if success:
                await message.answer(f"✅ የገንዘብ ማውጣት {withdrawal_id} ፈቅዷል!")
            else:
                await message.answer(f"❌ የገንዘብ ማውጣት {withdrawal_id} ማጽደቅ አልተቻለም።")
            
        except ValueError:
            await message.answer("❌ እባክዎ ትክክለኛ የማውጣት መታወቂያ ያስገቡ።")
        except Exception as e:
            await message.answer(f"❌ ስህተት: {str(e)[:100]}")
    
    # Initialize database
    try:
        logger.info("Initializing enhanced database...")
        from database.db import Database
        await Database.init_db()
        logger.info("[OK] Database tables initialized!")
        
        # Create admin_actions table if it doesn't exist
        with Database.get_cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS admin_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    admin_id INTEGER NOT NULL,
                    action_type TEXT NOT NULL,
                    details TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        logger.info("[OK] Admin actions table created/verified")
        
        await Database.migrate_db()
        logger.info("[OK] Database migrations completed!")
        
        cleaned = await Database.cleanup_orphaned_cards()
        if cleaned > 0:
            logger.info(f"[CLEANUP] Cleaned up {cleaned} orphaned cards")
            
    except Exception as e:
        logger.error(f"[ERROR] Database initialization failed: {e}")
        import traceback
        traceback.print_exc()
    
    # Initialize game manager
    try:
        logger.info("Initializing game manager...")
        from utils.game_manager import game_manager
        await game_manager.initialize()
        game_manager_obj = game_manager
        logger.info("[OK] Game manager initialized!")
    except Exception as e:
        logger.error(f"[ERROR] Game manager initialization failed: {e}")
        game_manager_obj = None
        
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
        from aiogram.types import BotCommand, BotCommandScopeChat
        
        user_commands = [
            BotCommand(command="start", description="Start bot and see menu"),
            BotCommand(command="play", description=f"Play bingo"),
            BotCommand(command="balance", description=f"Check your balance ({currency})"),
            BotCommand(command="deposit", description=f"Deposit money"),
            BotCommand(command="withdraw", description=f"Withdraw money"),
            BotCommand(command="history", description="View your game history"),
            BotCommand(command="instructions", description="Game rules and instructions"),
            BotCommand(command="support", description="Get support"),
        ]
        
        admin_commands = [
            BotCommand(command="admin", description="Admin panel"),
            BotCommand(command="adminpanel", description="Open admin web panel"),
            BotCommand(command="pendingdeposits", description="View pending deposits"),
            BotCommand(command="pendingwithdrawals", description="View pending withdrawal requests"),
            BotCommand(command="approvedeposit", description="Approve a deposit"),
            BotCommand(command="approvewithdrawal", description="Approve a withdrawal request"),
            BotCommand(command="startgame", description="Start new round game"),
            BotCommand(command="stopgame", description="Stop current round"),
            BotCommand(command="addbalance", description="Add balance to user"),
            BotCommand(command="stats", description="Game statistics"),
            BotCommand(command="callnumber", description="Manually call number"),
            BotCommand(command="fraudstats", description="Fraud detection statistics"),
            BotCommand(command="viewuserfraud", description="View user fraud history"),
            BotCommand(command="restrictuser", description="Restrict user from deposits"),
            BotCommand(command="getdb", description="Download database backup"),
            BotCommand(command="restoredb", description="SAFELY restore database from backup (auto-restart)"),
        ]
        
        await bot.set_my_commands(user_commands)
        
        for admin_id in ADMIN_IDS:
            try:
                await bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=admin_id))
                logger.info(f"[OK] Admin commands set for admin {admin_id}")
            except Exception as e:
                logger.warning(f"[WARNING] Could not set admin commands for {admin_id}: {e}")
        
        logger.info("[OK] Bot commands registered!")
    except Exception as e:
        logger.warning(f"[WARNING] Could not register commands: {e}")
    
    # Show startup info
    print("\n" + "="*60)
    print("🚀 ENHANCED BOT STARTUP COMPLETE")
    print("="*60)
    print(f"🤖 Bot: @habesh_bingo_bot")
    print(f"🎟️ Card Price: {card_price:.2f} {currency}")
    print(f"💸 Minimum Withdrawal: {MINIMUM_WITHDRAWAL_AMOUNT:.2f} {currency}")
    print(f"📱 Payment Phone: {PAYMENT_PHONE_NUMBER}")
    print(f"👤 Receiver Name: {PAYMENT_RECEIVER_NAME}")
    print(f"🆘 Support: {SUPPORT_TELEGRAM_USER}")
    print(f"🛡️ Fraud Prevention: ENABLED")
    print(f"🌐 Telebirr Primary API: {TELEBIRR_VERIFICATION_API_URL} (POST)")
    print(f"🌐 Telebirr Secondary API: {TELEBIRR_VERIFICATION_API_URL_2} (GET)")
    print(f"🌐 CBE Birr API: {CBE_BIRR_VERIFICATION_API_URL}")
    print(f"🔑 Telebirr API Key: {'Configured' if TELEBIRR_API_KEY else 'Not Configured'}")
    print(f"🔑 CBE Birr API Key: {'Configured' if CBE_BIRR_API_KEY else 'Not Configured'}")
    print(f"🎮 Game Mode: Round-Based Only")
    print(f"👑 Admins: {len(ADMIN_IDS)} configured")
    print(f"🌐 Web Interface: http://{WEBSERVER_HOST}:{WEBSERVER_PORT}/game.html")
    print(f"🛡️ Admin Panel: http://{WEBSERVER_HOST}:{WEBSERVER_PORT}/admin.html")
    if WEB_APP_URL:
        print(f"🌍 Public URL: {WEB_APP_URL}/game.html")
        print(f"🛡️ Admin URL: {WEB_APP_URL}/admin.html")
    print(f"✅ Status: Ready with enhanced features")
    print("="*60 + "\n")
    
    print("📋 ENHANCED COMMANDS:")
    print("  For All Users:")
    print(f"    /start        - Start bot and see menu")
    print(f"    /play         - Launch Round-Based Bingo")
    print(f"    /balance      - Check your balance (birr)")
    print(f"    /deposit      - Enhanced deposit with SMS verification")
    print(f"    /withdraw     - Withdraw money from your account")
    print(f"    /history      - View your game history")
    print(f"    /instructions - Game rules and instructions")
    print(f"    /support      - Get support")
    print("")
    print("  For Admins Only:")
    print(f"    /admin          - Admin panel")
    print(f"    /adminpanel     - Open admin web panel")
    print(f"    /pendingdeposits - View pending deposits")
    print(f"    /pendingwithdrawals - View pending withdrawals")
    print(f"    /approvedeposit  - Approve a deposit")
    print(f"    /approvewithdrawal - Approve a withdrawal")
    print(f"    /startgame       - Start new round game")
    print(f"    /stopgame        - Stop current round")
    print(f"    /addbalance      - Add balance to user")
    print(f"    /stats           - Game statistics")
    print(f"    /callnumber      - Manually call number")
    print(f"    /fraudstats      - Fraud detection statistics")
    print(f"    /viewuserfraud   - View user fraud history")
    print(f"    /restrictuser    - Restrict user from deposits")
    print(f"    /getdb           - Download database backup")
    print(f"    /restoredb       - **SAFE DATABASE RESTORE** - Upload .db file, auto-restart")
    print("="*60 + "\n")
    
    
    # ==================== REGISTER BOT WITH WEB_SERVER ====================
    try:
        from web_server import set_bot_instance
        set_bot_instance(bot)
        logger.info("✅ Registered bot instance with web_server for notifications")
        
        # Also store bot in a global variable that's easily accessible
        import sys
        sys.modules['bot'] = sys.modules[__name__]
        sys.modules['bot'].bot = bot
        logger.info("✅ Also registered bot in sys.modules")
    except Exception as e:
        logger.error(f"❌ Failed to register bot with web_server: {e}")

    # ==================== RUN ENHANCED BOT ====================
    try:
        logger.info("Starting enhanced bot polling...")
        main_task = asyncio.current_task()
        await dp.start_polling()
        
    except Exception as e:
        logger.error(f"Error starting enhanced bot: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        await enhanced_shutdown()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Enhanced bot stopped by user")
        print("\nEnhanced bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error in enhanced bot: {e}", exc_info=True)
        print(f"\nFatal error in enhanced bot: {e}")