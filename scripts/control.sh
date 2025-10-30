#!/usr/bin/env bash
set -euo pipefail

# === הגדרות בסיס ===
BASE="${BASE:-https://algogpt-docker.onrender.com}"
BEARER="${API_BEARER_TOKEN:?set API_BEARER_TOKEN in Replit secrets}"
BINANCE_API_KEY="${BINANCE_API_KEY:-}"
BINANCE_API_SECRET="${BINANCE_API_SECRET:-}"

# === פונקציה בסיסית לקריאות API ===
call() {
  local path="$1"
  local method="${2:-GET}"
  local body="${3:-}"
  if [ "$method" = "POST" ]; then
    curl -fsS -X POST "$BASE$path" \
      -H "Authorization: Bearer $BEARER" \
      -H "Content-Type: application/json" \
      --data "$body"
  else
    curl -fsS -X GET "$BASE$path" \
      -H "Authorization: Bearer $BEARER"
  fi
  echo
}

# === Quick Status ===
quick_status() {
  echo "⚡ Checking system quick status..."
  ver=$(curl -fsS "$BASE/health" 2>/dev/null | grep -o '"algogpt_version":"[^"]*"' | cut -d'"' -f4)
  tele=$(curl -fsS -H "Authorization: Bearer $BEARER" "$BASE/telegram/status" 2>/dev/null | grep -o '"state":"[^"]*"' | cut -d'"' -f4)
  ready=$(curl -fsS "$BASE/readyz" 2>/dev/null >/dev/null && echo "🟢" || echo "🔴")
  trades=$(curl -fsS -H "Authorization: Bearer $BEARER" "$BASE/trade/active" 2>/dev/null | grep -c '"symbol"')
  echo "🟢 Version: ${ver:-unknown} | 🤖 Telegram: ${tele:-offline} | ☁️ Render: ${ready} | 💰 Active Trades: $trades"
}

# === Binance API Validation ===
check_binance_api() {
  if [[ -z "$BINANCE_API_KEY" || -z "$BINANCE_API_SECRET" ]]; then
    echo "⚠️ Binance API keys missing. Add BINANCE_API_KEY and BINANCE_API_SECRET to secrets."
    return
  fi
  echo "🔐 Validating Binance API..."
  ts=$(date +%s%3N)
  query="timestamp=${ts}"
  sig=$(echo -n "$query" | openssl dgst -sha256 -hmac "$BINANCE_API_SECRET" | cut -d" " -f2)
  resp=$(curl -s -H "X-MBX-APIKEY: $BINANCE_API_KEY" \
    "https://fapi.binance.com/fapi/v1/account?${query}&signature=${sig}")
  if echo "$resp" | grep -q '"canTrade":true'; then
    echo -e "✅ \033[1;32mBinance API Connection OK\033[0m"
  elif echo "$resp" | grep -q '"code":-2015'; then
    echo -e "❌ \033[1;31mInvalid API key or permissions — check IP restriction\033[0m"
  else
    echo -e "⚠️ \033[1;33mUnexpected response from Binance:\033[0m"
    echo "$resp"
  fi
}

# === דוח מערכת מלא ===
full_report() {
  echo "🧾 Generating Full System Report..."
  echo "=================================================="
  echo "🌐 Render Health: $(curl -fsS "$BASE/readyz" >/dev/null && echo '🟢 OK' || echo '🔴 DOWN')"
  echo "----------------------------------------------"
  echo "💡 Health Info:"
  curl -fsS "$BASE/health" | grep -E 'version|uptime|status' | sed 's/[{}\",]//g'
  echo "----------------------------------------------"
  echo "🤖 Telegram Bot:"
  curl -fsS -H "Authorization: Bearer $BEARER" "$BASE/telegram/status" | grep -E '"state"|"ws_up"|"reconnects"'
  echo "----------------------------------------------"
  echo "💰 Active Trades:"
  curl -fsS -H "Authorization: Bearer $BEARER" "$BASE/trade/active" | grep -E '"symbol"|"side"|"entryPrice"'
  echo "----------------------------------------------"
  echo "📊 PnL Summary:"
  curl -fsS -H "Authorization: Bearer $BEARER" "$BASE/export/daily" | head -10
  echo "----------------------------------------------"
  echo "🔐 Binance API:"
  check_binance_api
  echo "----------------------------------------------"
  echo "🕐 Timestamp: $(date '+%Y-%m-%d %H:%M:%S %Z')"
  echo "=================================================="
}

# === שליחת דוח לטלגרם (אם זמין) ===
send_to_telegram() {
  local msg="$1"
  local token="${TELEGRAM_BOT_TOKEN:-}"
  local chat_id="${TELEGRAM_CHAT_ID:-}"
  if [[ -n "$token" && -n "$chat_id" ]]; then
    echo "📨 Sending report to Telegram..."
    curl -s -X POST "https://api.telegram.org/bot${token}/sendMessage" \
      -d "chat_id=${chat_id}" \
      -d "text=${msg}" \
      -d "parse_mode=HTML" >/dev/null && echo "✅ Sent successfully!"
  else
    echo "⚠️ Telegram not configured (missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID)"
  fi
}

# === מצבי הרצה ===
case "${1:-}" in
  quick-status)
    quick_status
    ;;
  binance-check)
    check_binance_api
    ;;
  full-report)
    report=$(full_report)
    echo "$report"
    send_to_telegram "<pre>$(echo "$report" | sed 's/&/&amp;/g;s/</\&lt;/g;s/>/\&gt;/g')</pre>"
    ;;
  deploy)
    bash scripts/deploy.sh
    ;;
  *)
    echo "Usage:"
    echo "  bash scripts/control.sh quick-status     # מצב מהיר"
    echo "  bash scripts/control.sh binance-check    # בדיקת Binance API"
    echo "  bash scripts/control.sh full-report      # דוח מערכת מלא + שליחה לטלגרם"
    echo "  bash scripts/control.sh deploy           # הפעלת deploy אוטומטי"
    ;;
esac
