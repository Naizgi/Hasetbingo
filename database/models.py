CREATE_USERS = """
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    telegram_id BIGINT UNIQUE,
    username TEXT,
    balance INT DEFAULT 0,
    is_admin BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);
"""

CREATE_GAMES = """
CREATE TABLE IF NOT EXISTS games (
    id SERIAL PRIMARY KEY,
    status TEXT,
    price_per_card INT,
    created_at TIMESTAMP DEFAULT NOW()
);
"""

CREATE_CARDS = """
CREATE TABLE IF NOT EXISTS bingo_cards (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id),
    game_id INT REFERENCES games(id),
    numbers JSONB,
    is_winner BOOLEAN DEFAULT FALSE
);
"""

CREATE_PAYMENTS = """
CREATE TABLE IF NOT EXISTS payments (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id),
    amount INT,
    transaction_id TEXT,
    status TEXT DEFAULT 'pending'
);
"""
