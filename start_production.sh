#!/bin/bash
# AlgoGPT Production Startup Script
# Runs FastAPI + 10 Workers in parallel with auto-restart on crash
# For Replit Reserved VM Deployment (24/7 autonomous operation)

set -e

echo "🚀 AlgoGPT Production Startup - 24/7 Autonomous Mode"
echo "=================================================="

# Environment
export PYTHONUNBUFFERED=1
export PYTHONPATH=/home/runner/$REPL_SLUG

# Log directory
LOGS_DIR="/tmp/algogpt_logs"
mkdir -p $LOGS_DIR

# PID tracking
PIDS=()

# Cleanup function
cleanup() {
    echo "⚠️ Received shutdown signal, cleaning up..."
    for pid in "${PIDS[@]}"; do
        kill -TERM "$pid" 2>/dev/null || true
    done
    wait
    echo "✅ All processes terminated"
    exit 0
}

trap cleanup SIGTERM SIGINT

# Auto-restart wrapper
start_service() {
    local name="$1"
    local cmd="$2"
    
    while true; do
        echo "▶️ Starting: $name"
        eval "$cmd" > "$LOGS_DIR/${name}.log" 2>&1 &
        local pid=$!
        echo "   PID: $pid"
        
        wait $pid
        local exit_code=$?
        
        echo "⚠️ $name exited with code $exit_code, restarting in 5s..."
        sleep 5
    done
}

echo ""
echo "🔧 Starting FastAPI Server (Gunicorn)..."
start_service "fastapi" "gunicorn -c gunicorn_conf.py main:app" &
PIDS+=($!)
sleep 3

echo ""
echo "🤖 Starting 10 Background Workers..."

# Worker 1: Auto Health Monitor
start_service "health-monitor" \
    "BASE_URL=http://127.0.0.1:5000 HEALTH_CHECK_INTERVAL=30 AUTO_FIX_ENABLE=1 TELEGRAM_SEND_ENABLE=1 python workers/auto_health_monitor.py" &
PIDS+=($!)

# Worker 2: Fills Watcher
start_service "fills-watcher" \
    "FILLS_WATCH_ENABLE=1 FILLS_WATCH_INTERVAL_SEC=15 python workers/fills_watcher.py" &
PIDS+=($!)

# Worker 3: Position Monitor
start_service "position-monitor" \
    "ENABLE_POSITION_MONITOR=1 ENABLE_AUTO_PROTECT=1 POSITION_REPORT_INTERVAL_SEC=1800 AUTO_PROTECT_INTERVAL_SEC=30 POSITION_ALERT_LEVEL=all python workers/position_monitor.py" &
PIDS+=($!)

# Worker 4: Sentinel Security
start_service "sentinel" \
    "SENTINEL_ENABLED=1 SENTINEL_ALERT_LEVEL=critical python workers/sentinel_security.py" &
PIDS+=($!)

# Worker 5: Telegram Digest Reporter
start_service "telegram-digest" \
    "python workers/telegram_digest_reporter.py" &
PIDS+=($!)

# Worker 6: Auto Cleanup
start_service "auto-cleanup" \
    "CLEANUP_INTERVAL_SEC=21600 LOGS_RETENTION_DAYS=7 AI_REVIEWS_KEEP_COUNT=100 IMPROVEMENTS_RETENTION_DAYS=30 python workers/auto_cleanup.py" &
PIDS+=($!)

# Worker 7: Auto Scanner (GRID Proposals)
start_service "auto-scanner" \
    "POOL_PER_CYCLE=50 SUGGEST_GRID=1 AUTO_RUN=1 MIN_QUALITY_SCORE=6.0 python workers/gpt_auto_suggest.py" &
PIDS+=($!)

# Worker 8: Auto Optimization
start_service "auto-optimization" \
    "OPTIMIZATION_INTERVAL_HOURS=4 OPTIMIZATION_LOOKBACK_DAYS=7 python workers/auto_optimization_orchestrator.py" &
PIDS+=($!)

# Worker 9: Insurance Monitor
start_service "insurance" \
    "ENABLE_INSURANCE_MONITOR=1 INSURANCE_CHECK_INTERVAL_SEC=60 python workers/insurance_monitor.py" &
PIDS+=($!)

# Worker 10: Quantum TOP 50
start_service "quantum-top50" \
    "python workers/quantum_top50_worker.py" &
PIDS+=($!)

echo ""
echo "✅ All services started!"
echo "📊 Logs location: $LOGS_DIR"
echo "🔄 Auto-restart enabled for all processes"
echo ""
echo "Running processes:"
ps aux | grep -E "(gunicorn|python workers)" | grep -v grep

echo ""
echo "🎯 System is now running 24/7 autonomously"
echo "=================================================="

# Keep script alive
wait
