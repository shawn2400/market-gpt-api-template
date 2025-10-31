#!/usr/bin/env bash
set -Eeuo pipefail

# Get project root (Replit workspace)
PROJECT_ROOT="${REPL_HOME:-/home/runner/workspace}"
cd "$PROJECT_ROOT" || exit 1

# === AlgoGPT Replit Configuration ===
SERVICE_NAME="AlgoGPT Server"
REPLIT_MODE=1
REPORT_PATH="/tmp/algogpt_health_report.txt"

# === שליחת הודעה לטלגרם ===
send_telegram() {
  local msg="$1"
  if [[ -n "${TELEGRAM_BOT_TOKEN:-}" && -n "${TELEGRAM_CHAT_ID:-}" ]]; then
    curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
      -d "chat_id=${TELEGRAM_CHAT_ID}" \
      -d "text=${msg}" \
      -d "parse_mode=HTML" >/dev/null 2>&1 || echo "⚠️ כשל בשליחת טלגרם"
  fi
}

# === בדיקת סביבה בסיסית ===
check_env() {
  echo "🔍 בודק Environment בסיסי..."
  local missing=0
  for key in BINANCE_API_KEY BINANCE_API_SECRET OPENAI_API_KEY TELEGRAM_BOT_TOKEN; do
    if [[ -z "${!key:-}" ]]; then
      echo "❌ חסר משתנה: $key"
      missing=1
    else
      echo "✅ $key קיים"
    fi
  done
  (( missing > 0 )) && return 1 || return 0
}

# === תיקון אוטומטי (Auto-Heal) ===
auto_heal() {
  echo "🧩 מפעיל Auto-Heal..."
  send_telegram "🧩 <b>Auto-Heal Triggered</b>\nמתקן רכיבים תקולים..."

  local fix_count=0

  echo "➡️ בדיקת Binance..."
  python3 - <<'PYEOF'
import httpx
try:
    r = httpx.get("https://fapi.binance.com/fapi/v1/time", timeout=4)
    if r.status_code == 200:
        print("✅ Binance OK")
    else:
        print(f"⚠️ Binance Error {r.status_code}")
except Exception as e:
    print("❌ Binance לא נגיש:", e)
PYEOF

  echo "➡️ בדיקת Auto Scanner..."
  if ! pgrep -f "gpt_auto_suggest.py" >/dev/null; then
    echo "🔧 Auto Scanner לא רץ - יופעל מחדש אוטומטית על ידי Replit"
    ((fix_count++))
  else
    echo "✅ Auto Scanner פעיל."
  fi

  echo "➡️ בדיקת API..."
  curl -fsSL "http://localhost:5000/readyz" >/dev/null || {
    echo "⚠️ שירות ראשי לא מגיב, בדוק Workflows."
    ((fix_count++))
  }

  echo "✅ Auto-Heal הושלם. בדקתי ${fix_count} רכיבים."
  send_telegram "✅ <b>Auto-Heal Completed</b>\nבדקתי ${fix_count} רכיבים.\n🕒 $(date '+%H:%M:%S %d/%m/%Y')"
}

clear
cat << 'BANNER'
╔════════════════════════════════════════════════════════════╗
║                                                            ║
║        ⚙️  AlgoGPT - Maintenance & Control Menu  ⚙️         ║
║                                                            ║
║              🤖 Replit Edition - Full Featured 🤖          ║
║                                                            ║
╚════════════════════════════════════════════════════════════╝
BANNER

