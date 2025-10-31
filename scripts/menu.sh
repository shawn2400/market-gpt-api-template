#!/usr/bin/env bash
set -Eeuo pipefail
cd "${REPL_HOME:-/home/runner/workspace}" || exit 1

clear
echo ""
echo "=========================================="
echo "          AlgoGPT Menu"
echo "=========================================="
echo ""
echo " 1. Check Server"
echo " 2. Health Report"
echo " 3. Show Workflows"
echo " 4. Check Binance"
echo " 5. Check Telegram"
echo " 6. Test Order"
echo ""
echo " 7. Restart Instructions"
echo " 8. Restart Scanner"
echo " 9. Auto-Heal"
echo "10. Send Test Message"
echo ""
echo "11. Check API Keys"
echo "12. Show Config"
echo ""
echo "13. Show Logs"
echo "14. Debug Mode"
echo ""
echo "15. Dynamic Filters Status"
echo "16. Full System Check"
echo ""
echo "17. Lower Filter Thresholds (GET TRADES!)"
echo ""
echo "18. Exit"
echo ""
echo "=========================================="
read -p "Choose (1-18): " CHOICE
echo ""

case "$CHOICE" in
  1)
    echo "Checking server..."
    curl -s http://localhost:5000/health | python3 -m json.tool
    ;;
  2)
    echo "Generating report..."
    {
      echo "Health Report - $(date '+%H:%M')"
      curl -s http://localhost:5000/health
      ps aux | grep -E "(gunicorn|gpt_auto_suggest)" | grep -v grep | wc -l | xargs echo "Processes:"
      curl -s https://fapi.binance.com/fapi/v1/time >/dev/null && echo "Binance: OK" || echo "Binance: FAIL"
    } | tee /tmp/health.txt
    [[ -n "${TELEGRAM_BOT_TOKEN:-}" && -n "${TELEGRAM_CHAT_ID:-}" ]] && \
      curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        -d "chat_id=${TELEGRAM_CHAT_ID}" -d "text=Health Report - $(date '+%H:%M')" >/dev/null 2>&1
    ;;
  3)
    echo "Workflows:"
    ps aux | grep -E "(gunicorn|gpt_auto_suggest|position_monitor|daily_digest)" | grep -v grep
    ;;
  4)
    echo "Checking Binance..."
    python3 -c "import httpx; r=httpx.get('https://fapi.binance.com/fapi/v1/time',timeout=5); print(f'Status: {r.status_code}')"
    ;;
  5)
    echo "Checking Telegram..."
    [[ -n "${TELEGRAM_BOT_TOKEN:-}" ]] && curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getMe" | python3 -m json.tool || echo "Token missing"
    ;;
  6)
    echo "Testing order..."
    python3 -c "import os,hmac,hashlib,time,httpx; k,s=os.getenv('BINANCE_API_KEY'),os.getenv('BINANCE_API_SECRET'); ts=int(time.time()*1000); qs=f'symbol=BTCUSDT&side=BUY&type=LIMIT&quantity=0.001&price=20000&timeInForce=GTC&timestamp={ts}'; sig=hmac.new(s.encode(),qs.encode(),hashlib.sha256).hexdigest(); r=httpx.post(f'https://fapi.binance.com/fapi/v1/order/test?{qs}&signature={sig}',headers={'X-MBX-APIKEY':k},timeout=10); print('OK - Keys are valid!' if r.status_code==200 else f'Error {r.status_code}')"
    ;;
  7)
    echo "Restart: Click Workflows -> Restart"
    ;;
  8)
    echo "Restarting Scanner..."
    pkill -f "gpt_auto_suggest.py" 2>/dev/null
    echo "Will restart automatically"
    ;;
  9)
    echo "Auto-Heal..."
    python3 -c "import httpx; r=httpx.get('https://fapi.binance.com/fapi/v1/time',timeout=4); print('Binance: OK' if r.status_code==200 else 'Binance: FAIL')"
    pgrep -f "gpt_auto_suggest.py" >/dev/null && echo "Scanner: OK" || echo "Scanner: Will restart"
    curl -s http://localhost:5000/health >/dev/null && echo "API: OK" || echo "API: FAIL"
    ;;
  10)
    echo "Sending test..."
    [[ -n "${TELEGRAM_BOT_TOKEN:-}" && -n "${TELEGRAM_CHAT_ID:-}" ]] && \
      curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        -d "chat_id=${TELEGRAM_CHAT_ID}" -d "text=Test - $(date '+%H:%M')" >/dev/null 2>&1
    echo "Sent!"
    ;;
  11)
    echo "Checking Keys:"
    for key in BINANCE_API_KEY BINANCE_API_SECRET OPENAI_API_KEY TELEGRAM_BOT_TOKEN; do
      [[ -z "${!key:-}" ]] && echo "$key: MISSING" || echo "$key: OK"
    done
    ;;
  12)
    echo "Config:"
    echo "Port: 5000"
    echo "Workflows: 4 (Server, Scanner, Monitor, Digest)"
    echo "Features: Dynamic Filters, Telegram, Live Management"
    ;;
  13)
    echo "Logs:"
    echo "=== Scanner (last 10) ==="
    tail -10 /tmp/logs/Auto_Scanner_*.log 2>/dev/null | grep -E "accepted=|Market Mood" || echo "No logs"
    ;;
  14)
    echo "Debug:"
    for key in BINANCE_API_KEY OPENAI_API_KEY TELEGRAM_BOT_TOKEN; do
      [[ -z "${!key:-}" ]] && echo "$key: MISSING" || echo "$key: OK"
    done
    echo ""
    ps aux | grep -E "(gunicorn|gpt_auto_suggest)" | grep -v grep | wc -l | xargs echo "Processes:"
    curl -s http://localhost:5000/health
    ;;
  15)
    echo "Dynamic Filters:"
    echo "Status:"
    tail -5 /tmp/logs/Auto_Scanner_*.log 2>/dev/null | grep -i "market mood\|accepted=" || echo "No logs"
    ;;
  16)
    echo "Full Check:"
    echo "Processes: $(ps aux | grep -E "(gunicorn|gpt_auto_suggest)" | grep -v grep | wc -l)"
    echo "Server: $(curl -s http://localhost:5000/health)"
    curl -s https://fapi.binance.com/fapi/v1/time >/dev/null && echo "Binance: OK" || echo "Binance: FAIL"
    echo ""
    echo "Last Scanner Results:"
    tail -3 /tmp/logs/Auto_Scanner_*.log 2>/dev/null | grep "accepted="
    ;;
  17)
    echo "LOWERING FILTER THRESHOLDS TO GET TRADES..."
    echo ""
    echo "Creating aggressive config..."
    cat > /tmp/aggressive_filters.env << 'ENVEOF'
# Aggressive mode - More trades!
DYNAMIC_FILTER_MODE=aggressive
MIN_SUCCESS_PCT=55
MIN_RR_TOP10=1.2
MIN_RR_ALTS=1.4
MIN_QUALITY=5.0
ENVEOF
    echo "Config created at: /tmp/aggressive_filters.env"
    echo ""
    echo "Now restart Scanner:"
    echo "  bash menu.sh"
    echo "  Choose option 8"
    ;;
  18)
    echo "Exiting"
    exit 0
    ;;
  *)
    echo "Invalid choice (1-18)"
    ;;
esac

echo ""
