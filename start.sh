#!/bin/bash
# AlgoGPT - Reserved VM Startup Script
# Runs all services on single VM
set -e
echo "🚀 Starting AlgoGPT Trading System..."
echo "📊 Environment: Production (Reserved VM)"
echo "💾 RAM: 2GB | Region: Frankfurt"

# Start Gunicorn API server
echo "🌐 Starting API Server..."
gunicorn -c gunicorn.conf.py main:app &

# Wait for API to be ready
sleep 5

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

