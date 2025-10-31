#!/usr/bin/env bash
set -euo pipefail

BASE="https://algogpt-docker.onrender.com"
BEARER="${API_BEARER_TOKEN:?set API_BEARER_TOKEN in Replit or Render secrets}"
TG_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
TG_CHAT="${TELEGRAM_CHAT_ID:-}"
STATE_FILE="scripts/.last_status"
LOG_FILE="/tmp/auto_executor.log"

G="\033[1;32m"; R="\033[1;31m"; Y="\033[1;33m"; C="\033[1;36m"; N="\033[0m"

send_telegram() {
  local msg="$1"
  if [[ -n "$TG_TOKEN" && -n "$TG_CHAT" ]]; then
    curl -s -X POST "https://api.telegram.org/bot${TG_TOKEN}/sendMessage" \
      -d "chat_id=${TG_CHAT}" -d "text=${msg}" -d "parse_mode=HTML" >/dev/null || true
  fi
}

show_output() { cat; }

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

  cur_state="${render_ok}|${tg_ok}"
  prev_state=$(cat "$STATE_FILE" 2>/dev/null || echo "")
  if [[ "$cur_state" != "$prev_state" ]]; then
    echo "$cur_state" >"$STATE_FILE"
    if [[ "$render_ok" != "OK" || "$tg_ok" != "OK" ]]; then
      send_telegram "⚠️ <b>AlgoGPT Alert</b>\n🔴 Render: ${render_ok}\n🤖 Telegram: ${tg_ok}\n🕐 $(date '+%H:%M:%S %d/%m/%Y')"
    else
      send_telegram "✅ <b>AlgoGPT Recovered</b>\n☁️ Render OK\n🧠 Telegram OK\n🕐 $(date '+%H:%M:%S %d/%m/%Y')"
    fi
  fi
  echo -e "${G}🟢 v${version}${N} | ${tg_display} | ${render_display} | 💰 Active: ${Y}${trades}${N}"
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
  echo "14) 🔐 Check Binance Permissions"
  echo "15) 🔄 Git Sync & Push (Auto)"
  echo "16) 🧠 Full Auto-Heal & Sync"
  echo "17) ⚙️ Restart AutoExecutor (Render Executor Mode)"
  echo "18) 📜 View AutoExecutor Logs (Live Tail)"
  echo "0) ❌ Exit"
  echo "=============================="
  read -rp "Choose option: " opt

  case $opt in
    1) echo "🛰️ Running market scan..."; curl -fsS -H "Authorization: Bearer $BEARER" "$BASE/scan/public-now?indicators=1" | show_output ;;
    2) echo "💰 Executing dry-run trade..."; curl -fsS -X POST "$BASE/trade/execute" -H "Authorization: Bearer $BEARER" -H "Content-Type: application/json" --data '{"symbol":"BTCUSDT","side":"BUY","quantity":0.01,"leverage":10,"dry_run":true}' | show_output ;;
    3) echo "📈 Fetching active trades..."; curl -fsS -H "Authorization: Bearer $BEARER" "$BASE/trade/active" | show_output ;;
    4) echo "⚙️ Managing open trades automatically..."; curl -fsS -X POST -H "Authorization: Bearer $BEARER" "$BASE/trade/manage" | show_output ;;
    5) echo "📊 Generating daily PnL report..."; curl -fsS -H "Authorization: Bearer $BEARER" "$BASE/export/daily" | show_output ;;
    6) echo "🧠 Running AI market summary..."; curl -fsS -H "Authorization: Bearer $BEARER" "$BASE/ai/summary" | show_output ;;
    7) echo "🛠️ Deploying latest version..."; bash scripts/deploy.sh ;;
    8) echo "🩺 Checking Render health..."; curl -fsS "$BASE/readyz" && echo "✅ ready OK"; curl -fsS "$BASE/healthz" || echo "⚠️ may require POST" ;;
    9) echo "🤖 Checking Telegram bot status..."; curl -fsS -H "Authorization: Bearer $BEARER" "$BASE/telegram/status" | show_output ;;
    10) echo "📡 Fetching system metrics..."; curl -fsS -H "Authorization: Bearer $BEARER" "$BASE/metrics" | show_output ;;
    11) echo "🔄 Toggling Auto-Trading mode..."; curl -fsS -X POST -H "Authorization: Bearer $BEARER" "$BASE/trade/toggle-auto" | show_output ;;
    12) echo "🧨 KILL SWITCH – stopping all auto-trading!"; read -rp "Type YES to confirm: " conf; [[ "$conf" == "YES" ]] && curl -fsS -X POST -H "Authorization: Bearer $BEARER" "$BASE/trade/stop-all" | show_output ;;
    13) echo "🧩 Running full system diagnostic..."; bash scripts/check_full_system.sh ;;
    14) echo "🔐 Checking Binance API connectivity..."; bash scripts/check_binance_api.sh ;;
    15) echo "🔄 Running Git auto-sync..."; bash scripts/git_fix_sync.sh ;;
    16) echo -e "${Y}🧠 Running Full Auto-Heal & Sync...${N}"; send_telegram "🧠 <b>Full Auto-Heal Triggered</b>\nRunning complete system check + Git self-sync..."; bash scripts/check_full_system.sh ;;
    17)
      echo -e "${C}⚙️ Restarting AutoExecutor safely...${N}"
      bash scripts/auto_executor_restart.sh
      ;;
    18)
      echo -e "${Y}📜 Viewing AutoExecutor logs (Ctrl+C to exit)...${N}"
      [[ -f "$LOG_FILE" ]] && tail -n 40 -f "$LOG_FILE" || echo -e "${R}No log file found ($LOG_FILE)${N}"
      ;;
    0) echo "👋 Exiting. Stay sharp!"; exit 0 ;;
    *) echo "❌ Invalid option." ;;
  esac
}

while true; do
  menu
done



