#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="${REPL_HOME:-/home/runner/workspace}"
cd "$PROJECT_ROOT" || exit 1

# פונקציות
send_telegram() {
  [[ -n "${TELEGRAM_BOT_TOKEN:-}" && -n "${TELEGRAM_CHAT_ID:-}" ]] && \
    curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
      -d "chat_id=${TELEGRAM_CHAT_ID}" -d "text=$1" -d "parse_mode=HTML" >/dev/null 2>&1
}

clear
echo ""
echo "AlgoGPT - תפריט ראשי"
echo "===================="
echo ""
echo "ניטור:"
echo ""
echo "  1 - בדיקת מצב השרת"
echo "  2 - דוח בריאות + טלגרם"
echo "  3 - רשימת Workflows"
echo "  4 - בדיקת Binance"
echo "  5 - בדיקת Telegram"
echo "  6 - Dry Run Order"
echo ""
echo "תפעול:"
echo ""
echo "  7 - הוראות ריסטרט"
echo "  8 - ריסטרט Scanner"
echo "  9 - Auto-Heal"
echo " 10 - טסט Telegram"
echo ""
echo "הגדרות:"
echo ""
echo " 11 - בדיקת Secrets"
echo " 12 - קונפיגורציה"
echo ""
echo "Logs:"
echo ""
echo " 13 - הצגת לוגים"
echo " 14 - Debug"
echo ""
echo "מערכת:"
echo ""
echo " 15 - Dynamic Filters"
echo " 16 - בדיקה מקיפה"
echo ""
echo " 17 - יציאה"
echo ""
read -p "בחר (1-17): " CHOICE
echo ""

case "$CHOICE" in
  1)
    echo "בודק מצב השרת..."
    curl -s http://localhost:5000/health | python3 -m json.tool
    ;;
  2)
    echo "מפיק דוח..."
    {
      echo "דוח - $(date '+%H:%M')"
      curl -s http://localhost:5000/health
      ps aux | grep -E "(gunicorn|gpt_auto_suggest)" | grep -v grep | wc -l | xargs echo "Processes:"
      curl -s https://fapi.binance.com/fapi/v1/time >/dev/null && echo "Binance: OK" || echo "Binance: FAIL"
    } | tee /tmp/health.txt
    send_telegram "דוח - $(date '+%H:%M')"
    echo "נשמר: /tmp/health.txt"
    ;;
  3)
    echo "Workflows:"
    ps aux | grep -E "(gunicorn|gpt_auto_suggest|position_monitor|daily_digest)" | grep -v grep
    ;;
  4)
    echo "בודק Binance..."
    python3 -c "import httpx; r=httpx.get('https://fapi.binance.com/fapi/v1/time',timeout=5); print(f'Status: {r.status_code}')"
    ;;
  5)
    echo "בודק Telegram..."
    [[ -n "${TELEGRAM_BOT_TOKEN:-}" ]] && curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getMe" | python3 -m json.tool || echo "Token חסר"
    ;;
  6)
    echo "Dry Run..."
    python3 -c "import os,hmac,hashlib,time,httpx; k,s=os.getenv('BINANCE_API_KEY'),os.getenv('BINANCE_API_SECRET'); ts=int(time.time()*1000); qs=f'symbol=BTCUSDT&side=BUY&type=LIMIT&quantity=0.001&price=20000&timeInForce=GTC&timestamp={ts}'; sig=hmac.new(s.encode(),qs.encode(),hashlib.sha256).hexdigest(); r=httpx.post(f'https://fapi.binance.com/fapi/v1/order/test?{qs}&signature={sig}',headers={'X-MBX-APIKEY':k},timeout=10); print('OK' if r.status_code==200 else f'Error {r.status_code}')"
    ;;
  7)
    echo "ריסטרט:"
    echo "1. לחץ Workflows בצד ימין"
    echo "2. לחץ Restart ליד כל workflow"
    ;;
  8)
    echo "מריסטרט Scanner..."
    pkill -f "gpt_auto_suggest.py" 2>/dev/null
    echo "יופעל מחדש אוטומטית"
    ;;
  9)
    echo "Auto-Heal..."
    python3 -c "import httpx; r=httpx.get('https://fapi.binance.com/fapi/v1/time',timeout=4); print('Binance: OK' if r.status_code==200 else 'Binance: FAIL')"
    pgrep -f "gpt_auto_suggest.py" >/dev/null && echo "Scanner: OK" || echo "Scanner: יופעל מחדש"
    curl -s http://localhost:5000/health >/dev/null && echo "API: OK" || echo "API: FAIL"
    send_telegram "Auto-Heal - $(date '+%H:%M')"
    ;;
  10)
    echo "שולח טסט..."
    send_telegram "Test - $(date '+%H:%M')"
    echo "נשלח!"
    ;;
  11)
    echo "Secrets:"
    for key in BINANCE_API_KEY BINANCE_API_SECRET OPENAI_API_KEY TELEGRAM_BOT_TOKEN; do
      [[ -z "${!key:-}" ]] && echo "$key: חסר" || echo "$key: קיים"
    done
    ;;
  12)
    echo "קונפיגורציה:"
    echo "Port: 5000"
    echo "Workflows: 4 (Server, Scanner, Monitor, Digest)"
    echo "Features: Dynamic Filters, Telegram, Live Management"
    ;;
  13)
    echo "לוגים:"
    echo "=== Server ==="
    tail -5 /tmp/logs/AlgoGPT_Server_*.log 2>/dev/null || echo "אין"
    echo ""
    echo "=== Scanner ==="
    tail -5 /tmp/logs/Auto_Scanner_*.log 2>/dev/null || echo "אין"
    ;;
  14)
    echo "Debug:"
    for key in BINANCE_API_KEY OPENAI_API_KEY TELEGRAM_BOT_TOKEN; do
      [[ -z "${!key:-}" ]] && echo "$key: חסר" || echo "$key: קיים"
    done
    echo ""
    ps aux | grep -E "(gunicorn|gpt_auto_suggest)" | grep -v grep | wc -l | xargs echo "Processes:"
    echo ""
    curl -s http://localhost:5000/health
    ;;
  15)
    echo "Dynamic Filters:"
    [[ -f "utils/dynamic_filters.py" ]] && echo "קיים ($(wc -l < utils/dynamic_filters.py) שורות)" || echo "לא נמצא"
    tail -2 /tmp/logs/Auto_Scanner_*.log 2>/dev/null | grep -i "mood\|regime" || echo "אין לוגים"
    ;;
  16)
    echo "בדיקה מקיפה:"
    echo "Processes: $(ps aux | grep -E "(gunicorn|gpt_auto_suggest)" | grep -v grep | wc -l)"
    echo "Server: $(curl -s http://localhost:5000/health)"
    curl -s https://fapi.binance.com/fapi/v1/time >/dev/null && echo "Binance: OK" || echo "Binance: FAIL"
    ;;
  17)
    echo "יוצא..."
    exit 0
    ;;
  *)
    echo "בחירה לא תקפה (1-17)"
    ;;
esac

echo ""
echo "AlgoGPT פעיל"
echo ""