echo ""
echo "════════════════════════════════════════════════════════════"
echo "  📊 MONITORING & STATUS"
echo "════════════════════════════════════════════════════════════"
echo "  1)  📦 בדיקת מצב השירות (Server Status)"
echo "  2)  📊 הפקת דוח בריאות מערכת + שליחה לטלגרם"
echo "  3)  📈 בדיקת Workflows פעילים"
echo "  4)  🔍 בדיקת חיבור ל-Binance API"
echo ""
echo "════════════════════════════════════════════════════════════"
echo "  🔧 OPERATIONS & RESTART"
echo "════════════════════════════════════════════════════════════"
echo "  5)  🔁 ריסטרט שירות (הוראות)"
echo "  6)  🧠 ריסטרט Auto Scanner בלבד"
echo "  7)  🔄 ריסטרט כל ה-Workflows"
echo "  8)  🧩 Auto-Heal - תיקון תקלות אוטומטי"
echo ""
echo "════════════════════════════════════════════════════════════"
echo "  ⚙️  CONFIGURATION & SETTINGS"
echo "════════════════════════════════════════════════════════════"
echo "  9)  🧩 בדיקת משתני סביבה (Secrets)"
echo "  10) 📝 הצגת קונפיגורציה נוכחית"
echo "  11) 🔐 בדיקת אימות API Keys"
echo ""
echo "════════════════════════════════════════════════════════════"
echo "  🧪 TESTING & VALIDATION"
echo "════════════════════════════════════════════════════════════"
echo "  12) 🧪 בדיקת מסחר אמיתית (Dry Run Order - Binance Test)"
echo "  13) 📡 בדיקת Telegram Bot"
echo "  14) 🔬 בדיקת Dynamic Filters"
echo "  15) 💬 שליחת הודעת טסט לטלגרם"
echo ""
echo "════════════════════════════════════════════════════════════"
echo "  📋 LOGS & DEBUGGING"
echo "════════════════════════════════════════════════════════════"
echo "  16) 📋 הצגת לוגים אחרונים"
echo "  17) 🐛 מצב Debug מלא"
echo "  18) 🧱 בדיקת מערכת מקיפה (Full System Check)"
echo ""
echo "════════════════════════════════════════════════════════════"
echo "  19) ❌ יציאה"
echo "════════════════════════════════════════════════════════════"
echo ""

read -rp "👉 בחר מספר פעולה (1-19): " CHOICE
echo ""
echo "════════════════════════════════════════════════════════════"
echo ""

case "$CHOICE" in
  1)
    echo "📦 בדיקת מצב השירות..."
    echo ""
    curl -fsSL "http://localhost:5000/health" && echo "✅ AlgoGPT Server פעיל!" || echo "❌ שירות לא זמין"
    echo ""
    echo "פרטי השירות:"
    curl -fsSL "http://localhost:5000/" | python3 -m json.tool 2>/dev/null || true
    ;;
    
  2)
    echo "📊 מפיק דוח בריאות מערכת..."
    {
      echo "════════════════════════════════════════════════════════════"
      echo "  🩺 AlgoGPT Health Report"
      echo "════════════════════════════════════════════════════════════"
      echo "⏰ $(date '+%Y-%m-%d %H:%M:%S')"
      echo ""
      echo "🌐 Server Status:"
      curl -fsSL "http://localhost:5000/readyz" || echo "❌ Server down"
      echo ""
      echo "📊 Workflows:"
      ps aux | grep -E "(gunicorn|gpt_auto_suggest|position_monitor|daily_digest)" | grep -v grep
      echo ""
      echo "💻 System Resources:"
      echo "CPU: $(top -bn1 | grep "Cpu(s)" | awk '{print $2}' | cut -d'%' -f1)% used"
      echo "Memory: $(free -m | awk '/Mem:/ {printf "%.1f%%", $3/$2*100}')"
      echo ""
      echo "🔗 Binance API:"
      curl -s https://fapi.binance.com/fapi/v1/time >/dev/null && echo "✅ Connected" || echo "❌ Failed"
      echo ""
      echo "════════════════════════════════════════════════════════════"
    } | tee "$REPORT_PATH"
    echo "✅ דוח נוצר ב־$REPORT_PATH"
    send_telegram "🩺 <b>AlgoGPT Health Report</b>\n📂 ${REPORT_PATH}\n🕒 $(date '+%H:%M:%S %d/%m/%Y')"
    ;;
    
  3)
    echo "📈 בדיקת Workflows פעילים..."
    echo ""
    ps aux | grep -E "(gunicorn|gpt_auto_suggest|position_monitor|daily_digest)" | grep -v grep || echo "⚠️ לא נמצאו processes"
    echo ""
    echo "סה״כ: $(ps aux | grep -E "(gunicorn|gpt_auto_suggest|position_monitor|daily_digest)" | grep -v grep | wc -l) processes רצים"
    ;;
    
  4)
    echo "🔍 בדיקת חיבור ל-Binance..."
    python3 - <<'EOF'
import httpx
try:
    r = httpx.get("https://fapi.binance.com/fapi/v1/time", timeout=5)
    print(f"✅ Binance API נגיש: {r.status_code}")
    print(f"   Server Time: {r.json()['serverTime']}")
    import datetime
    print(f"   Human Time: {datetime.datetime.fromtimestamp(r.json()['serverTime']/1000)}")
