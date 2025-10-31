cat > /app/menu.sh <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
cd /app || exit 1

SAFE_MODE=1
SERVICE_NAME="algogpt-prod"
REPORT_PATH="/app/health_report.txt"

# === שליחת הודעה לטלגרם ===
send_telegram() {
  local msg="$1"
  if [[ -n "${TELEGRAM_BOT_TOKEN:-}" && -n "${TELEGRAM_CHAT_ID:-}" ]]; then
    curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
      -d "chat_id=${TELEGRAM_CHAT_ID}" \
      -d "text=${msg}" \
      -d "parse_mode=HTML" >/dev/null || echo "⚠️ כשל בשליחת טלגרם"
  fi
}

# === בדיקת סביבה בסיסית ===
check_env() {
  echo "🔍 בודק Environment בסיסי..."
  local missing=0
  for key in BINANCE_API_KEY BINANCE_API_SECRET API_BEARER_TOKEN; do
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
  send_telegram "🧩 <b>Auto-Heal Triggered</b>\nמתקן רכיבים תקולים (Redis / Binance / Executor)..."

  local fix_count=0

  echo "➡️ בדיקת Redis..."
  if [[ -n "${REDIS_URL:-}" ]]; then
    if ! redis-cli -u "$REDIS_URL" ping >/dev/null 2>&1; then
      echo "🔧 מנסה להפעיל Redis מחדש..."
      systemctl restart redis 2>/dev/null || echo "⚠️ אין הרשאה להפעלת Redis."
      ((fix_count++))
    else
      echo "✅ Redis תקין."
    fi
  fi

  echo "➡️ בדיקת Binance..."
  python - <<'PYEOF'
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

  echo "➡️ בדיקת AutoExecutor..."
  if ! pgrep -f "auto_executor.py" >/dev/null; then
    echo "🔧 מפעיל AutoExecutor מחדש..."
    nohup python utils/auto_executor.py >/tmp/auto_exec.log 2>&1 &
    ((fix_count++))
  else
    echo "✅ AutoExecutor פעיל."
  fi

  echo "➡️ בדיקת API..."
  curl -fsSL "http://localhost:10000/readyz" >/dev/null || {
    echo "⚠️ שירות ראשי לא מגיב, ניסיון רענון."
    supervisorctl restart "${SERVICE_NAME}" || true
    ((fix_count++))
  }

  echo "✅ Auto-Heal הושלם. תוקנו ${fix_count} רכיבים."
  send_telegram "✅ <b>Auto-Heal Completed</b>\nתוקנו ${fix_count} רכיבים.\n🕒 $(date '+%H:%M:%S %d/%m/%Y')"
}

# === תפריט ראשי ===
clear
echo "============================"
echo "   ⚙️  AlgoGPT Maintenance Menu"
echo "============================"
echo ""
echo "בחר פעולה:"
echo "1) 📦 בדיקת מצב (status)"
echo "2) 🔁 ריסטרט שירות (רק אם צריך)"
echo "3) 🧠 ריסטארט סוכן AI בלבד"
echo "4) 🧩 רענון קונפיג / Env"
echo "5) 🚀 הפעלת Auto Executor (כולל בדיקה מקדימה)"
echo "6) 🔍 בדיקת חיבור ל-Binance"
echo "7) 🧱 בדיקת תקינות ריידיר / Docker"
echo "8) ❌ יציאה"
echo "9) 🧪 בדיקת מסחר אמיתית (Dry Run Order)"
echo "10) 📊 הפקת דוח בריאות מערכת (Health Report + Telegram)"
echo "11) 🧩 Auto-Heal – תיקון תקלות מערכת"
echo ""

read -rp "בחר מספר פעולה: " CHOICE
echo ""

case "$CHOICE" in
  1)
    echo "📦 בדיקת מצב השירות..."
    curl -fsSL "http://localhost:10000/readyz" || echo "❌ שירות לא זמין"
    ;;
  2)
    echo "🔁 מבצע ריסטרט יזום..."
    [[ "$SAFE_MODE" == "1" ]] && echo "⚠️ SAFE MODE – רק שירות Render."
    supervisorctl restart "${SERVICE_NAME}" || echo "⚠️ נדרש Restart ידני."
    ;;
  3)
    echo "🧠 ריסטארט מודול AI בלבד..."
    pkill -f "auto_executor.py" || true
    nohup python utils/auto_executor.py >/tmp/auto_exec.log 2>&1 &
    echo "✅ הופעל מחדש."
    ;;
  4)
    echo "🧩 רענון קובץ ENV..."
    export $(grep -v '^#' .env | xargs) || echo "⚠️ לא נמצא קובץ .env"
    ;;
  5)
    echo "🚀 הפעלת Auto Executor..."
    if check_env; then
      nohup python utils/auto_executor.py >/tmp/auto_exec.log 2>&1 &
      echo "✅ Auto Executor הופעל."
    else
      echo "⛔ חסרים משתנים קריטיים."
    fi
    ;;
  6)
    python - <<'PYEOF'
import httpx
try:
    r = httpx.get("https://fapi.binance.com/fapi/v1/time", timeout=5)
    print("✅ Binance נגיש:", r.status_code)
except Exception as e:
    print("❌ שגיאה:", e)
PYEOF
    ;;
  7)
    docker ps -a || echo "⚠️ Docker לא זמין"
    ;;
  8)
    echo "❌ יציאה."; exit 0 ;;
  9)
    python - <<'PYEOF'
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
    print("✅ Dry Run הצליח" if r.status_code==200 else f"⚠️ שגיאה {r.status_code}: {r.text}")
PYEOF
    ;;
  10)
    echo "📊 מפיק דוח בריאות..."
    {
      echo "============================"
      echo "  🩺 AlgoGPT Health Report"
      echo "============================"
      echo "⏰ $(date)"
      echo ""
      curl -fsSL "http://localhost:10000/readyz" || echo "❌ readyz down"
      echo ""
      [[ -n "${REDIS_URL:-}" ]] && redis-cli -u "$REDIS_URL" ping 2>/dev/null || echo "⚠️ Redis לא נגיש"
      echo ""
      pgrep -fa "auto_executor.py" || echo "⚠️ אין Auto Executor פעיל"
      echo ""
      echo "CPU: $(grep 'cpu ' /proc/stat | awk '{print ($2+$4)*100/($2+$4+$5)}')%"
      echo "Memory: $(free -m | awk '/Mem/ {print $3 \"MB/\" $2 \"MB\"}')"
    } > "$REPORT_PATH"
    echo "✅ דוח נוצר ב־$REPORT_PATH"
    send_telegram "🩺 <b>AlgoGPT Health Report</b>\n📂 ${REPORT_PATH}\n🕒 $(date '+%H:%M:%S %d/%m/%Y')"
    ;;
  11)
    auto_heal
    ;;
  *)
    echo "❌ בחירה לא תקפה."
    ;;
esac

echo ""
echo "💡 SAFE MODE פעיל — אין ריסטרט כולל אוטומטי."
EOF

chmod +x /app/menu.sh
echo "✅ menu.sh נוצר בהצלחה עם Auto-Heal מלא (סעיף 11)."




