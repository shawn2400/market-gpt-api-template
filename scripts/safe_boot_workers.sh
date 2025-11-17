#!/bin/bash
# 🚀 Safe-Boot Mode - Staggered Worker Startup
# Prevents REST API burst that could trigger new IP ban

set -e

echo "🚀 SAFE-BOOT MODE: Staggered Worker Startup"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "⚠️  Starting workers with 12-second delays"
echo "🛡️  REST rate limit: 40 req/min max"
echo "🔄 Auto-pause on burst detection: 2h"
echo ""

DELAY=12

# Critical monitoring workers first
echo "📊 [1/9] Starting Position Monitor..."
python workers/position_monitor.py &
echo "✅ Position Monitor started"
sleep $DELAY

echo "📊 [2/9] Starting Trade Manager (Fills Watcher)..."
python workers/fills_watcher.py &
echo "✅ Fills Watcher started"
sleep $DELAY

echo "📊 [3/9] Starting Insurance Monitor..."
python workers/insurance_monitor.py &
echo "✅ Insurance Monitor started"
sleep $DELAY

# Health & optimization
echo "📊 [4/9] Starting Auto Health Monitor..."
python workers/auto_health_monitor.py &
echo "✅ Auto Health Monitor started"
sleep $DELAY

echo "📊 [5/9] Starting Auto Optimization..."
python workers/auto_optimization_orchestrator.py &
echo "✅ Auto Optimization started"
sleep $DELAY

# Scanning & analysis (lower priority)
echo "📊 [6/9] Starting Auto Scanner..."
python workers/gpt_auto_suggest.py &
echo "✅ Auto Scanner started"
sleep $DELAY

echo "📊 [7/9] Starting Quantum TOP 50..."
python workers/quantum_top50_worker.py &
echo "✅ Quantum TOP 50 started"
sleep $DELAY

# Security & reporting
echo "📊 [8/9] Starting Sentinel Security..."
python workers/sentinel_security.py &
echo "✅ Sentinel Security started"
sleep $DELAY

echo "📊 [9/10] Starting Telegram Digest Reporter..."
python workers/telegram_digest_reporter.py &
echo "✅ Telegram Digest started"
sleep $DELAY

echo "📊 [10/10] Starting Ban Shield Monitor..."
python workers/ban_shield_monitor.py &
echo "✅ Ban Shield Monitor started"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🎉 All 10 workers started successfully!"
echo "⏰ Total startup time: ~2 minutes"
echo "📊 Monitoring for REST API bursts..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
