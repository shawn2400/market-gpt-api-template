#!/bin/bash
# AlgoGPT - Reserved VM Startup Script
# Runs all services on single VM

set -e

echo "🚀 Starting AlgoGPT Trading System..."
echo "📊 Environment: Production (Reserved VM)"
echo "💾 RAM: 2GB | Region: Frankfurt"

# Start Gunicorn API server
echo "🌐 Starting API Server..."
gunicorn -c gunicorn_conf.py main:app &

# Wait for API to be ready
sleep 5

# 🚨 EMERGENCY KILL-SWITCH CHECK
EMERGENCY_KILL_SWITCH="${EMERGENCY_KILL_SWITCH:-0}"
BAN_RECOVERY_MODE="${BAN_RECOVERY_MODE:-0}"

if [ "$EMERGENCY_KILL_SWITCH" = "1" ] || [ "$BAN_RECOVERY_MODE" = "1" ]; then
    echo ""
    echo "🚨 EMERGENCY KILL-SWITCH ACTIVE 🚨"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "⚠️  All workers DISABLED (BAN recovery mode)"
    echo "🔌 WebSocket UserStream: ACTIVE (via API server)"
    echo "🛡️  API Server: RUNNING (health checks only)"
    echo "⏰ Zero REST API calls to Binance"
    echo ""
    echo "💡 To resume workers:"
    echo "   1. Wait 3+ hours for IP ban to clear"
    echo "   2. Set EMERGENCY_KILL_SWITCH=0 in render.yaml"
    echo "   3. Re-deploy via GitHub push"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "📊 Total: 1 API Server ONLY (0 Workers)"
    echo "⏰ $(date)"
    echo ""
    
    # Keep container alive with only API server
    tail -f /dev/null
    exit 0
fi

# Start all workers in background
echo "👷 Starting Background Workers..."

python workers/auto_health_monitor.py &
echo "✅ Auto Health Monitor started"

python workers/auto_optimization_orchestrator.py &
echo "✅ Auto Optimization started"

python workers/gpt_auto_suggest.py &
echo "✅ Auto Scanner started"

python workers/fills_watcher.py &
echo "✅ Fills Watcher started"

python workers/insurance_monitor.py &
echo "✅ Insurance Monitor started"

python workers/position_monitor.py &
echo "✅ Position Monitor started"

python workers/quantum_top50_worker.py &
echo "✅ Quantum TOP 50 started"

python workers/sentinel_security.py &
echo "✅ Sentinel Security started"

python workers/telegram_digest_reporter.py &
echo "✅ Telegram Digest started"

echo ""
echo "🎉 All services started successfully!"
echo "📊 Total: 1 API + 9 Workers"
echo "⏰ $(date)"

# Keep container alive
tail -f /dev/null
