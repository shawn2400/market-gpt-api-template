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

check_env() {
  for key in BINANCE_API_KEY BINANCE_API_SECRET OPENAI_API_KEY TELEGRAM_BOT_TOKEN; do
    [[ -z "${!key:-}" ]] && echo "❌ $key חסר" || echo "✅ $key קיים"
  done
}

auto_heal() {
  echo "🔧 מפעיל Auto-Heal..."
  python3 -c "import httpx; r=httpx.get('https://fapi.binance.com/fapi/v1/time',timeout=4); print('✅ Binance' if r.status_code==200 else '❌ Binance')"
  pgrep -f "gpt_auto_suggest.py" >/dev/null && echo "✅ Scanner" || echo "⚠️ Scanner יופעל מחדש"
  curl -s http://localhost:5000/health >/dev/null && echo "✅ API" || echo "❌ API"
  send_telegram "✅ Auto-Heal Done"
}

clear
echo ""
echo "================================================================"
echo ""
echo "               AlgoGPT - תפריט ראשי                             "
echo ""
echo "================================================================"
echo ""
echo ""
echo "  ניטור ובדיקות:"
echo "  ---------------"
echo ""
echo "    1.  בדיקת מצב השרת"
echo ""
echo "    2.  דוח בריאות + שליחה לטלגרם"
echo ""
echo "    3.  רשימת Workflows פעילים"
echo ""
echo "    4.  בדיקת Binance API"
echo ""
echo "    5.  בדיקת Telegram Bot"
echo ""
echo "    6.  בדיקת מסחר (Dry Run)"
echo ""
echo ""
echo "  תפעול:"
echo "  -------"
echo ""
echo "    7.  הוראות ריסטרט"
echo ""
echo "    8.  ריסטרט Auto Scanner"
echo ""
echo "    9.  ריסטרט כל הרכיבים"
echo ""
echo "   10.  Auto-Heal (תיקון אוטומטי)"
echo ""
echo "   11.  שליחת טסט לטלגרם"
echo ""
echo ""
echo "  הגדרות:"
echo "  --------"
echo ""
echo "   12.  בדיקת Secrets"
echo ""
echo "   13.  הצגת קונפיגורציה"
echo ""
echo "   14.  אימות API Keys"
echo ""
echo ""
echo "  Logs:"
echo "  -----"
echo ""
echo "   15.  הצגת לוגים"
echo ""
echo "   16.  מצב Debug"
echo ""
echo ""
echo "  מערכת:"
echo "  -------"
echo ""
echo "   17.  Dynamic Filters"
echo ""
echo "   18.  בדיקה מקיפה"
echo ""
echo ""
echo "   19.  יציאה"
echo ""
echo ""
echo "================================================================"
echo ""
read -p "  בחר אופציה (1-19): " CHOICE
echo ""
echo "================================================================"
echo ""

