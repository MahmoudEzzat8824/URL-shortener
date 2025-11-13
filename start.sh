#!/bin/bash

# Activate virtual environment if it exists
if [ -d "venv" ]; then
    echo "Activating virtual environment..."
    source venv/bin/activate
elif [ -d "../venv" ]; then
    echo "Activating virtual environment..."
    source ../venv/bin/activate
fi

# Kill any stopped/hung Redis processes first
pkill -9 redis-server 2>/dev/null
sleep 1

# Start Redis in the background
echo "Starting Redis server..."
redis-server --daemonize yes
sleep 2

# Check if Redis is running and responding
if redis-cli ping > /dev/null 2>&1; then
    echo "✓ Redis is running"
else
    echo "✗ Failed to start Redis"
    exit 1
fi

# Start Flask app
echo "Starting Flask app..."
echo "----------------------------------------"
echo "Server will be running at:"
echo "  http://127.0.0.1:5001"
echo "  http://localhost:5001"
echo "----------------------------------------"
echo "Press Ctrl+C to stop both services"
echo ""

# Trap Ctrl+C to clean up
trap 'echo ""; echo "Stopping services..."; redis-cli shutdown > /dev/null 2>&1; exit 0' INT

# Run Flask app
python app.py
