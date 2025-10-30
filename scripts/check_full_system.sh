#!/usr/bin/env bash
set -euo pipefail

BASE="https://algogpt-docker.onrender.com"
BEARER="${API_BEARER_TOKEN:?set API_BEARER_TOKEN in secrets}"
TG_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
TG_CHAT="${TELEGRAM_CHAT_ID:-}"

G="\033[1;32m"; R="\033[1;31m"; Y="\033[1;33m"; N="\033[0m"

section() {
  echo -e "\n${Y}=============================="
  echo -e "🔎 $1"
  echo -e "==============================${N}"
}

send_telegram() {
  local msg="$1"
  if [[ -n "${TG_TOKEN}" && -n "${TG_CHAT}" ]]; then
    curl -s -X POST "https://api.telegram.org/bot${TG_TOKEN}/sendMessage" \
         -d "chat_id=${TG_CHAT}" -d "text=${msg}" -d "parse_mode=HTML" >/dev/null || true
  fi
}

# === 1. VERSION CHECK ===
section "System Version"
ver=$(curl -s -H "Authorization: Bearer $BEARER" "$BASE/version" | grep -o '"algogpt_version":"[^"]*"' | cut -d'"' -f4 || echo "n/a")
echo -e "📦 AlgoGPT Version: ${G}${ver}${N}"

# === 2. RENDER HEALTH ===
section "Render Health"
ready=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/readyz" || echo "000")
health=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/healthz" || echo "000")
if [[ "$ready" == "200" && "$health" == "200" ]]; then
  echo -e "☁️ Render: ${G}OK${N}"
else
  echo -e "☁️ Render: ${R}NOT HEALTHY${N} (readyz=$ready, healthz=$health)"
fi

# === 3. TELEGRAM BOT STATUS ===
section "Telegram Bot"
if curl -s -H "Authorization: Bearer $BEARER" "$BASE/telegram/status" | grep -q '"ok":true'; then
  echo -e "🧠 Telegram Bot: ${G}Connected${N}"
else
  echo -e "🧠 Telegram Bot: ${R}Not responding${N}"
fi

# === 4. BINANCE CHECKS ===
section "Binance Futures & Spot"
echo "🔍 Futures status:"
if curl -fsS -H "Authorization: Bearer $BEARER" "$BASE/binance/status" >/dev/null 2>&1; then
  echo -e "✅ Futures API reachable"
else
  echo -e "❌ Cannot reach Futures API"
fi

echo "🔍 Futures balance:"
if curl -fsS -H "Authorization: Bearer $BEARER" "$BASE/binance/futures-balance" >/dev/null 2>&1; then
  echo -e "✅ Futures balance OK"
else
  echo -e "❌ Balance failed"
fi

echo "🔍 Spot account:"
if curl -fsS -H "Authorization: Bearer $BEARER" "$BASE/binance/spot-status" >/dev/null 2>&1; then
  echo -e "✅ Spot OK"
else
  echo -e "⚠️ Spot failed (optional)"
fi

echo "🔍 HMAC signature:"
if curl -fsS -H "Authorization: Bearer $BEARER" "$BASE/binance/hmac-test" >/dev/null 2>&1; then
  echo -e "✅ HMAC valid"
else
  echo -e "❌ Invalid HMAC or signature mismatch"
fi

# === 5. PNL REPORT ===
section "PnL Summary"
curl -fsS -H "Authorization: Bearer $BEARER" "$BASE/export/daily" | head -n 20 || echo "⚠️ PnL summary unavailable"

# === 6. ERROR DIAGNOSIS ===
section "Diagnostic Result"
echo -e "⚠️ אם אתה מקבל הודעה מסוג: \"Binance Futures permissions required\" — הנה ההסבר המלא:"
cat <<'EOF'

הסיבה המדויקת:
אחד מהבאים (או כולם):
❌ ה-API Key לא מאושר ל-Futures Trading
❌ יש הגבלת IP שחוסמת את 35.200.193.249
❌ ה-API Key לא פעיל או פג תוקפו

🔧 מה לעשות:
1️⃣ היכנס ל-Binance.com > API Management
2️⃣ מצא את ה-API Key שלך שמתחיל ב- cGlzKn6A...yADH
3️⃣ לחץ Edit לידו ובדוק:
   ✅ Enable Reading
   ✅ Enable Futures
   ✅ Enable Spot & Margin Trading (רשות)
4️⃣ תחת IP Access Restrictions:
   מומלץ לבחור "Unrestricted"
   או הוסף את IP:
   👉 35.200.193.249 (שרת Replit)
5️⃣ שמור (Save / Confirm)
6️⃣ המתן 1-2 דקות
7️⃣ הפעל שוב את הסקריפט הזה או אמור לי "בדוק שוב"

⚡ בדיקות שיבוצעו:
✅ /fapi/v2/balance
✅ /fapi/v2/account
✅ /fapi/v2/positionRisk

📋 Checklist מהיר:
□ נכנסתי ל-Binance.com
□ נכנסתי ל-API Management
□ Enable Reading ✅
□ Enable Futures ✅
□ הסרתי או עדכנתי IP restriction
□ שמרתי ✅
□ המתנתי ✅
□ הרצת בדיקה חוזרת ✅

אם עדיין לא עובד → צור API Key חדש עם:
✅ Enable Reading
✅ Enable Futures
Unrestricted Access
והדבק אותו ב־Replit Secrets:
BINANCE_API_KEY
BINANCE_API_SECRET

EOF

echo -e "\n${Y}🔄 אחרי שתתקן – הרץ שוב: bash scripts/check_full_system.sh${N}"

# === 7. TELEGRAM ALERT SUMMARY ===
msg="📊 AlgoGPT System Check\n☁️ Render: $ready/$health\n🤖 Telegram: $(if [[ "$ready" == "200" ]]; then echo OK; else echo FAIL; fi)\n💰 Binance Futures: $(if curl -fsS -H "Authorization: Bearer $BEARER" "$BASE/binance/futures-balance" >/dev/null 2>&1; then echo OK; else echo FAIL; fi)\n🧠 Version: ${ver}"
send_telegram "$msg"


