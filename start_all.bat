@echo off
echo ========================================
echo 🎮 Habesha Bingo Bot - Complete Setup
echo ========================================
echo.

echo Step 1: Starting ngrok (for HTTPS)...
start cmd /k "cd /d C:\ngrok && ngrok http 8080"
timeout /t 5

echo Step 2: Starting Web Server...
start cmd /k "python web_server.py"

echo Step 3: Starting Bot...
timeout /t 3
python bot.py

pause