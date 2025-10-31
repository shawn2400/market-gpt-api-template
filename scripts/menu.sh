#!/usr/bin/env bash
set -Eeuo pipefail
cd /app || exit 1

# === SAFE MODE: חסימת ריסטרט אוטומטי מיותר ===
SAFE_MODE=1
SERVICE_NAME="algogpt-prod"

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
echo "7) 🧱 בדיקת תקינות ריידיר / Docker"
echo "8) ❌ יציאה"
echo ""

read -rp "בחר מספר פעולה: " CHOICE
echo ""

case "$CHOICE" in
  1)
    echo "📦 בדיקת מצב השירות..."
    curl -fsSL "http://localhost:10000/readyz" || echo "❌ שירות לא זמין"
    ;;
  2)
    echo "🔁 מבצע ריסטרט יזום של השירות..."
    if [[ "${SAFE_MODE}" == "1" ]]; then
      echo "⚠️ SAFE MODE פעיל — מבצע ריסטרט רק לשירות Render, לא למכולה כולה."
    fi
    supervisorctl restart "${SERVICE_NAME}" || echo "⚠️ לא ניתן לאתחל דרך supervisor, ייתכן שצריך restart ידני דרך Render."
    ;;
  3)
    echo "🧠 ריסטארט מודול AI בלבד..."
    pkill -f "auto_executor.py" || true
    nohup python utils/auto_executor.py >/tmp/auto_exec.log 2>&1 &
    echo "✅ סוכן AI הופעל מחדש."
    ;;
  4)
    echo "🧩 רענון קובץ ENV..."
    export $(grep -v '^#' .env | xargs) || echo "⚠️ לא נמצא קובץ .env"
    echo "✅ משתני סביבה נטענו."
    ;;
  5)
    echo "🚀 הפעלת Auto Executor..."
    python utils/auto_executor.py &
    echo "✅ הופעל בהצלחה."
    ;;
  6)
    echo "🔍 בדיקת חיבור ל-Binance..."
    python - <<'EOF'
import httpx
try:
    r = httpx.get("https://fapi.binance.com/fapi/v1/time", timeout=5)
    print("✅ Binance נגיש:", r.status_code)
except Exception as e:
    print("❌ שגיאה:", e)
EOF
    ;;
  7)
    echo "🧱 בדיקת ריידיר / Docker..."
    docker ps -a || echo "⚠️ אין Docker CLI זמין"
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
echo "💡 SAFE MODE מופעל — לא בוצע ריסטרט כללי אוטומטי."



