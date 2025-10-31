#!/usr/bin/env bash
# תפריט פשוט מאוד - ללא עיצוב
set -Eeuo pipefail
cd "${REPL_HOME:-/home/runner/workspace}" || exit 1

clear
echo ""
echo "AlgoGPT Menu"
echo "============"
echo ""
echo " 1. Check Status"
echo " 2. Show Logs"
echo " 3. Restart Scanner"
echo " 4. Full Check"
echo " 5. Exit"
echo ""
read -p "Choose (1-5): " CHOICE
echo ""

case "$CHOICE" in
  1)
    echo "Server:"
    curl -s http://localhost:5000/health | python3 -m json.tool || echo "OFFLINE"
    echo ""
    echo "Processes:"
    ps aux | grep -E "(gunicorn|gpt_auto_suggest)" | grep -v grep | wc -l
    ;;
  2)
    echo "Scanner Logs (last 20 lines):"
    tail -20 /tmp/logs/Auto_Scanner_*.log 2>/dev/null | grep -E "accepted=|Market Mood|Success%|RR" || echo "No logs"
    ;;
  3)
    echo "Restarting Scanner..."
    pkill -f "gpt_auto_suggest.py" 2>/dev/null || true
    echo "Done - will restart automatically"
    ;;
  4)
    echo "Full System Check:"
    echo ""
    echo "1. Processes:"
    ps aux | grep -E "(gunicorn|gpt_auto_suggest)" | grep -v grep | wc -l | xargs echo "  Running:"
    echo ""
    echo "2. Server:"
    curl -s http://localhost:5000/health | python3 -m json.tool || echo "  OFFLINE"
    echo ""
    echo "3. Binance:"
    curl -s https://fapi.binance.com/fapi/v1/time >/dev/null && echo "  OK" || echo "  FAIL"
    echo ""
    echo "4. Last Scanner Result:"
    tail -5 /tmp/logs/Auto_Scanner_*.log 2>/dev/null | grep "accepted=" | tail -1 || echo "  No data"
    echo ""
    echo "5. Filter Settings:"
    tail -10 /tmp/logs/Auto_Scanner_*.log 2>/dev/null | grep -E "Success%|RR Top10|Market Mood" | tail -4 || echo "  No data"
    ;;
  5)
    echo "Exiting"
    exit 0
    ;;
  *)
    echo "Invalid (1-5)"
    ;;
esac

echo ""
