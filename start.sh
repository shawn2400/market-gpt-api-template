#!/bin/bash
set -e

echo "🚀 AlgoGPT v10.4.0 - Starting Services..."

# Load environment variables
if [ -f ".env" ]; then
    set -a
    source .env
    set +a
fi

# Check for main.py
if [ ! -f "main.py" ]; then
    echo "❌ main.py not found!"
    exit 1
fi

# Start FastAPI backend with Gunicorn
echo "🔥 Starting FastAPI Backend (port ${PORT:-8008})..."
cd /app

if [ -f "gunicorn_conf.py" ]; then
    exec gunicorn -c gunicorn_conf.py main:app
else
    exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8008}
fi
