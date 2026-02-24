
#!/usr/bin/env python3
"""
Telebirr Web Scraper for Transaction Verification - SIMPLIFIED VERSION
Uses hardcoded URL template: https://transactioninfo.ethiotelecom.et/receipt/{transaction_id}
"""
import aiohttp
import re
import json
from datetime import datetime
from bs4 import BeautifulSoup
import logging
import random
from typing import Dict, Optional
import asyncio

logger = logging.getLogger(__name__)

class TelebirrScraper:
    """Scrape and verify Telebirr transactions from Ethio telecom receipt page"""
    
    # Hardcoded receipt URL template
    RECEIPT_URL_TEMPLATE = "https://transactioninfo.ethiotelecom.et/receipt/{transaction_id}"
    
    def __init__(self):
        self.session = None
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15',
            'Mozilla/5.0 (Linux; Android 10; SM-G973F) AppleWebKit/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        ]
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            headers={'User-Agent': random.choice(self.user_agents)}
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    def extract_transaction_id(self, sms_text: str) -> Optional[str]:
        """Extract transaction ID from SMS text"""
        # Look for transaction ID in various patterns
        patterns = [
            # From receipt link
            r'transactioninfo\.ethiotelecom\.et/receipt/([A-Z0-9]+)',
            # From "transaction number is" pattern
            r'transaction number is ([A-Z0-9]{8,12})',
            # Common patterns
            r'number is ([A-Z0-9]{8,12})',
            r'TXN[:\s]*([A-Z0-9]{8,12})',
            r'Transaction[:\s]*([A-Z0-9]{8,12})',
            # Specific DAT format
            r'(DAT[A-Z0-9]{6})',
            r'TXN[:\s]*(DAT[A-Z0-9]{6})',
            # General 8-12 char alphanumeric
            r'\b([A-Z0-9]{8,12})\b'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, sms_text, re.IGNORECASE)
            if match:
                tx_id = match.group(1).strip().upper()
                # Validate it looks like a transaction ID
                if self.validate_transaction_id(tx_id):
                    return tx_id
        
        return None
    
    def validate_transaction_id(self, tx_id: str) -> bool:
        """Validate if a string looks like a valid Telebirr transaction ID"""
        if not tx_id:
            return False
        
        # Length check
        if len(tx_id) < 8 or len(tx_id) > 12:
            return False
        
        # Must be alphanumeric
        if not re.match(r'^[A-Z0-9]+$', tx_id):
            return False
        
        # Not just numbers
        if tx_id.isdigit():
            return False
        
        return True
    
    def extract_info_from_sms(self, sms_text: str) -> Dict:
        """Extract transaction info from SMS text"""
        result = {
            'transaction_id': None,
            'amount': None,
            'receiver_name': None,
            'receiver_phone': None,
            'timestamp': None,
            'sender_name': None,
            'extracted': False
        }
        
        # Extract transaction ID
        result['transaction_id'] = self.extract_transaction_id(sms_text)
        
        # Extract amount (ETB 400.00)
        amount_pattern = r'ETB\s*([\d,]+\.?\d*)'
        amount_match = re.search(amount_pattern, sms_text, re.IGNORECASE)
        if amount_match:
            try:
                amount_str = amount_match.group(1).replace(',', '')
                result['amount'] = float(amount_str)
            except:
                pass
        
        # Extract receiver info: "to SHEMSE SEBRE (0999836926)"
        receiver_pattern = r'to\s+([^\(]+)\s*\((\d{10})\)'
        receiver_match = re.search(receiver_pattern, sms_text, re.IGNORECASE)
        if receiver_match:
            result['receiver_name'] = receiver_match.group(1).strip()
            result['receiver_phone'] = receiver_match.group(2).strip()
        
        # Extract timestamp: "on 29/01/2026 17:04:55"
        timestamp_pattern = r'on\s*(\d{2}/\d{2}/\d{4}\s*\d{2}:\d{2}:\d{2})'
        timestamp_match = re.search(timestamp_pattern, sms_text, re.IGNORECASE)
        if timestamp_match:
            result['timestamp'] = timestamp_match.group(1).strip()
        
        # Extract sender name: "Dear Senait"
        sender_pattern = r'Dear\s+([^\n]+)'
        sender_match = re.search(sender_pattern, sms_text, re.IGNORECASE)
        if sender_match:
            result['sender_name'] = sender_match.group(1).strip()
        
        result['extracted'] = all([
            result['transaction_id'],
            result['amount'],
            result['receiver_phone']
        ])
        
        return result
    
    async def scrape_receipt(self, transaction_id: str) -> Dict:
        """Scrape transaction details from Ethio telecom receipt page"""
        url = self.RECEIPT_URL_TEMPLATE.format(transaction_id=transaction_id)
        
        try:
            headers = {
                'User-Agent': random.choice(self.user_agents),
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Cache-Control': 'max-age=0',
                'Referer': 'https://telebirr.et/'
            }
            
            logger.info(f"Scraping receipt: {url}")
            
            async with self.session.get(url, headers=headers, ssl=False, allow_redirects=True) as response:
                if response.status != 200:
                    logger.error(f"Failed to fetch receipt: {response.status}")
                    return None
                
                html = await response.text()
                
                # Initialize result
                result = {
                    'url': url,
                    'scraped_at': datetime.now().isoformat(),
                    'transaction_id': transaction_id,
                    'amount': None,
                    'sender': None,
                    'receiver': None,
                    'receiver_name': None,
                    'status': None,
                    'timestamp': None,
                    'currency': 'ETB',
                    'scraped_successfully': False
                }
                
                soup = BeautifulSoup(html, 'html.parser')
                text_content = soup.get_text().upper()
                
                # DEBUG: Log the receipt content structure
                logger.debug(f"Receipt content (first 500 chars): {text_content[:500]}")
                
                # Look for transaction status
                if 'SUCCESS' in text_content or 'COMPLETED' in text_content or 'APPROVED' in text_content:
                    result['status'] = 'SUCCESS'
                elif 'FAILED' in text_content or 'REJECTED' in text_content or 'DECLINED' in text_content:
                    result['status'] = 'FAILED'
                elif 'PENDING' in text_content or 'PROCESSING' in text_content:
                    result['status'] = 'PENDING'
                else:
                    result['status'] = 'UNKNOWN'
                
                # Look for amount
                amount_patterns = [
                    r'AMOUNT[:\s]*([\d,]+\.?\d*)\s*(?:ETB|ብር|BIRR)',
                    r'TOTAL[:\s]*([\d,]+\.?\d*)\s*(?:ETB|ብር|BIRR)',
                    r'ETB[:\s]*([\d,]+\.?\d*)',
                    r'([\d,]+\.?\d*)\s*(?:ETB|ብር|BIRR)',
                    r'ብር[:\s]*([\d,]+\.?\d*)',
                    r'BIRR[:\s]*([\d,]+\.?\d*)'
                ]
                
                for pattern in amount_patterns:
                    matches = re.findall(pattern, text_content, re.IGNORECASE)
                    for match in matches:
                        if isinstance(match, tuple):
                            match = match[0]
                        try:
                            amount_str = str(match).replace(',', '')
                            amount_float = float(amount_str)
                            # Heuristic: Typically amounts are > 1 and reasonable
                            if amount_float > 1 and amount_float < 100000:
                                result['amount'] = amount_float
                                break
                        except:
                            continue
                    if result['amount']:
                        break
                
                # Look for timestamp
                time_patterns = [
                    r'DATE[:\s]*([\d/]{10}\s+[\d:]{8})',
                    r'TIME[:\s]*([\d/]{10}\s+[\d:]{8})',
                    r'(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2})',
                    r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})'
                ]
                
                for pattern in time_patterns:
                    match = re.search(pattern, text_content)
                    if match:
                        result['timestamp'] = match.group(1).strip()
                        break
                
                # Look for phone numbers and names
                all_text = soup.get_text()
                
                # Phone patterns
                phone_patterns = [
                    r'(\+2519\d{8})',
                    r'(09\d{8})',
                    r'(2519\d{8})',
                    r'To[:\s]*([\+\d\s]+)',
                    r'Receiver[:\s]*([\+\d\s]+)',
                    r'Beneficiary[:\s]*([\+\d\s]+)',
                    r'በ[:\s]*([\+\d\s]+)',
                    r'ለ[:\s]*([\+\d\s]+)'
                ]
                
                found_phones = []
                for pattern in phone_patterns:
                    matches = re.findall(pattern, all_text)
                    for match in matches:
                        if isinstance(match, tuple):
                            match = match[0]
                        phone = str(match).strip()
                        if phone and phone not in found_phones:
                            found_phones.append(phone)
                
                if found_phones:
                    if len(found_phones) >= 2:
                        result['sender'] = found_phones[0]
                        result['receiver'] = found_phones[-1]
                    else:
                        result['receiver'] = found_phones[0]
                
                # Look for names near phone numbers
                for element in soup.find_all(['div', 'p', 'span', 'td']):
                    text = element.get_text().strip()
                    if any(keyword in text for keyword in ['To:', 'Receiver:', 'Beneficiary:']):
                        # Try to extract name and phone
                        name_match = re.search(r'[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+', text)
                        phone_match = re.search(r'[\d\*\+]+', text)
                        
                        if name_match and phone_match:
                            result['receiver_name'] = name_match.group()
                            if not result['receiver']:
                                result['receiver'] = phone_match.group()
                
                result['scraped_successfully'] = all([
                    result['status'] == 'SUCCESS',
                    result['amount'] is not None,
                    result['receiver'] is not None
                ])
                
                logger.info(f"Scraped receipt: TX={result['transaction_id']}, "
                          f"Amount={result['amount']}, Status={result['status']}, "
                          f"Receiver={result.get('receiver')}")
                
                return result
                
        except Exception as e:
            logger.error(f"Error scraping receipt: {e}", exc_info=True)
            return None
    
    async def verify_transaction(self, sms_text: str, admin_phone: str) -> Dict:
        """
        Verify transaction by comparing SMS data with scraped receipt data
        
        Steps:
        1. Extract info from SMS
        2. Scrape receipt using transaction ID
        3. Compare and validate
        """
        verification_result = {
            'verified': False,
            'sms_info': {},
            'scraped_info': {},
            'matches': {},
            'errors': [],
            'warnings': []
        }
        
        try:
            # Step 1: Extract info from SMS
            sms_info = self.extract_info_from_sms(sms_text)
            verification_result['sms_info'] = sms_info
            
            if not sms_info['extracted']:
                verification_result['errors'].append("Failed to extract required info from SMS")
                return verification_result
            
            logger.info(f"Extracted from SMS - TX: {sms_info['transaction_id']}, "
                       f"Amount: {sms_info['amount']}, Receiver: {sms_info['receiver_phone']}")
            
            # Step 2: Scrape receipt
            async with self:
                scraped_info = await self.scrape_receipt(sms_info['transaction_id'])
            
            if not scraped_info:
                verification_result['errors'].append("Failed to scrape receipt")
                return verification_result
            
            verification_result['scraped_info'] = scraped_info
            
            if not scraped_info['scraped_successfully']:
                verification_result['errors'].append("Receipt scraping incomplete")
                return verification_result
            
            logger.info(f"Scraped from receipt - TX: {scraped_info['transaction_id']}, "
                       f"Amount: {scraped_info['amount']}, Status: {scraped_info['status']}")
            
            # Step 3: Compare and validate
            
            # 3.1 Check transaction status
            if scraped_info['status'] != 'SUCCESS':
                verification_result['errors'].append(f"Transaction not successful: {scraped_info['status']}")
            
            # 3.2 Check amount match
            if sms_info['amount'] and scraped_info['amount']:
                amount_match = abs(sms_info['amount'] - scraped_info['amount']) <= 0.01
                verification_result['matches']['amount'] = amount_match
                if not amount_match:
                    verification_result['errors'].append(
                        f"Amount mismatch: SMS={sms_info['amount']}, Receipt={scraped_info['amount']}"
                    )
            
            # 3.3 Check receiver phone match
            if sms_info['receiver_phone'] and scraped_info['receiver']:
                # Clean phone numbers for comparison
                sms_phone_clean = re.sub(r'[^\d]', '', sms_info['receiver_phone'])
                scraped_phone_clean = re.sub(r'[^\d]', '', scraped_info['receiver'])
                
                # Check if SMS phone is in scraped phone
                phone_match = sms_phone_clean in scraped_phone_clean
                verification_result['matches']['receiver_phone'] = phone_match
                
                if not phone_match:
                    verification_result['errors'].append(
                        f"Phone mismatch: SMS={sms_info['receiver_phone']}, Receipt={scraped_info['receiver']}"
                    )
            
            # 3.4 Check timestamp (if available in both)
            if sms_info['timestamp'] and scraped_info['timestamp']:
                # Simple string comparison for now
                timestamp_match = sms_info['timestamp'] in scraped_info['timestamp']
                verification_result['matches']['timestamp'] = timestamp_match
            
            # 3.5 Check if receiver matches admin phone
            if scraped_info['receiver']:
                admin_phone_clean = re.sub(r'[^\d]', '', admin_phone)
                scraped_phone_clean = re.sub(r'[^\d]', '', scraped_info['receiver'])
                
                if admin_phone_clean and scraped_phone_clean:
                    admin_in_scraped = admin_phone_clean in scraped_phone_clean
                    verification_result['matches']['admin_phone'] = admin_in_scraped
                    
                    if not admin_in_scraped:
                        verification_result['errors'].append(
                            f"Admin phone not found in receipt: Admin={admin_phone_clean}, Receipt={scraped_info['receiver']}"
                        )
            
            # 3.6 Check transaction ID match
            if sms_info['transaction_id'] and scraped_info['transaction_id']:
                tx_match = sms_info['transaction_id'].upper() == scraped_info['transaction_id'].upper()
                verification_result['matches']['transaction_id'] = tx_match
                
                if not tx_match:
                    verification_result['errors'].append("Transaction ID mismatch")
            
            # Step 4: Final verification
            if not verification_result['errors']:
                verification_result['verified'] = True
                
                # Calculate match score
                match_count = sum(verification_result['matches'].values())
                total_checks = len(verification_result['matches'])
                match_score = (match_count / total_checks * 100) if total_checks > 0 else 0
                
                verification_result['match_score'] = match_score
                logger.info(f"Transaction VERIFIED! Match score: {match_score:.1f}%")
            else:
                logger.error(f"Transaction verification FAILED: {verification_result['errors']}")
            
            return verification_result
            
        except Exception as e:
            logger.error(f"Verification error: {e}", exc_info=True)
            verification_result['errors'].append(f"Verification error: {str(e)}")
            return verification_result

# Global instance
telebirr_scraper = TelebirrScraper()
