#!/usr/bin/env bash
set -euo pipefail

BASE="https://algogpt-docker.onrender.com"
BEARER="${API_BEARER_TOKEN:?set API_BEARER_TOKEN in secrets}"
TG_TOKEN="${TELEGRAM_BOT_TOKEN:?set TELEGRAM_BOT_TOKEN in secrets}"
TG_CHAT="${TELEGRAM_CHAT_ID:?set TELEGRAM_CHAT_ID in secrets}"
STATE_FILE="scripts/.last_status"

G="\033[1;32m"; R="\033[1;31m"; Y="\033[1;33m"; N="\033[0m"

send_telegram() {
  curl -s -X POST "https://api.telegram.org/bot${TG_TOKEN}/sendMessage" \
       -d "chat_id=${TG_CHAT}" -d "text=${1}" -d "parse_mode=HTML" >/dev/null || true
}

show_output() { cat; }

quick_status() {
  version=$(curl -s -H "Authorization: Bearer $BEARER" "$BASE/version" | grep -o '"algogpt_version":"[^"]*"' | cut -d'"' -f4 || echo "n/a")
  if curl -s -H "Authorization: Bearer $BEARER" "$BASE/telegram/status" | grep -q '"ok":true'; then tg="🧠 OK"; else tg="⚠️ Off"; fi
  http_code=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/readyz" || echo "000")
  if [ "$http_code" = "200" ]; then rd="☁️ OK"; else rd="☁️ Down"; fi
  trades=$(curl -s -H "Authorization: Bearer $BEARER" "$BASE/trade/active" | grep -c '"symbol"' || echo "0")
  echo -e "${G}🟢 v${version}${N} | ${tg} | ${rd} | 💰 Active:${Y}${trades}${N}"
}

menu() {
  clear
  echo "=============================="
  echo "     🤖 AlgoGPT Super Menu"
  echo "=============================="
  quick_status
  echo "------------------------------"
  echo "1) 🔍 Market Scan + Indicators"
  echo "2) 💰 Execute Test Trade (dry-run)"
  echo "3) 📈 View Active Trades"
  echo "4) ⚙️ Manage Open Trades (Auto)"
  echo "5) 📊 Generate Daily PnL Report"
  echo "6) 🧠 AI Market Summary"
  echo "7) 🛠️ Deploy + Sync (Full Auto)"
  echo "8) 🩺 Check Render Health"
  echo "9) 🤖 Telegram Bot Status"
  echo "10) 📡 System Metrics"
  echo "11) 🔄 Toggle Auto-Trading"
  echo "12) 🧨 KillSwitch – STOP ALL"
  echo "13) 🧩 System Diagnostic (Full Check)"
  echo "14) 🔐 Check Binance API Connectivity"
  echo "0) ❌ Exit"
  echo "=============================="
  read -rp "Choose option: " opt
  case $opt in
    1) curl -fsS -H "Authorization: Bearer $BEARER" "$BASE/scan/public-now?indicators=1" | show_output;;
    2) curl -fsS -X POST "$BASE/trade/execute" -H "Authorization: Bearer $BEARER" -H "Content-Type: application/json" --data '{"symbol":"BTCUSDT","side":"BUY","quantity":0.01,"leverage":10,"dry_run":true}' | show_output;;
    3) curl -fsS -H "Authorization: Bearer $BEARER" "$BASE/trade/active" | show_output;;
    4) curl -fsS -X POST -H "Authorization: Bearer $BEARER" "$BASE/trade/manage" | show_output;;
    5) curl -fsS -H "Authorization: Bearer $BEARER" "$BASE/export/daily" | show_output;;
    6) curl -fsS -H "Authorization: Bearer $BEARER" "$BASE/ai/summary" | show_output;;
    7) bash scripts/deploy.sh;;
    8) curl -fsS "$BASE/readyz" && echo "✅ ready OK"; curl -fsS "$BASE/healthz" || echo "⚠️ may require POST";;
    9) curl -fsS -H "Authorization: Bearer $BEARER" "$BASE/telegram/status" | show_output || echo "⚠️ Telegram endpoint not found";;
   10) curl -fsS -H "Authorization: Bearer $BEARER" "$BASE/metrics" | show_output;;
   11) curl -fsS -X POST -H "Authorization: Bearer $BEARER" "$BASE/trade/toggle-auto" | show_output;;
   12) read -rp "Type YES to confirm: " c; [[ "$c" == "YES" ]] && curl -fsS -X POST -H "Authorization: Bearer $BEARER" "$BASE/trade/stop-all" | show_output && echo "🛑 Stopped."; ;
   13) bash scripts/check_full_system.sh;;
   14) bash scripts/check_full_system.sh --binance-only;;
    0) echo "👋 Exit."; exit 0;;
    *) echo "❌ Invalid option.";;
  esac
}

while true; do menu; done