case "$CHOICE" in
  1)
    echo "  בודק מצב השרת..."
    echo ""
    curl -s http://localhost:5000/health | python3 -m json.tool
    echo ""
    curl -s http://localhost:5000/ | python3 -m json.tool
    ;;
  2)
    echo "  מפיק דוח בריאות..."
    echo ""
    {
      echo "דוח בריאות - $(date '+%H:%M:%S')"
      echo "================================"
      curl -s http://localhost:5000/health
      echo ""
      ps aux | grep -E "(gunicorn|gpt_auto_suggest)" | grep -v grep
      echo ""
      echo "CPU: $(top -bn1 | grep "Cpu(s)" | awk '{print $2}')%"
      echo "Memory: $(free -m 2>/dev/null | awk '/Mem:/ {printf "%.1f%%", $3/$2*100}' || echo 'N/A')"
      curl -s https://fapi.binance.com/fapi/v1/time >/dev/null && echo "Binance: ✅" || echo "Binance: ❌"
    } | tee /tmp/health.txt
    send_telegram "דוח בריאות - $(date '+%H:%M')"
    echo ""
    echo "  נשמר ב: /tmp/health.txt"
    ;;
  3)
    echo "  Workflows פעילים:"
    echo ""
    ps aux | grep -E "(gunicorn|gpt_auto_suggest|position_monitor|daily_digest)" | grep -v grep
    echo ""
    echo "  סה״כ: $(ps aux | grep -E "(gunicorn|gpt_auto_suggest)" | grep -v grep | wc -l) processes"
    ;;
  4)
    echo "  בודק Binance API..."
    echo ""
    python3 -c "import httpx,datetime; r=httpx.get('https://fapi.binance.com/fapi/v1/time',timeout=5); print(f'  Status: {r.status_code}'); print(f'  Time: {datetime.datetime.fromtimestamp(r.json()[\"serverTime\"]/1000)}')"
    ;;
  5)
    echo "  בודק Telegram Bot..."
    echo ""
    [[ -n "${TELEGRAM_BOT_TOKEN:-}" ]] && curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getMe" | python3 -m json.tool || echo "  ❌ Token חסר"
    ;;
  6)
    echo "  בודק API Keys עם Dry Run..."
    echo ""
    python3 -c "import os,hmac,hashlib,time,httpx; k,s=os.getenv('BINANCE_API_KEY'),os.getenv('BINANCE_API_SECRET'); ts=int(time.time()*1000); qs=f'symbol=BTCUSDT&side=BUY&type=LIMIT&quantity=0.001&price=20000&timeInForce=GTC&timestamp={ts}'; sig=hmac.new(s.encode(),qs.encode(),hashlib.sha256).hexdigest(); r=httpx.post(f'https://fapi.binance.com/fapi/v1/order/test?{qs}&signature={sig}',headers={'X-MBX-APIKEY':k},timeout=10); print('  ✅ Keys תקינים!' if r.status_code==200 else f'  ❌ Error {r.status_code}')"
    ;;
  7)
    echo "  הוראות ריסטרט:"
    echo ""
    echo "  ב-Replit:"
    echo "  1. לחץ על Workflows בצד ימין"
    echo "  2. לחץ Restart ליד כל workflow"
    echo "  3. או השתמש בכלי Replit Agent"
    ;;
  8)
    echo "  מריסטרט Auto Scanner..."
    echo ""
    pkill -f "gpt_auto_suggest.py" 2>/dev/null
    echo "  ✅ יופעל מחדש אוטומטית"
    ;;
  9)
    echo "  ריסטרט כל הרכיבים:"
    echo ""
    echo "  לחץ Restart בכל workflow ב-Workflows pane"
    ;;
  10)
    auto_heal
    ;;
  11)
    echo "  שולח טסט לטלגרם..."
    echo ""
    send_telegram "טסט - $(date '+%H:%M:%S') ✅"
    echo "  ✅ נשלח!"
    ;;
  12)
    echo "  בודק Secrets:"
    echo ""
    check_env
    ;;
  13)
    echo "  קונפיגורציה:"
    echo ""
    echo "  Port: 5000"
    echo "  Workflows: AlgoGPT Server, Auto Scanner, Position Monitor, Daily Digest"
    echo "  Features: Dynamic Filters, Telegram Approval, Live Management"
    ;;
  14)
    echo "  מאמת API Keys:"
    echo ""
    check_env
    ;;
  15)
    echo "  לוגים אחרונים:"
    echo ""
    echo "  === Server (10 אחרונות) ==="
    tail -10 /tmp/logs/AlgoGPT_Server_*.log 2>/dev/null || echo "  אין לוגים"
    echo ""
    echo "  === Scanner (10 אחרונות) ==="
    tail -10 /tmp/logs/Auto_Scanner_*.log 2>/dev/null || echo "  אין לוגים"
    ;;
  16)
    echo "  מצב Debug:"
    echo ""
    check_env
    echo ""
    ps aux | grep -E "(python|gunicorn)" | grep -v grep | head -5
    echo ""
    curl -s http://localhost:5000/health
    ;;
  17)
    echo "  Dynamic Filters:"
    echo ""
    [[ -f "utils/dynamic_filters.py" ]] && echo "  ✅ קיים ($(wc -l < utils/dynamic_filters.py) שורות)" || echo "  ❌ לא נמצא"
    echo ""
    tail -3 /tmp/logs/Auto_Scanner_*.log 2>/dev/null | grep -i "mood\|regime" || echo "  אין לוגים"
    ;;
  18)
    echo "  בדיקה מקיפה:"
    echo ""
    echo "  Processes: $(ps aux | grep -E "(gunicorn|gpt_auto_suggest)" | grep -v grep | wc -l) רצים"
    echo "  Server: $(curl -s http://localhost:5000/health)"
    echo "  CPU: $(top -bn1 | grep "Cpu(s)" | awk '{print $2}')%"
    echo "  Memory: $(free -m 2>/dev/null | awk '/Mem:/ {printf "%.1f%%", $3/$2*100}' || echo 'N/A')"
    curl -s https://fapi.binance.com/fapi/v1/time >/dev/null && echo "  Binance: ✅" || echo "  Binance: ❌"
    ;;
  19)
    echo "  יוצא..."
    exit 0
    ;;
  *)
    echo "  ❌ בחירה לא תקפה (בחר 1-19)"
    ;;
esac

echo ""
echo "================================================================"
echo ""
echo "  AlgoGPT פעיל | Dynamic Filters | 530 Symbols | 60s Cycles"
echo ""
echo "================================================================"
echo ""