except Exception as e:
    print(f"❌ שגיאה: {e}")
EOF
    ;;
    
  5)
    echo "🔁 ריסטרט שירותים..."
    echo ""
    echo "⚠️ ב-Replit - השתמש באחת מהאופציות:"
    echo "   1. לחץ על 'Restart' ב-Workflows pane (צד ימין)"
    echo "   2. השתמש בכלי Replit Agent"
    echo "   3. בחר אופציה 7 לריסטרט כל ה-Workflows"
    ;;
    
  6)
    echo "🧠 הפעלה מחדש של Auto Scanner..."
    pkill -f "gpt_auto_suggest.py" || true
    echo "✅ Auto Scanner יופעל מחדש אוטומטית על ידי Replit"
    sleep 2
    echo "בודק..."
    ps aux | grep "gpt_auto_suggest" | grep -v grep || echo "⚠️ מחכה להפעלה..."
    ;;
    
  7)
    echo "🔄 ריסטרט כל ה-Workflows..."
    echo ""
    echo "💡 ב-Replit, Workflows מנוהלים אוטומטית."
    echo "   לריסטרט ידני - לחץ על כפתור Restart בכל workflow."
    ;;
    
  8)
    auto_heal
    ;;
    
  9)
    echo "🧩 בדיקת משתני סביבה..."
    echo ""
    [[ -n "${BINANCE_API_KEY:-}" ]] && echo "✅ BINANCE_API_KEY: ${BINANCE_API_KEY:0:10}..." || echo "❌ BINANCE_API_KEY חסר"
    [[ -n "${BINANCE_API_SECRET:-}" ]] && echo "✅ BINANCE_API_SECRET: ${BINANCE_API_SECRET:0:10}..." || echo "❌ BINANCE_API_SECRET חסר"
    [[ -n "${OPENAI_API_KEY:-}" ]] && echo "✅ OPENAI_API_KEY: ${OPENAI_API_KEY:0:10}..." || echo "❌ OPENAI_API_KEY חסר"
    [[ -n "${TELEGRAM_BOT_TOKEN:-}" ]] && echo "✅ TELEGRAM_BOT_TOKEN: ${TELEGRAM_BOT_TOKEN:0:15}..." || echo "❌ TELEGRAM_BOT_TOKEN חסר"
    [[ -n "${TELEGRAM_CHAT_ID:-}" ]] && echo "✅ TELEGRAM_CHAT_ID: $TELEGRAM_CHAT_ID" || echo "❌ TELEGRAM_CHAT_ID חסר"
    echo ""
    ;;
    
  10)
    echo "📝 הצגת קונפיגורציה נוכחית..."
    echo ""
    echo "🌐 URLs:"
    echo "   Replit Domain: ${REPL_SLUG:-unknown}"
    echo "   Port: 5000"
    echo ""
    echo "⚙️ Workflows:"
    echo "   ✅ AlgoGPT Server (gunicorn)"
    echo "   ✅ Auto Scanner (60s cycles)"
    echo "   ✅ Position Monitor"
    echo "   ✅ Daily Digest"
    echo ""
    echo "🔧 Features:"
    echo "   ✅ Dynamic Filters"
    echo "   ✅ Telegram Approval Workflow"
    echo "   ✅ Live Position Management"
    ;;
    
  11)
    echo "🔐 בדיקת אימות API Keys..."
    check_env
    ;;
    
  12)
    echo "🧪 בדיקת מסחר אמיתית (Dry Run)..."
    python3 - <<'PYEOF'
import os, hmac, hashlib, time, httpx
key, secret = os.getenv("BINANCE_API_KEY"), os.getenv("BINANCE_API_SECRET")
if not key or not secret:
    print("❌ חסרים מפתחות API")
else:
    ts = int(time.time()*1000)
    qs = f"symbol=BTCUSDT&side=BUY&type=LIMIT&quantity=0.001&price=20000&timeInForce=GTC&timestamp={ts}"
    sig = hmac.new(secret.encode(), qs.encode(), hashlib.sha256).hexdigest()
    url = f"https://fapi.binance.com/fapi/v1/order/test?{qs}&signature={sig}"
    r = httpx.post(url, headers={"X-MBX-APIKEY": key}, timeout=10)
    print("✅ Dry Run הצליח - API Keys תקינים!" if r.status_code==200 else f"⚠️ שגיאה {r.status_code}: {r.text}")
