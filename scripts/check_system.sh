#!/usr/bin/env bash
# AlgoGPT System Health Check - Replit Edition

echo "🔍 AlgoGPT System Health Check"
echo "================================"
echo ""

# 1. Server Health
echo "1️⃣ Server Status:"
curl -s http://localhost:5000/health && echo " ✅" || echo " ❌"

# 2. Workflows
echo ""
echo "2️⃣ Workflows:"
ps aux | grep -E "(gunicorn|gpt_auto_suggest|position_monitor|daily_digest)" | grep -v grep | wc -l | xargs echo "   Running processes:"

# 3. Dynamic Filters
echo ""
echo "3️⃣ Dynamic Filters:"
tail -1 /tmp/logs/Auto_Scanner_*.log 2>/dev/null | grep -o "Market Mood.*" || echo "   (check logs)"

# 4. Binance Connection
echo ""
echo "4️⃣ Binance API:"
curl -s https://fapi.binance.com/fapi/v1/time >/dev/null && echo "   ✅ Connected" || echo "   ❌ Failed"

# 5. Environment Variables
echo ""
echo "5️⃣ Environment:"
[[ -n "$BINANCE_API_KEY" ]] && echo "   ✅ BINANCE_API_KEY" || echo "   ❌ BINANCE_API_KEY"
[[ -n "$OPENAI_API_KEY" ]] && echo "   ✅ OPENAI_API_KEY" || echo "   ❌ OPENAI_API_KEY"
[[ -n "$TELEGRAM_BOT_TOKEN" ]] && echo "   ✅ TELEGRAM_BOT_TOKEN" || echo "   ❌ TELEGRAM_BOT_TOKEN"
[[ -n "$TELEGRAM_CHAT_ID" ]] && echo "   ✅ TELEGRAM_CHAT_ID: $TELEGRAM_CHAT_ID" || echo "   ❌ TELEGRAM_CHAT_ID"

echo ""
echo "================================"
echo "✅ System Check Complete!"
