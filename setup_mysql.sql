-- Create database if not exists
CREATE DATABASE IF NOT EXISTS habesha_bingo 
CHARACTER SET utf8mb4 
COLLATE utf8mb4_unicode_ci;

-- Grant privileges (adjust as needed)
GRANT ALL PRIVILEGES ON habesha_bingo.* TO 'root'@'localhost';
FLUSH PRIVILEGES;

-- Use the database
USE habesha_bingo;