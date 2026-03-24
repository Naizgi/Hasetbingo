fall_back_html = """

<!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>Habesha Bingo - Game</title>
                <style>
                    * {
                        margin: 0;
                        padding: 0;
                        box-sizing: border-box;
                    }
                    
                    body {
                        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                        min-height: 100vh;
                        color: #333;
                    }
                    
                    .container {
                        max-width: 1200px;
                        margin: 0 auto;
                        padding: 20px;
                    }
                    
                    header {
                        background: white;
                        border-radius: 15px;
                        padding: 25px;
                        margin-bottom: 25px;
                        box-shadow: 0 10px 30px rgba(0,0,0,0.2);
                        text-align: center;
                    }
                    
                    h1 {
                        color: #2d3748;
                        font-size: 2.8rem;
                        margin-bottom: 10px;
                        background: linear-gradient(90deg, #667eea, #764ba2);
                        -webkit-background-clip: text;
                        -webkit-text-fill-color: transparent;
                    }
                    
                    .subtitle {
                        color: #718096;
                        font-size: 1.2rem;
                        margin-bottom: 20px;
                    }
                    
                    .game-container {
                        display: grid;
                        grid-template-columns: 2fr 1fr;
                        gap: 25px;
                        margin-bottom: 25px;
                    }
                    
                    @media (max-width: 768px) {
                        .game-container {
                            grid-template-columns: 1fr;
                        }
                    }
                    
                    .game-board {
                        background: white;
                        border-radius: 15px;
                        padding: 25px;
                        box-shadow: 0 10px 30px rgba(0,0,0,0.2);
                    }
                    
                    .bingo-grid {
                        display: grid;
                        grid-template-columns: repeat(5, 1fr);
                        gap: 12px;
                        margin: 25px 0;
                    }
                    
                    .bingo-cell {
                        aspect-ratio: 1;
                        background: linear-gradient(135deg, #f6d365 0%, #fda085 100%);
                        border-radius: 10px;
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        font-size: 1.8rem;
                        font-weight: bold;
                        color: #2d3748;
                        cursor: pointer;
                        transition: all 0.3s ease;
                        box-shadow: 0 5px 15px rgba(0,0,0,0.1);
                    }
                    
                    .bingo-cell:hover {
                        transform: translateY(-5px);
                        box-shadow: 0 15px 30px rgba(0,0,0,0.2);
                    }
                    
                    .bingo-cell.marked {
                        background: linear-gradient(135deg, #4CAF50 0%, #2E7D32 100%);
                        color: white;
                    }
                    
                    .bingo-cell.free {
                        background: linear-gradient(135deg, #9C27B0 0%, #673AB7 100%);
                        color: white;
                    }
                    
                    .bingo-header {
                        display: grid;
                        grid-template-columns: repeat(5, 1fr);
                        gap: 12px;
                        margin-bottom: 15px;
                    }
                    
                    .bingo-header-cell {
                        text-align: center;
                        font-weight: bold;
                        font-size: 1.5rem;
                        color: #667eea;
                        padding: 10px;
                    }
                    
                    .game-info {
                        background: white;
                        border-radius: 15px;
                        padding: 25px;
                        box-shadow: 0 10px 30px rgba(0,0,0,0.2);
                    }
                    
                    .info-section {
                        margin-bottom: 25px;
                    }
                    
                    .info-section h3 {
                        color: #2d3748;
                        margin-bottom: 15px;
                        padding-bottom: 10px;
                        border-bottom: 2px solid #e2e8f0;
                    }
                    
                    .stat-item {
                        display: flex;
                        justify-content: space-between;
                        margin-bottom: 12px;
                        padding: 12px;
                        background: #f8fafc;
                        border-radius: 8px;
                    }
                    
                    .stat-label {
                        color: #718096;
                        font-weight: 600;
                    }
                    
                    .stat-value {
                        color: #2d3748;
                        font-weight: bold;
                        font-size: 1.1rem;
                    }
                    
                    .countdown {
                        text-align: center;
                        margin: 20px 0;
                    }
                    
                    .countdown-timer {
                        font-size: 3.5rem;
                        font-weight: bold;
                        color: #e53e3e;
                        margin: 15px 0;
                    }
                    
                    .game-phase {
                        font-size: 1.4rem;
                        color: #667eea;
                        font-weight: bold;
                        text-transform: uppercase;
                        letter-spacing: 2px;
                    }
                    
                    .called-numbers {
                        display: flex;
                        flex-wrap: wrap;
                        gap: 10px;
                        margin-top: 15px;
                    }
                    
                    .called-number {
                        width: 50px;
                        height: 50px;
                        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                        border-radius: 50%;
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        color: white;
                        font-weight: bold;
                        font-size: 1.2rem;
                    }
                    
                    .called-number.current {
                        background: linear-gradient(135deg, #f56565 0%, #e53e3e 100%);
                        transform: scale(1.1);
                        box-shadow: 0 0 20px rgba(245, 101, 101, 0.5);
                    }
                    
                    .controls {
                        display: flex;
                        gap: 15px;
                        margin-top: 25px;
                    }
                    
                    button {
                        flex: 1;
                        padding: 18px;
                        border: none;
                        border-radius: 10px;
                        font-size: 1.1rem;
                        font-weight: bold;
                        cursor: pointer;
                        transition: all 0.3s ease;
                        box-shadow: 0 5px 15px rgba(0,0,0,0.1);
                    }
                    
                    button:hover {
                        transform: translateY(-3px);
                        box-shadow: 0 10px 25px rgba(0,0,0,0.2);
                    }
                    
                    .btn-primary {
                        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                        color: white;
                    }
                    
                    .btn-success {
                        background: linear-gradient(135deg, #38a169 0%, #2f855a 100%);
                        color: white;
                    }
                    
                    .btn-danger {
                        background: linear-gradient(135deg, #f56565 0%, #e53e3e 100%);
                        color: white;
                    }
                    
                    .btn-bingo {
                        background: linear-gradient(135deg, #ed8936 0%, #dd6b20 100%);
                        color: white;
                        font-size: 1.4rem;
                        padding: 22px;
                    }
                    
                    .card-purchase {
                        display: grid;
                        grid-template-columns: repeat(3, 1fr);
                        gap: 15px;
                        margin-top: 20px;
                    }
                    
                    .card-option {
                        background: #f8fafc;
                        border: 2px solid #e2e8f0;
                        border-radius: 10px;
                        padding: 20px;
                        text-align: center;
                        cursor: pointer;
                        transition: all 0.3s ease;
                    }
                    
                    .card-option:hover {
                        border-color: #667eea;
                        transform: translateY(-5px);
                    }
                    
                    .card-option.selected {
                        border-color: #38a169;
                        background: #f0fff4;
                    }
                    
                    .card-option.sold {
                        border-color: #e53e3e;
                        background: #fff5f5;
                        opacity: 0.7;
                        cursor: not-allowed;
                    }
                    
                    .card-price {
                        font-size: 1.5rem;
                        font-weight: bold;
                        color: #667eea;
                        margin: 10px 0;
                    }
                    
                    .user-balance {
                        background: linear-gradient(135deg, #f6e05e 0%, #d69e2e 100%);
                        padding: 15px;
                        border-radius: 10px;
                        text-align: center;
                        margin: 20px 0;
                    }
                    
                    .balance-amount {
                        font-size: 2.2rem;
                        font-weight: bold;
                        color: #744210;
                    }
                    
                    .notifications {
                        position: fixed;
                        top: 20px;
                        right: 20px;
                        width: 350px;
                        z-index: 1000;
                    }
                    
                    .notification {
                        background: white;
                        border-radius: 10px;
                        padding: 20px;
                        margin-bottom: 15px;
                        box-shadow: 0 10px 30px rgba(0,0,0,0.2);
                        border-left: 5px solid #667eea;
                        animation: slideIn 0.3s ease;
                    }
                    
                    .notification.success {
                        border-left-color: #38a169;
                    }
                    
                    .notification.error {
                        border-left-color: #e53e3e;
                    }
                    
                    .notification.warning {
                        border-left-color: #ed8936;
                    }
                    
                    @keyframes slideIn {
                        from {
                            transform: translateX(100%);
                            opacity: 0;
                        }
                        to {
                            transform: translateX(0);
                            opacity: 1;
                        }
                    }
                    
                    .loader {
                        border: 5px solid #f3f3f3;
                        border-top: 5px solid #667eea;
                        border-radius: 50%;
                        width: 50px;
                        height: 50px;
                        animation: spin 1s linear infinite;
                        margin: 20px auto;
                    }
                    
                    @keyframes spin {
                        0% { transform: rotate(0deg); }
                        100% { transform: rotate(360deg); }
                    }
                    
                    .winner-banner {
                        position: fixed;
                        top: 0;
                        left: 0;
                        right: 0;
                        bottom: 0;
                        background: rgba(0,0,0,0.9);
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        z-index: 2000;
                        animation: fadeIn 0.5s ease;
                    }
                    
                    .winner-content {
                        background: white;
                        padding: 50px;
                        border-radius: 20px;
                        text-align: center;
                        max-width: 600px;
                        animation: scaleIn 0.5s ease;
                    }
                    
                    .winner-text {
                        font-size: 4rem;
                        color: #e53e3e;
                        margin-bottom: 20px;
                        text-shadow: 3px 3px 0 #f6e05e;
                    }
                    
                    .prize-amount {
                        font-size: 3rem;
                        color: #38a169;
                        margin: 20px 0;
                    }
                    
                    @keyframes fadeIn {
                        from { opacity: 0; }
                        to { opacity: 1; }
                    }
                    
                    @keyframes scaleIn {
                        from { transform: scale(0.5); opacity: 0; }
                        to { transform: scale(1); opacity: 1; }
                    }
                    
                    .mobile-warning {
                        display: none;
                        background: #f6ad55;
                        color: #744210;
                        padding: 15px;
                        border-radius: 10px;
                        text-align: center;
                        margin: 20px 0;
                    }
                    
                    @media (max-width: 768px) {
                        .mobile-warning {
                            display: block;
                        }
                        
                        .bingo-cell {
                            font-size: 1.4rem;
                        }
                        
                        .countdown-timer {
                            font-size: 2.5rem;
                        }
                        
                        .winner-text {
                            font-size: 2.5rem;
                        }
                    }
                </style>
            </head>
            <body>
                <div class="container">
                    <header>
                        <h1>🎯 Habesha Bingo</h1>
                        <div class="subtitle">Server-Coordinated • Real-Time • Lightning Fast Verification</div>
                    </header>
                    
                    <div class="mobile-warning">
                        📱 For best experience, please use desktop or tablet with landscape orientation
                    </div>
                    
                    <div class="game-container">
                        <div class="game-board">
                            <h2>🎮 Your Bingo Card</h2>
                            
                            <div class="bingo-header">
                                <div class="bingo-header-cell">B</div>
                                <div class="bingo-header-cell">I</div>
                                <div class="bingo-header-cell">N</div>
                                <div class="bingo-header-cell">G</div>
                                <div class="bingo-header-cell">O</div>
                            </div>
                            
                            <div class="bingo-grid" id="bingoGrid">
                                <!-- Bingo cells will be populated by JavaScript -->
                            </div>
                            
                            <div class="controls">
                                <button class="btn-bingo" id="claimBingoBtn" onclick="claimBingo()">
                                    🚨 CLAIM BINGO
                                </button>
                                <button class="btn-primary" id="syncBtn" onclick="forceSync()">
                                    🔄 SYNC
                                </button>
                            </div>
                        </div>
                        
                        <div class="game-info">
                            <div class="info-section">
                                <h3>📊 Game Info</h3>
                                <div class="game-phase" id="gamePhase">CARD PURCHASE</div>
                                
                                <div class="countdown">
                                    <div>Time Remaining:</div>
                                    <div class="countdown-timer" id="countdownTimer">30</div>
                                </div>
                                
                                <div class="stat-item">
                                    <span class="stat-label">Game ID:</span>
                                    <span class="stat-value" id="gameId">Loading...</span>
                                </div>
                                
                                <div class="stat-item">
                                    <span class="stat-label">Round:</span>
                                    <span class="stat-value" id="roundNumber">1</span>
                                </div>
                                
                                <div class="stat-item">
                                    <span class="stat-label">Players:</span>
                                    <span class="stat-value" id="playerCount">0</span>
                                </div>
                                
                                <div class="stat-item">
                                    <span class="stat-label">Prize Pool:</span>
                                    <span class="stat-value" id="prizePool">0 birr</span>
                                </div>
                            </div>
                            
                            <div class="info-section">
                                <h3>💰 Your Balance</h3>
                                <div class="user-balance">
                                    <div>Available Balance</div>
                                    <div class="balance-amount" id="userBalance">10.00 birr</div>
                                </div>
                            </div>
                            
                            <div class="info-section">
                                <h3>🎲 Called Numbers</h3>
                                <div class="called-numbers" id="calledNumbers">
                                    <!-- Called numbers will be populated by JavaScript -->
                                </div>
                            </div>
                            
                            <div class="info-section">
                                <h3>🛒 Card Purchase</h3>
                                <div class="card-purchase" id="cardPurchase">
                                    <!-- Card purchase options will be populated by JavaScript -->
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
                
                <div class="notifications" id="notifications"></div>
                
                <div id="winnerBanner" class="winner-banner" style="display: none;">
                    <div class="winner-content">
                        <div class="winner-text">🎉 BINGO! 🎉</div>
                        <h2>You Won!</h2>
                        <div class="prize-amount" id="prizeAmount">0 birr</div>
                        <p id="winnerMessage">Congratulations! Your bingo has been verified!</p>
                        <button class="btn-success" onclick="closeWinnerBanner()">Continue</button>
                    </div>
                </div>
                
                <script>
                    // Game state
                    let gameState = {
                        gameId: null,
                        userId: Math.floor(Math.random() * 1000000),
                        hasCard: false,
                        cardNumbers: [],
                        markedNumbers: new Set(),
                        calledNumbers: [],
                        gamePhase: 'card_purchase',
                        countdown: 30,
                        playerCount: 0,
                        prizePool: 0,
                        roundNumber: 1,
                        userBalance: 10.00,
                        soldCards: []
                    };
                    
                    // WebSocket connection
                    let ws = null;
                    let syncInterval = null;
                    
                    // Initialize game
                    async function initGame() {
                        showNotification('🔌 Connecting to server...', 'info');
                        
                        // Generate user ID or get from URL
                        const urlParams = new URLSearchParams(window.location.search);
                        gameState.userId = urlParams.get('user_id') || Math.floor(Math.random() * 1000000);
                        
                        // Connect WebSocket
                        connectWebSocket();
                        
                        // Start sync interval
                        syncInterval = setInterval(syncWithServer, 3000);
                        
                        // Initial sync
                        await syncWithServer();
                        
                        showNotification('✅ Connected to Habesha Bingo!', 'success');
                    }
                    
                    // Connect to WebSocket
                    function connectWebSocket() {
                        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
                        const wsUrl = `${protocol}//${window.location.host}/ws`;
                        
                        ws = new WebSocket(wsUrl);
                        
                        ws.onopen = function() {
                            console.log('WebSocket connected');
                            // Authenticate
                            ws.send(JSON.stringify({
                                type: 'auth',
                                userId: gameState.userId.toString()
                            }));
                            
                            // Request active game info
                            ws.send(JSON.stringify({
                                type: 'get_active_game'
                            }));
                        };
                        
                        ws.onmessage = function(event) {
                            try {
                                const data = JSON.parse(event.data);
                                handleWebSocketMessage(data);
                            } catch (error) {
                                console.error('Error parsing WebSocket message:', error);
                            }
                        };
                        
                        ws.onerror = function(error) {
                            console.error('WebSocket error:', error);
                            showNotification('❌ Connection error', 'error');
                        };
                        
                        ws.onclose = function() {
                            console.log('WebSocket disconnected');
                            showNotification('🔌 Disconnected from server', 'warning');
                            // Try to reconnect after 3 seconds
                            setTimeout(connectWebSocket, 3000);
                        };
                    }
                    
                    // Handle WebSocket messages
                    function handleWebSocketMessage(data) {
                        console.log('WebSocket message:', data.type);
                        console.log('file is not imported, you are seeing thisfrom web_server.py not from game.html')
                        switch (data.type) {
                            case 'auth_success':
                                showNotification(`✅ Authenticated as User ${gameState.userId}`, 'success');
                                break;
                                
                            case 'active_game_info':
                                gameState.gameId = data.game_id;
                                gameState.gamePhase = data.phase;
                                gameState.roundNumber = data.round_number || 1;
                                gameState.prizePool = data.prize_pool || 0;
                                gameState.countdown = data.countdown_remaining || 30;
                                updateUI();
                                break;
                                
                            case 'no_active_game':
                                showNotification('No active game found', 'warning');
                                break;
                                
                            case 'number_called':
                                const number = data.number;
                                if (!gameState.calledNumbers.includes(number)) {
                                    gameState.calledNumbers.push(number);
                                    updateCalledNumbers();
                                    markNumberOnCard(number);
                                    playSound('numberCalled');
                                }
                                break;
                                
                            case 'card_purchased':
                                showNotification(`✅ Card purchased by User ${data.user_id}`, 'info');
                                if (data.user_id == gameState.userId) {
                                    gameState.hasCard = true;
                                    loadCardData();
                                }
                                updateSoldCards(data.card_index);
                                break;
                                
                            case 'bingo_claim_verified':
                                showWinnerBanner(data.prize_amount, data.pattern_type);
                                playSound('winner');
                                break;
                                
                            case 'bingo_rejected':
                                showNotification(`❌ ${data.reason}`, 'error');
                                break;
                                
                            case 'sync_response':
                                if (data.has_active_game) {
                                    updateGameState(data.server_state);
                                }
                                break;
                                
                            case 'countdown_correction':
                                gameState.countdown = data.server_countdown;
                                updateUI();
                                showNotification(`⏰ Countdown corrected to ${data.server_countdown}s`, 'info');
                                break;
                                
                            case 'phase_transition':
                                gameState.gamePhase = data.to_phase;
                                gameState.countdown = data.countdown || 30;
                                updateUI();
                                showNotification(`🔄 Phase changed to ${data.to_phase}`, 'info');
                                break;
                                
                            case 'admin_game_started':
                                showNotification(`🎮 Game ${data.game_id} started by admin`, 'info');
                                break;
                                
                            case 'admin_game_stopped':
                                showNotification(`🛑 Game ${data.game_id} stopped by admin`, 'warning');
                                break;
                                
                            case 'admin_number_called':
                                showNotification(`🎲 Number ${data.number} called by admin`, 'info');
                                break;
                                
                            case 'pong':
                                // Keep-alive response
                                break;
                        }
                    }
                    
                    // Sync with server
                    async function syncWithServer() {
                        if (!gameState.gameId) return;
                        
                        try {
                            // Use WebSocket for sync if connected
                            if (ws && ws.readyState === WebSocket.OPEN) {
                                ws.send(JSON.stringify({
                                    type: 'request_sync',
                                    game_id: gameState.gameId,
                                    user_id: gameState.userId
                                }));
                            } else {
                                // Fallback to HTTP API
                                const response = await fetch(`/api/game/${gameState.gameId}/sync`, {
                                    method: 'POST',
                                    headers: { 'Content-Type': 'application/json' },
                                    body: JSON.stringify({
                                        game_phase: gameState.gamePhase,
                                        called_numbers: gameState.calledNumbers,
                                        countdown: gameState.countdown,
                                        user_id: gameState.userId
                                    })
                                });
                                
                                const data = await response.json();
                                if (data.has_active_game && data.server_state) {
                                    updateGameState(data.server_state);
                                }
                            }
                        } catch (error) {
                            console.error('Sync error:', error);
                        }
                    }
                    
                    // Force sync
                    function forceSync() {
                        syncWithServer();
                        showNotification('🔄 Syncing with server...', 'info');
                    }
                    
                    // Update game state from server
                    function updateGameState(serverState) {
                        gameState.gamePhase = serverState.game_phase;
                        gameState.gameStatus = serverState.game_status;
                        gameState.countdown = serverState.countdown_remaining;
                        gameState.playerCount = serverState.player_count;
                        gameState.prizePool = serverState.prize_pool;
                        gameState.roundNumber = serverState.round_number;
                        
                        // Update called numbers if server has more
                        if (serverState.called_numbers && serverState.called_numbers.length > gameState.calledNumbers.length) {
                            gameState.calledNumbers = [...serverState.called_numbers];
                            updateCalledNumbers();
                        }
                        
                        updateUI();
                    }
                    
                    // Update UI
                    function updateUI() {
                        // Update game phase
                        document.getElementById('gamePhase').textContent = gameState.gamePhase.toUpperCase();
                        document.getElementById('gameId').textContent = gameState.gameId || 'Loading...';
                        document.getElementById('roundNumber').textContent = gameState.roundNumber;
                        document.getElementById('playerCount').textContent = gameState.playerCount;
                        document.getElementById('prizePool').textContent = gameState.prizePool.toFixed(2) + ' birr';
                        document.getElementById('userBalance').textContent = gameState.userBalance.toFixed(2) + ' birr';
                        document.getElementById('countdownTimer').textContent = gameState.countdown;
                        
                        // Update card purchase section
                        updateCardPurchase();
                        
                        // Update called numbers
                        updateCalledNumbers();
                        
                        // Show/hide controls based on phase
                        const claimBtn = document.getElementById('claimBingoBtn');
                        claimBtn.disabled = gameState.gamePhase !== 'active' || !gameState.hasCard;
                    }
                    
                    // Load card data
                    async function loadCardData() {
                        try {
                            const response = await fetch(`/api/game/${gameState.gameId}/user-state/${gameState.userId}`);
                            const data = await response.json();
                            
                            if (data.success && data.user_card) {
                                gameState.hasCard = true;
                                
                                // Parse card numbers
                                let cardNumbers = [];
                                if (data.user_card.card_data) {
                                    try {
                                        cardNumbers = JSON.parse(data.user_card.card_data);
                                    } catch {
                                        cardNumbers = data.user_card.card_data;
                                    }
                                }
                                
                                if (Array.isArray(cardNumbers) && cardNumbers.length === 25) {
                                    gameState.cardNumbers = cardNumbers;
                                    renderBingoCard();
                                }
                            }
                        } catch (error) {
                            console.error('Error loading card data:', error);
                        }
                    }
                    
                    // Render bingo card
                    function renderBingoCard() {
                        const grid = document.getElementById('bingoGrid');
                        grid.innerHTML = '';
                        
                        for (let i = 0; i < 25; i++) {
                            const cell = document.createElement('div');
                            cell.className = 'bingo-cell';
                            
                            // Center is FREE space
                            if (i === 12) {
                                cell.textContent = 'FREE';
                                cell.classList.add('free');
                                cell.classList.add('marked');
                            } else {
                                cell.textContent = gameState.cardNumbers[i] || '';
                                
                                // Mark if called
                                if (gameState.calledNumbers.includes(gameState.cardNumbers[i])) {
                                    cell.classList.add('marked');
                                }
                            }
                            
                            grid.appendChild(cell);
                        }
                    }
                    
                    // Mark number on card
                    function markNumberOnCard(number) {
                        const index = gameState.cardNumbers.indexOf(number);
                        if (index !== -1 && index !== 12) {
                            const cells = document.querySelectorAll('.bingo-cell');
                            if (cells[index]) {
                                cells[index].classList.add('marked');
                            }
                        }
                    }
                    
                    // Update called numbers display
                    function updateCalledNumbers() {
                        const container = document.getElementById('calledNumbers');
                        container.innerHTML = '';
                        
                        // Show last 10 called numbers
                        const recentNumbers = gameState.calledNumbers.slice(-10);
                        
                        recentNumbers.forEach(number => {
                            const div = document.createElement('div');
                            div.className = 'called-number';
                            div.textContent = number;
                            container.appendChild(div);
                        });
                    }
                    
                    // Update card purchase section
                    function updateCardPurchase() {
                        const container = document.getElementById('cardPurchase');
                        
                        if (gameState.gamePhase !== 'card_purchase') {
                            container.innerHTML = '<p>Card purchase closed</p>';
                            return;
                        }
                        
                        container.innerHTML = '';
                        
                        // Create 3 card options
                        for (let i = 1; i <= 3; i++) {
                            const option = document.createElement('div');
                            option.className = 'card-option';
                            
                            if (gameState.soldCards.includes(i)) {
                                option.classList.add('sold');
                                option.innerHTML = `
                                    <div>Card #${i}</div>
                                    <div class="card-price">10 birr</div>
                                    <div>SOLD</div>
                                `;
                            } else if (gameState.hasCard) {
                                option.classList.add('selected');
                                option.innerHTML = `
                                    <div>Card #${i}</div>
                                    <div class="card-price">10 birr</div>
                                    <div>YOUR CARD</div>
                                `;
                            } else {
                                option.onclick = () => purchaseCard(i);
                                option.innerHTML = `
                                    <div>Card #${i}</div>
                                    <div class="card-price">10 birr</div>
                                    <button class="btn-primary" style="margin-top: 10px;">BUY NOW</button>
                                `;
                            }
                            
                            container.appendChild(option);
                        }
                    }
                    
                    // Update sold cards
                    function updateSoldCards(cardIndex) {
                        if (!gameState.soldCards.includes(cardIndex)) {
                            gameState.soldCards.push(cardIndex);
                            updateCardPurchase();
                        }
                    }
                    
                    // Purchase card
                    async function purchaseCard(cardIndex) {
                        if (gameState.userBalance < 10) {
                            showNotification('❌ Insufficient balance', 'error');
                            return;
                        }
                        
                        try {
                            const response = await fetch(`/api/game/${gameState.gameId}/toggle-card`, {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({
                                    user_id: gameState.userId,
                                    card_index: cardIndex,
                                    action: 'buy'
                                })
                            });
                            
                            const data = await response.json();
                            if (data.success) {
                                gameState.userBalance = data.new_balance;
                                gameState.prizePool = data.prize_pool;
                                gameState.hasCard = true;
                                updateUI();
                                loadCardData();
                                showNotification('✅ Card purchased successfully!', 'success');
                                playSound('purchase');
                            } else {
                                showNotification(`❌ ${data.message}`, 'error');
                            }
                        } catch (error) {
                            console.error('Error purchasing card:', error);
                            showNotification('❌ Purchase failed', 'error');
                        }
                    }
                    
                    // Claim bingo
                    async function claimBingo() {
                        if (!gameState.hasCard) {
                            showNotification('❌ You need a card to claim bingo', 'error');
                            return;
                        }
                        
                        if (gameState.gamePhase !== 'active') {
                            showNotification('❌ Game is not active', 'error');
                            return;
                        }
                        
                        // Visual feedback
                        const btn = document.getElementById('claimBingoBtn');
                        btn.disabled = true;
                        btn.textContent = 'VERIFYING...';
                        
                        try {
                            const response = await fetch(`/api/game/${gameState.gameId}/claim-bingo`, {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({
                                    user_id: gameState.userId
                                })
                            });
                            
                            const data = await response.json();
                            
                            if (data.success) {
                                showNotification('✅ Bingo claim submitted!', 'success');
                                // Server will send verification result via WebSocket
                            } else {
                                showNotification(`❌ ${data.message}`, 'error');
                            }
                        } catch (error) {
                            console.error('Error claiming bingo:', error);
                            showNotification('❌ Claim failed', 'error');
                        } finally {
                            btn.disabled = false;
                            btn.textContent = '🚨 CLAIM BINGO';
                        }
                    }
                    
                    // Show winner banner
                    function showWinnerBanner(prizeAmount, patternType) {
                        document.getElementById('prizeAmount').textContent = prizeAmount.toFixed(2) + ' birr';
                        document.getElementById('winnerMessage').textContent = `You won with ${patternType} pattern!`;
                        document.getElementById('winnerBanner').style.display = 'flex';
                    }
                    
                    // Close winner banner
                    function closeWinnerBanner() {
                        document.getElementById('winnerBanner').style.display = 'none';
                    }
                    
                    // Show notification
                    function showNotification(message, type = 'info') {
                        const container = document.getElementById('notifications');
                        const notification = document.createElement('div');
                        notification.className = `notification ${type}`;
                        notification.textContent = message;
                        container.appendChild(notification);
                        
                        // Remove after 5 seconds
                        setTimeout(() => {
                            notification.remove();
                        }, 5000);
                    }
                    
                    // Play sound
                    function playSound(type) {
                        // Simple sound notification (could be expanded with actual audio files)
                        if (type === 'numberCalled') {
                            // Beep sound
                            try {
                                const audio = new Audio('/sounds/beep.mp3');
                                audio.play().catch(e => console.log('Audio play failed:', e));
                            } catch (e) {
                                // Fallback to Web Audio API
                                playBeep(800, 200);
                            }
                        } else if (type === 'winner') {
                            // Winner sound
                            try {
                                const audio = new Audio('/sounds/winner.mp3');
                                audio.play().catch(e => console.log('Audio play failed:', e));
                            } catch (e) {
                                playBeep(1200, 500);
                            }
                        } else if (type === 'purchase') {
                            // Purchase sound
                            try {
                                const audio = new Audio('/sounds/purchase.mp3');
                                audio.play().catch(e => console.log('Audio play failed:', e));
                            } catch (e) {
                                playBeep(1000, 300);
                            }
                        }
                    }
                    
                    // Fallback beep sound using Web Audio API
                    function playBeep(frequency, duration) {
                        try {
                            const audioContext = new (window.AudioContext || window.webkitAudioContext)();
                            const oscillator = audioContext.createOscillator();
                            const gainNode = audioContext.createGain();
                            
                            oscillator.connect(gainNode);
                            gainNode.connect(audioContext.destination);
                            
                            oscillator.frequency.value = frequency;
                            oscillator.type = 'sine';
                            
                            gainNode.gain.setValueAtTime(0.3, audioContext.currentTime);
                            gainNode.gain.exponentialRampToValueAtTime(0.01, audioContext.currentTime + duration / 1000);
                            
                            oscillator.start(audioContext.currentTime);
                            oscillator.stop(audioContext.currentTime + duration / 1000);
                        } catch (e) {
                            console.log('Web Audio API not supported');
                        }
                    }
                    
                    // Initialize when page loads
                    window.onload = initGame;
                    
                    // Handle beforeunload
                    window.onbeforeunload = function() {
                        if (syncInterval) {
                            clearInterval(syncInterval);
                        }
                        if (ws) {
                            ws.close();
                        }
                    };
                </script>
            </body>
            </html>
"""