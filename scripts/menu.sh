#!/usr/bin/env bash
set -euo pipefail

# === CONFIG ===
BASE="https://algogpt-docker.onrender.com"
BEARER="${API_BEARER_TOKEN:?set API_BEARER_TOKEN in Replit or Render secrets}"
TG_TOKEN="${TELEGRAM_BOT_TOKEN:?set TELEGRAM_BOT_TOKEN in secrets}"
TG_CHAT="${TELEGRAM_CHAT_ID:?set TELEGRAM_CHAT_ID in secrets}"
STATE_FILE="scripts/.last_status"

# === Colors ===
G="\033[1;32m"; R="\033[1;31m"; Y="\033[1;33m"; N="\033[0m"

send_telegram() {
  local msg="$1"
  curl -s -X POST "https://api.telegram.org/bot${TG_TOKEN}/sendMessage" \
       -d "chat_id=${TG_CHAT}" -d "text=${msg}" -d "parse_mode=HTML" >/dev/null || true
}

show_output() { cat; }

# === Quick Status Live Line ===
quick_status() {
  local version tg_ok render_ok trades cur_state prev_state
  version=$(curl -s -H "Authorization: Bearer $BEARER" "$BASE/version" | grep -o '"algogpt_version":"[^"]*"' | cut -d'"' -f4 || echo "n/a")

  if curl -s -H "Authorization: Bearer $BEARER" "$BASE/telegram/status" | grep -q '"ok":true'; then
    tg_ok="OK"; tg_display="${G}🧠 Telegram OK${N}"
  else
    tg_ok="DOWN"; tg_display="${R}⚠️ Telegram Off${N}"
  fi

  http_code=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/readyz" || echo "000")
  if [ "$http_code" = "200" ]; then
    render_ok="OK"; render_display="${G}☁️ Render OK${N}"
  else
    render_ok="DOWN"; render_display="${R}☁️ Render Down${N}"
  fi

  trades=$(curl -s -H "Authorization: Bearer $BEARER" "$BASE/trade/active" | grep -c '"symbol"' || echo "0")

  echo -e "${G}🟢 v${version}${N} | ${tg_display} | ${render_display} | 💰 Active: ${Y}${trades}${N}"
}

# === MAIN MENU ===
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
  echo "13) 🧩 System Diagnostic (Quick)"
  echo "14) 🔐 Check Binance Permissions"
  echo "15) 🧰 Auto-Fix Binance Keys"
  echo "16) 🧠 Full System Check (Auto Diagnostic)"
  echo "0) ❌ Exit"
  echo "=============================="
  read -rp "Choose option: " opt

  case $opt in
    1)  echo "🛰️ Running market scan..."
        curl -fsS -H "Authorization: Bearer $BEARER" "$BASE/scan/public-now?indicators=1" | show_output ;;
    2)  echo "💰 Executing dry-run trade..."
        curl -fsS -X POST "$BASE/trade/execute" \
             -H "Authorization: Bearer $BEARER" \
             -H "Content-Type: application/json" \
             --data '{"symbol":"BTCUSDT","side":"BUY","quantity":0.01,"leverage":10,"dry_run":true}' | show_output ;;
    3)  echo "📈 Fetching active trades..."
        curl -fsS -H "Authorization: Bearer $BEARER" "$BASE/trade/active" | show_output ;;
    4)  echo "⚙️ Managing open trades automatically..."
        curl -fsS -X POST -H "Authorization: Bearer $BEARER" "$BASE/trade/manage" | show_output ;;
    5)  echo "📊 Generating daily PnL report..."
        curl -fsS -H "Authorization: Bearer $BEARER" "$BASE/export/daily" | show_output ;;
    6)  echo "🧠 Running AI market summary..."
        curl -fsS -H "Authorization: Bearer $BEARER" "$BASE/ai/summary" | show_output ;;
    7)  echo "🛠️ Deploying latest version..."
        bash scripts/deploy.sh ;;
    8)  echo "🩺 Checking Render health..."
        curl -fsS "$BASE/readyz" && echo "✅ ready OK"
        curl -fsS "$BASE/healthz" || echo "⚠️ may require POST" ;;
    9)  echo "🤖 Checking Telegram bot status..."
        curl -fsS -H "Authorization: Bearer $BEARER" "$BASE/telegram/status" | show_output || echo "⚠️ Telegram endpoint not found" ;;
   10)  echo "📡 Fetching system metrics..."
        curl -fsS -H "Authorization: Bearer $BEARER" "$BASE/metrics" | show_output ;;
   11)  echo "🔄 Toggling Auto-Trading mode..."
        curl -fsS -X POST -H "Authorization: Bearer $BEARER" "$BASE/trade/toggle-auto" | show_output ;;
   12)  echo "🧨 KILL SWITCH – stopping all auto-trading!"
        read -rp "Type YES to confirm: " conf
        if [[ "$conf" == "YES" ]]; then
          curl -fsS -X POST -H "Authorization: Bearer $BEARER" "$BASE/trade/stop-all" | show_output
          echo "🛑 All trading stopped."
        else echo "❌ Cancelled."; fi ;;
   13)  echo "🧩 Running quick diagnostic..."
        bash scripts/check_full_system.sh | head -n 40 ;;
   14)  echo "🔐 Checking Binance API permissions..."
        bash scripts/check_full_system.sh | grep -A10 "Binance Futures" ;;
   15)  echo "🧰 Running Binance API Fix..."
        bash scripts/menu_auto_fix.sh || echo "⚠️ Auto-fix script missing (menu_auto_fix.sh)" ;;
   16)  echo "🧠 Running full system diagnostic..."
        bash scripts/check_full_system.sh ;;
    0)  echo "👋 Exiting. Stay sharp!"; exit 0 ;;
    *)  echo "❌ Invalid option." ;;
  esac
}

while true; do
  menu
done



