#!/bin/bash

echo "🚀 Setting up JavaScript Telebirr Scraper..."

# Create directory for scraper
mkdir -p scraper
cd scraper

echo "📄 Creating package.json..."
cat > package.json << 'EOF'
{
  "name": "telebirr-scraper",
  "version": "1.0.0",
  "description": "Ethio telecom Telebirr receipt scraper",
  "main": "scraper.js",
  "scripts": {
    "scrape": "node scraper.js",
    "test": "node scraper.js DB39FLHXI5 test_result.json"
  },
  "dependencies": {
    "puppeteer": "^21.0.0"
  },
  "engines": {
    "node": ">=16.0.0"
  },
  "author": "Habesha Bingo",
  "license": "MIT"
}
EOF

echo "📄 Creating scraper.js..."
cat > scraper.js << 'EOF'
#!/usr/bin/env node

const puppeteer = require('puppeteer');
const fs = require('fs');
const path = require('path');

class TelebirrScraper {
    constructor() {
        this.results = [];
        this.timeout = 30000; // 30 seconds max
    }

    async scrapeReceipt(transactionId) {
        const url = `https://transactioninfo.ethiotelecom.et/receipt/${transactionId}`;
        
        console.log(`🔍 Scraping: ${url}`);
        
        let browser;
        try {
            // Launch browser with optimized settings
            browser = await puppeteer.launch({
                headless: 'new',
                args: [
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-accelerated-2d-canvas',
                    '--disable-gpu',
                    '--window-size=1920,1080'
                ],
                timeout: this.timeout
            });

            const page = await browser.newPage();
            
            // Set realistic headers
            await page.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36');
            await page.setExtraHTTPHeaders({
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-User': '?1',
                'Cache-Control': 'max-age=0',
                'DNT': '1',
                'Referer': 'https://telebirr.et/'
            });

            // Set cookies
            await page.setCookie({
                name: '_ga',
                value: 'GA1.2.1234567890.1234567890',
                domain: 'transactioninfo.ethiotelecom.et'
            }, {
                name: '_gid',
                value: 'GA1.2.9876543210.9876543210',
                domain: 'transactioninfo.ethiotelecom.et'
            });

            // Navigate with timeout
            console.log('🌐 Navigating to page...');
            await page.goto(url, {
                waitUntil: 'domcontentloaded',
                timeout: this.timeout
            });

            // Wait for content to load
            await page.waitForTimeout(2000);

            // Get page content
            const content = await page.content();
            const text = await page.evaluate(() => document.body.innerText);
            const html = await page.evaluate(() => document.body.innerHTML);

            // Extract information using regex patterns
            const result = {
                transaction_id: transactionId,
                url: url,
                scraped_at: new Date().toISOString(),
                amount: null,
                sender: null,
                receiver: null,
                receiver_name: null,
                status: null,
                timestamp: null,
                currency: 'ETB',
                scraped_successfully: false,
                raw_text: text.substring(0, 1000) // First 1000 chars
            };

            // 1. Extract Status
            const statusPatterns = [
                /success/i, /completed/i, /approved/i, /processed/i, /የተሳካ/i, /ተሳክቷል/i,
                /failed/i, /rejected/i, /declined/i, /canceled/i, /unsuccessful/i,
                /pending/i, /processing/i, /in progress/i, /ጊዜ የሚፈልግ/i
            ];

            for (const pattern of statusPatterns) {
                if (pattern.test(text)) {
                    if (pattern.source.includes('success') || pattern.source.includes('completed') || pattern.source.includes('የተሳካ')) {
                        result.status = 'SUCCESS';
                    } else if (pattern.source.includes('failed') || pattern.source.includes('rejected')) {
                        result.status = 'FAILED';
                    } else if (pattern.source.includes('pending') || pattern.source.includes('processing')) {
                        result.status = 'PENDING';
                    }
                    break;
                }
            }

            if (!result.status) {
                result.status = 'UNKNOWN';
            }

            // 2. Extract Amount
            const amountPatterns = [
                /ETB\s*([\d,]+\.?\d*)/i,
                /ብር\s*([\d,]+\.?\d*)/i,
                /BIRR\s*([\d,]+\.?\d*)/i,
                /([\d,]+\.?\d{2})\s*(?:ETB|ብር|BIRR)/i,
                /amount\s*[:\s]+([\d,]+\.?\d*)/i,
                /total\s*[:\s]+([\d,]+\.?\d*)/i
            ];

            for (const pattern of amountPatterns) {
                const match = text.match(pattern);
                if (match && match[1]) {
                    try {
                        const amountStr = match[1].replace(/,/g, '');
                        const amountFloat = parseFloat(amountStr);
                        if (amountFloat > 0.1 && amountFloat < 100000) {
                            result.amount = amountFloat;
                            console.log(`💰 Amount found: ${result.amount}`);
                            break;
                        }
                    } catch (e) {
                        continue;
                    }
                }
            }

            // 3. Extract Phone Numbers
            const phonePatterns = [
                /\+2519\d{8}/g,
                /2519\d{8}/g,
                /09\d{8}/g,
                /9\d{8}/g
            ];

            const phones = [];
            for (const pattern of phonePatterns) {
                const matches = text.match(pattern);
                if (matches) {
                    phones.push(...matches);
                }
            }

            // Clean and format phone numbers
            const uniquePhones = [...new Set(phones)];
            const formattedPhones = uniquePhones.map(phone => {
                let clean = phone.replace(/\D/g, '');
                if (clean.startsWith('9') && clean.length === 9) {
                    clean = '251' + clean;
                } else if (clean.startsWith('09')) {
                    clean = '251' + clean.substring(1);
                }
                if (clean.startsWith('2519') && clean.length === 12) {
                    return `+${clean}`;
                }
                return null;
            }).filter(phone => phone !== null);

            if (formattedPhones.length > 0) {
                result.receiver = formattedPhones[0];
                if (formattedPhones.length > 1) {
                    result.sender = formattedPhones[1];
                }
                console.log(`📱 Phones found: ${formattedPhones.join(', ')}`);
            }

            // 4. Extract Timestamp
            const datePatterns = [
                /\d{2}\/\d{2}\/\d{4}\s+\d{2}:\d{2}:\d{2}/,
                /\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}/,
                /\d{2}-\d{2}-\d{4}\s+\d{2}:\d{2}:\d{2}/,
                /on\s+(\d{2}\/\d{2}\/\d{4})/i,
                /at\s+(\d{2}:\d{2}:\d{2})/i
            ];

            for (const pattern of datePatterns) {
                const match = text.match(pattern);
                if (match) {
                    result.timestamp = match[0];
                    console.log(`⏰ Timestamp found: ${result.timestamp}`);
                    break;
                }
            }

            // 5. Extract Receiver Name
            const namePatterns = [
                /to\s+([^(\n]+?)\s*(?:\+|\(|251|09|ETB|ብር|BIRR)/i,
                /receiver\s*[:\s]+([^\n]+)/i,
                /sent to\s+([^\n]+)/i
            ];

            for (const pattern of namePatterns) {
                const match = text.match(pattern);
                if (match && match[1]) {
                    result.receiver_name = match[1].trim();
                    console.log(`👤 Receiver name found: ${result.receiver_name}`);
                    break;
                }
            }

            // 6. Determine if successful
            result.scraped_successfully = (
                result.status === 'SUCCESS' &&
                result.amount !== null &&
                result.receiver !== null
            );

            console.log(`✅ Scraping ${result.scraped_successfully ? 'SUCCESSFUL' : 'PARTIAL'}`);
            console.log(`   • Status: ${result.status}`);
            console.log(`   • Amount: ${result.amount}`);
            console.log(`   • Receiver: ${result.receiver}`);

            return result;

        } catch (error) {
            console.error(`❌ Scraping error: ${error.message}`);
            return {
                transaction_id: transactionId,
                url: url,
                scraped_at: new Date().toISOString(),
                error: error.message,
                scraped_successfully: false
            };
        } finally {
            if (browser) {
                await browser.close();
            }
        }
    }
}

// Command line interface
async function main() {
    const args = process.argv.slice(2);
    
    if (args.length === 0) {
        console.log('Usage: node scraper.js <transaction_id> [output_file]');
        console.log('Example: node scraper.js DB39FLHXI5');
        process.exit(1);
    }

    const transactionId = args[0];
    const outputFile = args[1] || 'scraped_result.json';
    
    console.log(`🚀 Starting Telebirr Receipt Scraper`);
    console.log(`📝 Transaction ID: ${transactionId}`);
    
    const scraper = new TelebirrScraper();
    const result = await scraper.scrapeReceipt(transactionId);
    
    // Save single result
    fs.writeFileSync(outputFile, JSON.stringify(result, null, 2));
    console.log(`💾 Result saved to ${outputFile}`);
    
    // Print summary
    console.log('\n📊 SCRAPING SUMMARY:');
    console.log(`   • Transaction ID: ${result.transaction_id}`);
    console.log(`   • Status: ${result.status}`);
    console.log(`   • Amount: ${result.amount || 'Not found'}`);
    console.log(`   • Receiver: ${result.receiver || 'Not found'}`);
    console.log(`   • Success: ${result.scraped_successfully ? '✅ Yes' : '❌ No'}`);
    
    if (result.error) {
        console.log(`   • Error: ${result.error}`);
    }
    
    process.exit(result.scraped_successfully ? 0 : 1);
}

// Run if called directly
if (require.main === module) {
    main().catch(error => {
        console.error('Fatal error:', error);
        process.exit(1);
    });
}

// Export for use as module
module.exports = { TelebirrScraper };
EOF

echo "📦 Installing dependencies..."
npm install

echo "🔧 Checking Node.js..."
node --version

if [ $? -eq 0 ]; then
    echo "✅ Node.js is ready"
else
    echo "❌ Node.js is not installed or not in PATH"
    echo "Please install Node.js from: https://nodejs.org/"
    exit 1
fi

# Test the scraper
echo "🧪 Testing scraper..."
echo "node scraper.js DB39FLHXI5 test.json"

cd ..

echo "🎉 Setup complete!"
echo "📁 Scraper directory: ./scraper/"
echo "📄 Main file: ./scraper/scraper.js"
echo "📄 Python wrapper: Integrated in bot.py"
echo ""
echo "To test: cd scraper && node scraper.js DB39FLHXI5"