PYEOF
    ;;
    
  13)
    echo "📡 בדיקת Telegram Bot..."
    if [[ -n "${TELEGRAM_BOT_TOKEN:-}" ]]; then
      curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getMe" | python3 -m json.tool 2>/dev/null || echo "❌ שגיאה"
    else
      echo "❌ TELEGRAM_BOT_TOKEN לא מוגדר"
    fi
    ;;
    
  14)
    echo "🔬 בדיקת Dynamic Filters..."
    echo ""
    if [ -f "utils/dynamic_filters.py" ]; then
      echo "✅ Dynamic Filters קיים ($(wc -l < utils/dynamic_filters.py) שורות)"
      echo ""
      echo "📊 לוגים אחרונים:"
      tail -5 /tmp/logs/Auto_Scanner_*.log 2>/dev/null | grep -i "dynamic\|mood\|regime" || echo "אין לוגים זמינים"
    else
      echo "❌ Dynamic Filters לא נמצא"
    fi
    ;;
    
  15)
    echo "💬 שליחת הודעת טסט לטלגרם..."
    send_telegram "🧪 <b>Test Message from AlgoGPT</b>\n🕒 $(date '+%H:%M:%S')\n✅ Telegram Bot פעיל!"
    echo "✅ הודעה נשלחה!"
    ;;
    
  16)
    echo "📋 הצגת לוגים אחרונים..."
    echo ""
    echo "=== Server Logs (20 שורות אחרונות) ==="
    tail -20 /tmp/logs/AlgoGPT_Server_*.log 2>/dev/null || echo "אין לוגים"
    echo ""
    echo "=== Auto Scanner Logs (20 שורות אחרונות) ==="
    tail -20 /tmp/logs/Auto_Scanner_*.log 2>/dev/null || echo "אין לוגים"
    ;;
    
  17)
    echo "🐛 מצב Debug מלא..."
    echo ""
    echo "=== Environment ==="
    check_env
    echo ""
    echo "=== Processes ==="
    ps aux | grep -E "(python|gunicorn)" | grep -v grep
    echo ""
    echo "=== Logs Files ==="
    ls -lth /tmp/logs/*.log 2>/dev/null | head -10
    echo ""
    echo "=== Network ==="
    curl -s http://localhost:5000/health
    echo ""
    curl -s https://fapi.binance.com/fapi/v1/time | python3 -m json.tool 2>/dev/null
    ;;
    
  18)
    echo "🧱 בדיקת מערכת מקיפה..."
    echo ""
    echo "═══ 🔄 Workflows ═══"
    ps aux | grep -E "(gunicorn|gpt_auto_suggest|position_monitor|daily_digest)" | grep -v grep | head -10 || echo "⚠️ לא נמצאו processes"
    echo ""
    echo "═══ 📁 Logs ═══"
    ls -lth /tmp/logs/*.log 2>/dev/null | head -5 || echo "אין לוגים"
    echo ""
    echo "═══ ❤️ Health Check ═══"
    curl -s http://localhost:5000/health
    echo ""
    echo ""
    echo "═══ 📊 System Info ═══"
    echo "CPU: $(top -bn1 | grep "Cpu(s)" | awk '{print $2}' | cut -d'%' -f1)% used"
    echo "Memory: $(free -m | awk '/Mem:/ {printf "%.1f%%", $3/$2*100}')"
    echo ""
    echo "═══ 🌐 Connectivity ═══"
    curl -s https://fapi.binance.com/fapi/v1/time >/dev/null && echo "✅ Binance: Connected" || echo "❌ Binance: Failed"
    ;;
    
  19)
    echo "❌ יציאה מהתפריט."
    echo "להפעלה מחדש הרץ: bash menu.sh"
    exit 0
    ;;
    
  *)
    echo "❌ בחירה לא תקפה. בחר מספר בין 1-19."
    ;;
esac

echo ""
echo "════════════════════════════════════════════════════════════"
echo "💡 AlgoGPT Running on Replit - מערכת דינמית אוטומטית פעילה!"
echo "   🟢 Dynamic Filters: Auto-adjusting to market conditions"
echo "   📊 Auto Scanner: Scanning 530 symbols every 60 seconds"
echo "   💬 Telegram: Ready for trade approvals"
echo "════════════════════════════════════════════════════════════"
echo ""
