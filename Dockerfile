FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Install system dependencies (no Node.js needed)
RUN apt-get update && apt-get install -y \
    curl \
    wget \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (better caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the app
COPY . .

# Create logs directory with proper permissions
RUN mkdir -p logs && chmod 777 logs

# Remove scraper directory if it exists (not needed anymore)
RUN rm -rf scraper 2>/dev/null || true

# Run the bot
CMD ["python", "bot.py"]