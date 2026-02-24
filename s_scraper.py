#!/usr/bin/env python3
"""
JavaScript Scraper Wrapper for Python
"""

import asyncio
import json
import subprocess
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

class JSTelebirrScraper:
    """Wrapper for JavaScript Puppeteer scraper"""
    
    def __init__(self, scraper_js_path: str = "scraper.js"):
        self.scraper_js_path = Path(scraper_js_path)
        if not self.scraper_js_path.exists():
            raise FileNotFoundError(f"Scraper JS file not found: {scraper_js_path}")
        
        # Ensure Node.js is available
        self.check_node_js()
    
    def check_node_js(self):
        """Check if Node.js is installed and accessible"""
        try:
            result = subprocess.run(
                ["node", "--version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                logger.info(f"✅ Node.js version: {result.stdout.strip()}")
                return True
            else:
                logger.error(f"Node.js check failed: {result.stderr}")
                return False
        except Exception as e:
            logger.error(f"Node.js not found: {e}")
            return False
    
    async def scrape_receipt(self, transaction_id: str, timeout: int = 30):
        """
        Scrape receipt using JavaScript scraper
        Returns: dict with scraped data or None if failed
        """
        try:
            # Create temp output file
            import tempfile
            import uuid
            import shutil
            
            temp_dir = tempfile.mkdtemp(prefix="telebirr_scrape_")
            output_file = Path(temp_dir) / f"result_{uuid.uuid4().hex[:8]}.json"
            
            logger.info(f"🚀 Running JS scraper for transaction: {transaction_id}")
            
            # Run the JS scraper
            cmd = [
                "node",
                str(self.scraper_js_path),
                transaction_id,
                str(output_file)
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.scraper_js_path.parent
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout
                )
                
                stdout_text = stdout.decode('utf-8', errors='ignore') if stdout else ""
                stderr_text = stderr.decode('utf-8', errors='ignore') if stderr else ""
                
                logger.debug(f"JS scraper stdout:\n{stdout_text}")
                if stderr_text:
                    logger.debug(f"JS scraper stderr:\n{stderr_text}")
                
                if process.returncode != 0:
                    logger.error(f"JS scraper failed with code {process.returncode}")
                    # Try to read error output
                    return None
                
                # Read the result file
                if output_file.exists():
                    with open(output_file, 'r', encoding='utf-8') as f:
                        result = json.load(f)
                    
                    logger.info(f"✅ JS scraper completed: {result.get('status', 'UNKNOWN')}")
                    
                    # Clean up temp directory
                    try:
                        shutil.rmtree(temp_dir)
                    except:
                        pass
                    
                    return result
                else:
                    logger.error(f"Output file not created: {output_file}")
                    return None
                    
            except asyncio.TimeoutError:
                logger.error(f"JS scraper timeout after {timeout} seconds")
                try:
                    process.kill()
                except:
                    pass
                return None
                
        except Exception as e:
            logger.error(f"Error running JS scraper: {e}")
            return None
    
    async def scrape_receipt_batch(self, transaction_ids: list, max_concurrent: int = 3):
        """Scrape multiple receipts with concurrency limit"""
        import asyncio
        
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def scrape_with_semaphore(tx_id):
            async with semaphore:
                return await self.scrape_receipt(tx_id)
        
        tasks = [scrape_with_semaphore(tx_id) for tx_id in transaction_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results
        valid_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Error scraping {transaction_ids[i]}: {result}")
            elif result:
                valid_results.append(result)
        
        return valid_results

# Fast testing function
async def test_scraper():
    """Test the JS scraper quickly"""
    import time
    
    scraper = JSTelebirrScraper("scraper.js")
    
    # Test with a known transaction ID
    test_tx_id = "DB39FLHXI5"
    
    print(f"🧪 Testing JS scraper with transaction: {test_tx_id}")
    start_time = time.time()
    
    result = await scraper.scrape_receipt(test_tx_id, timeout=20)
    
    elapsed = time.time() - start_time
    print(f"⏱️  Scraping took {elapsed:.2f} seconds")
    
    if result:
        print(f"✅ Success: {result.get('scraped_successfully', False)}")
        print(f"📊 Status: {result.get('status', 'UNKNOWN')}")
        print(f"💰 Amount: {result.get('amount', 'N/A')}")
        print(f"📱 Receiver: {result.get('receiver', 'N/A')}")
        return result
    else:
        print("❌ Scraping failed")
        return None

if __name__ == "__main__":
    # Quick test
    import asyncio
    asyncio.run(test_scraper())