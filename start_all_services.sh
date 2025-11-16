#!/bin/bash
# AlgoGPT - Simple production startup (Replit deployment compatible)
# Runs FastAPI + 10 Workers in background with logging

set -e

echo "🚀 AlgoGPT 24/7 Production Startup"
export PYTHONUNBUFFERED=1
export PYTHONPATH=/home/runner/$REPL_SLUG

# Create logs directory
mkdir -p /tmp/algogpt_logs

# Start FastAPI (Gunicorn) - binds to 0.0.0.0:5000
echo "▶️ Starting FastAPI Server..."
gunicorn -c gunicorn_conf.py main:app > /tmp/algogpt_logs/fastapi.log 2>&1 &
sleep 2

# Start all 10 workers
echo "▶️ Starting Workers..."

BASE_URL=http://127.0.0.1:5000 HEALTH_CHECK_INTERVAL=30 AUTO_FIX_ENABLE=1 TELEGRAM_SEND_ENABLE=1 \
    python workers/auto_health_monitor.py > /tmp/algogpt_logs/health.log 2>&1 &

FILLS_WATCH_ENABLE=1 FILLS_WATCH_INTERVAL_SEC=15 \
    python workers/fills_watcher.py > /tmp/algogpt_logs/fills.log 2>&1 &

ENABLE_POSITION_MONITOR=1 ENABLE_AUTO_PROTECT=1 POSITION_REPORT_INTERVAL_SEC=1800 AUTO_PROTECT_INTERVAL_SEC=30 POSITION_ALERT_LEVEL=all \
    python workers/position_monitor.py > /tmp/algogpt_logs/position.log 2>&1 &

SENTINEL_ENABLED=1 SENTINEL_ALERT_LEVEL=critical \
    python workers/sentinel_security.py > /tmp/algogpt_logs/sentinel.log 2>&1 &

python workers/telegram_digest_reporter.py > /tmp/algogpt_logs/digest.log 2>&1 &

CLEANUP_INTERVAL_SEC=21600 LOGS_RETENTION_DAYS=7 AI_REVIEWS_KEEP_COUNT=100 IMPROVEMENTS_RETENTION_DAYS=30 \
    python workers/auto_cleanup.py > /tmp/algogpt_logs/cleanup.log 2>&1 &

POOL_PER_CYCLE=50 SUGGEST_GRID=1 AUTO_RUN=1 MIN_QUALITY_SCORE=6.0 \
    python workers/gpt_auto_suggest.py > /tmp/algogpt_logs/scanner.log 2>&1 &

OPTIMIZATION_INTERVAL_HOURS=4 OPTIMIZATION_LOOKBACK_DAYS=7 \
    python workers/auto_optimization_orchestrator.py > /tmp/algogpt_logs/optimization.log 2>&1 &

ENABLE_INSURANCE_MONITOR=1 INSURANCE_CHECK_INTERVAL_SEC=60 \
    python workers/insurance_monitor.py > /tmp/algogpt_logs/insurance.log 2>&1 &

python workers/quantum_top50_worker.py > /tmp/algogpt_logs/quantum.log 2>&1 &

echo "✅ All 11 services started (1 API + 10 Workers)"
echo "📊 Logs: /tmp/algogpt_logs/*.log"
echo "🎯 System running 24/7 autonomously"

# Monitor processes
while true; do
    sleep 30
    if ! pgrep -f "gunicorn.*main:app" > /dev/null; then
        echo "⚠️ FastAPI crashed, restarting..."
        gunicorn -c gunicorn_conf.py main:app > /tmp/algogpt_logs/fastapi.log 2>&1 &
    fi
done
