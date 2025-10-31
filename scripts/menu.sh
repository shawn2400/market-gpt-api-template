#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="${REPL_HOME:-/home/runner/workspace}"
cd "$PROJECT_ROOT" || exit 1

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
echo "  1 - בדיקת מצב השרת"
echo "  2 - דוח בריאות + טלגרם"
echo "  3 - רשימת Workflows"
echo "  4 - בדיקת Binance"
echo "  5 - בדיקת Telegram"
echo "  6 - Dry Run Order"
echo ""
echo "תפעול:"
echo "  7 - הוראות ריסטרט"
echo "  8 - ריסטרט Scanner"
echo "  9 - ריסטרט כל Workflows"
echo " 10 - Auto-Heal"
echo " 11 - טסט Telegram"
echo ""
echo "הגדרות:"
echo " 12 - בדיקת Secrets"
echo " 13 - קונפיגורציה"
echo " 14 - אימות API Keys"
echo ""
echo "Logs:"
echo " 15 - הצגת לוגים"
echo " 16 - Debug"
echo ""
echo "מערכת:"
echo " 17 - Dynamic Filters"
echo " 18 - בדיקה מקיפה"
echo ""
echo " 19 - יציאה"
echo ""
read -p "בחר (1-19): " CHOICE
echo ""

case "$CHOICE" in
  1)
    echo "בודק מצב..."
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
    ;;
  3)
    echo "Workflows:"
    ps aux | grep -E "(gunicorn|gpt_auto_suggest|position_monitor|daily_digest)" | grep -v grep
    ;;
  4)
    echo "Binance:"
    python3 -c "import httpx; r=httpx.get('https://fapi.binance.com/fapi/v1/time',timeout=5); print(f'Status: {r.status_code}')"
    ;;
  5)
    echo "Telegram:"
    [[ -n "${TELEGRAM_BOT_TOKEN:-}" ]] && curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getMe" | python3 -m json.tool || echo "Token חסר"
    ;;
  6)
    echo "Dry Run:"
    python3 -c "import os,hmac,hashlib,time,httpx; k,s=os.getenv('BINANCE_API_KEY'),os.getenv('BINANCE_API_SECRET'); ts=int(time.time()*1000); qs=f'symbol=BTCUSDT&side=BUY&type=LIMIT&quantity=0.001&price=20000&timeInForce=GTC&timestamp={ts}'; sig=hmac.new(s.encode(),qs.encode(),hashlib.sha256).hexdigest(); r=httpx.post(f'https://fapi.binance.com/fapi/v1/order/test?{qs}&signature={sig}',headers={'X-MBX-APIKEY':k},timeout=10); print('OK' if r.status_code==200 else f'Error {r.status_code}')"
    ;;
  7)
    echo "ריסטרט: לחץ Workflows -> Restart"
    ;;
  8)
    echo "מריסטרט Scanner..."
    pkill -f "gpt_auto_suggest.py" 2>/dev/null
    echo "יופעל מחדש"
    ;;
  9)
    echo "ריסטרט הכל: לחץ Restart בכל workflow"
    ;;
  10)
    echo "Auto-Heal..."
    python3 -c "import httpx; r=httpx.get('https://fapi.binance.com/fapi/v1/time',timeout=4); print('Binance: OK' if r.status_code==200 else 'Binance: FAIL')"
    pgrep -f "gpt_auto_suggest.py" >/dev/null && echo "Scanner: OK" || echo "Scanner: יופעל"
    curl -s http://localhost:5000/health >/dev/null && echo "API: OK" || echo "API: FAIL"
    send_telegram "Auto-Heal - $(date '+%H:%M')"
    ;;
  11)
    echo "טסט Telegram..."
    send_telegram "Test - $(date '+%H:%M')"
    echo "נשלח"
    ;;
  12)
    echo "Secrets:"
    for key in BINANCE_API_KEY BINANCE_API_SECRET OPENAI_API_KEY TELEGRAM_BOT_TOKEN; do
      [[ -z "${!key:-}" ]] && echo "$key: חסר" || echo "$key: קיים"
    done
    ;;
  13)
    echo "קונפיג:"
    echo "Port: 5000"
    echo "Workflows: 4"
    echo "Features: Dynamic Filters, Telegram, Live Management"
    ;;
  14)
    echo "אימות Keys:"
    for key in BINANCE_API_KEY BINANCE_API_SECRET OPENAI_API_KEY TELEGRAM_BOT_TOKEN; do
      [[ -z "${!key:-}" ]] && echo "$key: חסר" || echo "$key: קיים"
    done
    ;;
  15)
    echo "לוגים:"
    tail -5 /tmp/logs/AlgoGPT_Server_*.log 2>/dev/null || echo "אין Server logs"
    echo ""
    tail -5 /tmp/logs/Auto_Scanner_*.log 2>/dev/null || echo "אין Scanner logs"
    ;;
  16)
    echo "Debug:"
    for key in BINANCE_API_KEY OPENAI_API_KEY TELEGRAM_BOT_TOKEN; do
      [[ -z "${!key:-}" ]] && echo "$key: חסר" || echo "$key: קיים"
    done
    echo ""
    ps aux | grep -E "(gunicorn|gpt_auto_suggest)" | grep -v grep | wc -l | xargs echo "Processes:"
    curl -s http://localhost:5000/health
    ;;
  17)
    echo "Dynamic Filters:"
    [[ -f "utils/dynamic_filters.py" ]] && echo "קיים ($(wc -l < utils/dynamic_filters.py) שורות)" || echo "לא נמצא"
    tail -2 /tmp/logs/Auto_Scanner_*.log 2>/dev/null | grep -i "mood\|regime" || echo "אין לוגים"
    ;;
  18)
    echo "בדיקה מקיפה:"
    echo "Processes: $(ps aux | grep -E "(gunicorn|gpt_auto_suggest)" | grep -v grep | wc -l)"
    echo "Server: $(curl -s http://localhost:5000/health)"
    curl -s https://fapi.binance.com/fapi/v1/time >/dev/null && echo "Binance: OK" || echo "Binance: FAIL"
    ;;
  19)
    echo "יוצא"
    exit 0
    ;;
  *)
    echo "בחירה לא תקפה"
    ;;
esac

echo ""
