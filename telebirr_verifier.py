
#!/usr/bin/env python3
"""
Telebirr Transaction Verifier - SIMPLIFIED VERSION
For use in deposit flow without amount request
"""
import hashlib
import re
import unicodedata
from datetime import datetime
import logging
from typing import Dict, Optional
import asyncio

logger = logging.getLogger(__name__)

class TelebirrVerifier:
    """Simplified verifier for Telebirr transactions"""
    
    def __init__(self, admin_phone: str):
        self.admin_phone = admin_phone
        self.admin_phone_clean = re.sub(r'[^\d+]', '', admin_phone)
    
    def calculate_sms_hash(self, sms_text: str) -> str:
        """Create unique hash of SMS to prevent reuse"""
        normalized = unicodedata.normalize('NFKC', sms_text.strip())
        normalized = re.sub(r'\s+', ' ', normalized)
        normalized = normalized.lower().strip()
        return hashlib.sha256(normalized.encode('utf-8')).hexdigest()[:32]
    
    def extract_transaction_info(self, sms_text: str) -> Dict:
        """Extract all transaction info from SMS"""
        result = {
            'valid': False,
            'transaction_id': None,
            'amount': None,
            'receiver_name': None,
            'receiver_phone': None,
            'timestamp': None,
            'sender_name': None,
            'errors': [],
            'warnings': []
        }
        
        # Extract transaction ID
        tx_patterns = [
            r'transactioninfo\.ethiotelecom\.et/receipt/([A-Z0-9]+)',
            r'transaction number is ([A-Z0-9]{8,12})',
            r'(DAT[A-Z0-9]{6})',
            r'\b([A-Z0-9]{8,12})\b'
        ]
        
        for pattern in tx_patterns:
            match = re.search(pattern, sms_text, re.IGNORECASE)
            if match:
                tx_id = match.group(1).strip().upper()
                if self.validate_transaction_id(tx_id):
                    result['transaction_id'] = tx_id
                    break
        
        if not result['transaction_id']:
            result['errors'].append("No valid transaction ID found")
        
        # Extract amount
        amount_pattern = r'ETB\s*([\d,]+\.?\d*)'
        amount_match = re.search(amount_pattern, sms_text, re.IGNORECASE)
        if amount_match:
            try:
                amount_str = amount_match.group(1).replace(',', '')
                result['amount'] = float(amount_str)
            except:
                result['errors'].append("Invalid amount format")
        else:
            result['errors'].append("No amount found")
        
        # Extract receiver info
        receiver_pattern = r'to\s+([^\(]+)\s*\((\d{10})\)'
        receiver_match = re.search(receiver_pattern, sms_text, re.IGNORECASE)
        if receiver_match:
            result['receiver_name'] = receiver_match.group(1).strip()
            result['receiver_phone'] = receiver_match.group(2).strip()
        else:
            result['errors'].append("No receiver info found")
        
        # Extract timestamp
        timestamp_pattern = r'on\s*(\d{2}/\d{2}/\d{4}\s*\d{2}:\d{2}:\d{2})'
        timestamp_match = re.search(timestamp_pattern, sms_text, re.IGNORECASE)
        if timestamp_match:
            result['timestamp'] = timestamp_match.group(1).strip()
        
        # Extract sender name
        sender_pattern = r'Dear\s+([^\n]+)'
        sender_match = re.search(sender_pattern, sms_text)
        if sender_match:
            result['sender_name'] = sender_match.group(1).strip()
        
        # Validate receiver phone matches admin phone
        if result['receiver_phone']:
            if self.admin_phone_clean and self.admin_phone_clean not in result['receiver_phone']:
                # Try without country code
                admin_last_ten = self.admin_phone_clean[-10:] if len(self.admin_phone_clean) >= 10 else self.admin_phone_clean
                if admin_last_ten not in result['receiver_phone']:
                    result['errors'].append(
                        f"Receiver phone mismatch: {result['receiver_phone']} vs admin {admin_last_ten}"
                    )
        
        # Check SMS is valid
        result['valid'] = (
            result['transaction_id'] is not None and
            result['amount'] is not None and
            result['receiver_phone'] is not None and
            len(result['errors']) == 0
        )
        
        return result
    
    def validate_transaction_id(self, tx_id: str) -> bool:
        """Validate transaction ID format"""
        if not tx_id:
            return False
        
        if len(tx_id) < 8 or len(tx_id) > 12:
            return False
        
        if not re.match(r'^[A-Z0-9]+$', tx_id):
            return False
        
        if tx_id.isdigit():
            return False
        
        return True
    
    async def verify_with_scraping(self, sms_text: str) -> Dict:
        """Complete verification with web scraping"""
        result = {
            'verified': False,
            'sms_info': {},
            'scraped_info': {},
            'matches': {},
            'errors': [],
            'warnings': [],
            'final_amount': None,
            'final_decision': 'REJECT'
        }
        
        try:
            # Step 1: Extract info from SMS
            sms_info = self.extract_transaction_info(sms_text)
            result['sms_info'] = sms_info
            
            if not sms_info['valid']:
                result['errors'].extend(sms_info['errors'])
                return result
            
            # Step 2: Scrape receipt
            try:
                from telebirr_scraper import TelebirrScraper
                scraper = TelebirrScraper()
                
                async with scraper:
                    scraped_result = await scraper.verify_transaction(
                        sms_text=sms_text,
                        admin_phone=self.admin_phone
                    )
                
                result['scraped_info'] = scraped_result
                
                # Step 3: Check verification result
                if scraped_result.get('verified', False):
                    result['verified'] = True
                    result['final_decision'] = 'APPROVE'
                    result['final_amount'] = scraped_result.get('scraped_info', {}).get('amount')
                    result['matches'] = scraped_result.get('matches', {})
                else:
                    result['errors'].extend(scraped_result.get('errors', []))
                    result['warnings'].extend(scraped_result.get('warnings', []))
                    
            except ImportError:
                result['errors'].append("Web scraper not available")
            except Exception as e:
                result['errors'].append(f"Web scraping failed: {str(e)}")
        
        except Exception as e:
            logger.error(f"Verification error: {e}", exc_info=True)
            result['errors'].append(f"Verification error: {str(e)}")
        
        return result
    
    def get_transaction_id(self, sms_text: str) -> Optional[str]:
        """Quickly extract transaction ID from SMS"""
        patterns = [
            r'transactioninfo\.ethiotelecom\.et/receipt/([A-Z0-9]+)',
            r'transaction number is ([A-Z0-9]{8,12})',
            r'(DAT[A-Z0-9]{6})'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, sms_text, re.IGNORECASE)
            if match:
                tx_id = match.group(1).strip().upper()
                if self.validate_transaction_id(tx_id):
                    return tx_id
        
        return None
    
    def get_amount_from_sms(self, sms_text: str) -> Optional[float]:
        """Extract amount from SMS"""
        amount_pattern = r'ETB\s*([\d,]+\.?\d*)'
        amount_match = re.search(amount_pattern, sms_text, re.IGNORECASE)
        if amount_match:
            try:
                amount_str = amount_match.group(1).replace(',', '')
                return float(amount_str)
            except:
                pass
        return None

async def verify_deposit(sms_text: str, admin_phone: str) -> Dict:
    """
    Main function for deposit verification
    
    Returns:
        {
            'verified': bool,
            'amount': float,  # Amount from receipt
            'transaction_id': str,
            'errors': list,
            'warnings': list
        }
    """
    verifier = TelebirrVerifier(admin_phone)
    result = await verifier.verify_with_scraping(sms_text)
    
    return {
        'verified': result['verified'],
        'amount': result.get('final_amount'),
        'transaction_id': result.get('sms_info', {}).get('transaction_id'),
        'errors': result['errors'],
        'warnings': result['warnings'],
        'decision': result.get('final_decision', 'REJECT')
    }

# Export for use in bot.py
__all__ = ['TelebirrVerifier', 'verify_deposit']
