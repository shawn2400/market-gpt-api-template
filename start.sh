#!/bin/bash
# ================================================================================
# AlgoGPT Startup Script for Render
# ================================================================================
# This script starts the main Gunicorn server + all 10 background workers
# ================================================================================

set -e  # Exit on error

echo "🚀 Starting AlgoGPT Production System..."
echo "=========================================="

# Set default PORT if not set
export PORT=${PORT:-10000}
export PYTHONPATH=${PYTHONPATH:-/app}

# ===================================================================
# START BACKGROUND WORKERS
# ===================================================================

echo "📡 Starting background workers..."

# 1. Auto Health Monitor
echo "  → Auto Health Monitor"
python workers/auto_health_monitor.py &
HEALTH_PID=$!

# 2. Auto Scanner (GPT Auto Suggest)
echo "  → Auto Scanner"
python workers/gpt_auto_suggest.py &
SCANNER_PID=$!

# 3. Daily Digest
echo "  → Daily Digest"
python workers/daily_digest.py &
DIGEST_PID=$!

# 4. GPT-5 Central Brain (Orchestrator)
echo "  → GPT-5 Orchestrator"
python workers/gpt5_orchestrator.py &
GPT5_PID=$!

# 5. GitHub Auto-Commit
echo "  → GitHub Auto-Commit"
python workers/github_auto_commit.py &
GITHUB_PID=$!

# 6. Heartbeat Monitor
echo "  → Heartbeat Monitor"
python workers/system_heartbeat.py &
HEARTBEAT_PID=$!

# 7. N8N Bridge
echo "  → N8N Bridge"
python workers/n8n_bridge.py &
N8N_PID=$!

# 8. Position Monitor
echo "  → Position Monitor"
python workers/position_monitor.py &
POSITION_PID=$!

# 9. Sentinel Security
echo "  → Sentinel Security"
python workers/sentinel_security.py &
SENTINEL_PID=$!

echo "✅ All 9 background workers started"

# Give workers 5 seconds to initialize
echo "⏳ Waiting 5 seconds for workers to initialize..."
sleep 5

# ===================================================================
# START MAIN GUNICORN SERVER
# ===================================================================

echo "🌐 Starting Gunicorn server on port $PORT..."
echo "=========================================="

# Cleanup function to kill all background workers on exit
cleanup() {
    echo ""
    echo "🛑 Shutting down AlgoGPT..."
    echo "  → Stopping background workers..."
    kill $HEALTH_PID $SCANNER_PID $DIGEST_PID $GPT5_PID $GITHUB_PID $HEARTBEAT_PID $N8N_PID $POSITION_PID $SENTINEL_PID 2>/dev/null || true
    echo "  → Stopping Gunicorn..."
    exit 0
}

# Trap SIGTERM and SIGINT (Ctrl+C)
trap cleanup SIGTERM SIGINT

# Start Gunicorn with production config
exec gunicorn -c gunicorn_conf.py main:app
