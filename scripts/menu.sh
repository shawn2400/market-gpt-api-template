#!/usr/bin/env bash
set -Eeuo pipefail

# Get project root (Replit workspace)
PROJECT_ROOT="${REPL_HOME:-/home/runner/workspace}"
cd "$PROJECT_ROOT" || exit 1

# === AlgoGPT Replit Configuration ===
SERVICE_NAME="AlgoGPT Server"
REPLIT_MODE=1

echo ""
echo "============================"
echo "   ⚙️  AlgoGPT Maintenance Menu"
echo "============================"
echo ""
echo "בחר פעולה:"
echo "1) 📦 בדיקת מצב (status)"
echo "2) 🔁 ריסטרט שירות (רק אם צריך)"
echo "3) 🧠 ריסטארט סוכן AI בלבד"
echo "4) 🧩 רענון קונפיג / Env"
echo "5) 🚀 הפעלת Auto Executor"
echo "6) 🔍 בדיקת חיבור ל-Binance"
echo "7) 🧱 בדיקת תקינות מערכת"
echo "8) ❌ יציאה"
echo ""

read -rp "בחר מספר פעולה: " CHOICE
echo ""

case "$CHOICE" in
  1)
    echo "📦 בדיקת מצב השירות..."
    echo ""
    curl -fsSL "http://localhost:5000/health" && echo "✅ AlgoGPT Server פעיל!" || echo "❌ שירות לא זמין"
    curl -fsSL "http://localhost:5000/" | python3 -m json.tool 2>/dev/null || true
    ;;
  2)
    echo "🔁 מבצע ריסטרט שירותים..."
    echo "⚠️ ב-Replit - השתמש ב-Workflows UI או הרץ:"
    echo "   → לחץ על 'Restart' ב-Workflows pane"
    echo "   → או השתמש בכלי Replit Agent"
    ;;
  3)
    echo "🧠 הפעלה מחדש של Auto Scanner..."
    pkill -f "gpt_auto_suggest.py" || true
    echo "✅ Auto Scanner יופעל מחדש אוטומטית על ידי Replit"
    ;;
  4)
    echo "🧩 בדיקת משתני סביבה..."
    echo ""
    [[ -n "${BINANCE_API_KEY:-}" ]] && echo "✅ BINANCE_API_KEY: ${BINANCE_API_KEY:0:10}..." || echo "❌ BINANCE_API_KEY חסר"
    [[ -n "${OPENAI_API_KEY:-}" ]] && echo "✅ OPENAI_API_KEY: ${OPENAI_API_KEY:0:10}..." || echo "❌ OPENAI_API_KEY חסר"
    [[ -n "${TELEGRAM_BOT_TOKEN:-}" ]] && echo "✅ TELEGRAM_BOT_TOKEN: ${TELEGRAM_BOT_TOKEN:0:15}..." || echo "❌ TELEGRAM_BOT_TOKEN חסר"
    [[ -n "${TELEGRAM_CHAT_ID:-}" ]] && echo "✅ TELEGRAM_CHAT_ID: $TELEGRAM_CHAT_ID" || echo "❌ TELEGRAM_CHAT_ID חסר"
    echo ""
    ;;
  5)
    echo "🚀 בדיקת Auto Scanner..."
    echo ""
    if ps aux | grep "gpt_auto_suggest" | grep -v grep >/dev/null; then
      echo "✅ Auto Scanner רץ!"
      ps aux | grep "gpt_auto_suggest" | grep -v grep
    else
      echo "⚠️ Auto Scanner לא רץ - בדוק Workflows"
    fi
    echo ""
    echo "📝 לוגים אחרונים:"
    tail -20 /tmp/logs/Auto_Scanner_*.log 2>/dev/null || echo "אין לוגים זמינים"
    ;;
  6)
    echo "🔍 בדיקת חיבור ל-Binance..."
    python3 - <<'EOF'
import httpx
try:
    r = httpx.get("https://fapi.binance.com/fapi/v1/time", timeout=5)
    print(f"✅ Binance API נגיש: {r.status_code}")
    print(f"   Server Time: {r.json()['serverTime']}")
except Exception as e:
    print(f"❌ שגיאה: {e}")
EOF
    ;;
  7)
    echo "🧱 בדיקת מערכת מלאה..."
    echo ""
    echo "=== 🔄 Workflows ==="
    ps aux | grep -E "(gunicorn|gpt_auto_suggest|position_monitor|daily_digest)" | grep -v grep | head -10 || echo "⚠️ לא נמצאו processes"
    echo ""
    echo "=== 📁 Logs ==="
    ls -lth /tmp/logs/*.log 2>/dev/null | head -5 || echo "אין לוגים"
    echo ""
    echo "=== ❤️ Health Check ==="
    curl -s http://localhost:5000/health
    echo ""
    echo ""
    echo "=== 📊 System Info ==="
    echo "CPU: $(top -bn1 | grep "Cpu(s)" | awk '{print $2}' | cut -d'%' -f1)% used"
    echo "Memory: $(free -m | awk '/Mem:/ {printf "%.1f%%", $3/$2*100}')"
    ;;
  8)
    echo "❌ יציאה."
    exit 0
    ;;
  *)
    echo "❌ בחירה לא תקפה."
    ;;
esac

echo ""
echo "💡 AlgoGPT Running on Replit - מערכת דינמית אוטומטית פעילה!"
echo "   🟢 Dynamic Filters: Auto-adjusting to market conditions"
echo "   📊 Auto Scanner: Scanning 530 symbols every 60 seconds"
echo "   💬 Telegram: Ready for trade approvals"
echo ""
