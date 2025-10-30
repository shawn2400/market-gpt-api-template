#!/usr/bin/env bash
set -euo pipefail

# === הגדרות בסיס ===
BASE="https://algogpt-docker.onrender.com"
BEARER="${API_BEARER_TOKEN:?set API_BEARER_TOKEN in Replit secrets}"
BINANCE_API_KEY="${BINANCE_API_KEY:-}"
BINANCE_API_SECRET="${BINANCE_API_SECRET:-}"

# === פונקציה להצגת פלט ===
show_output() { cat; }

# === פונקציה לבדיקת סטטוס מהיר ===
quick_status() {
  echo "⚡ Checking system status..."
  ver=$(curl -fsS "$BASE/health" 2>/dev/null | grep -o '"algogpt_version":"[^"]*"' | cut -d'"' -f4)
  tele=$(curl -fsS -H "Authorization: Bearer $BEARER" "$BASE/telegram/status" 2>/dev/null | grep -o '"state":"[^"]*"' | cut -d'"' -f4)
  ready=$(curl -fsS "$BASE/readyz" 2>/dev/null >/dev/null && echo "🟢" || echo "🔴")
  trades=$(curl -fsS -H "Authorization: Bearer $BEARER" "$BASE/trade/active" 2>/dev/null | grep -c '"symbol"')
  echo "🟢 v${ver:-unknown} | 🤖 Telegram: ${tele:-offline} | ☁️ Render: ${ready} | 💰 Active Trades: $trades"
}

# === פונקציה לבדיקת API של Binance ===
test_binance_api() {
  if [[ -z "$BINANCE_API_KEY" || -z "$BINANCE_API_SECRET" ]]; then
    echo "⚠️ BINANCE_API_KEY or BINANCE_API_SECRET not set in secrets."
    return
  fi
  echo "🔐 Testing Binance API connection..."
  ts=$(date +%s%3N)
  query="timestamp=${ts}"
  sig=$(echo -n "$query" | openssl dgst -sha256 -hmac "$BINANCE_API_SECRET" | cut -d" " -f2)
  resp=$(curl -s -H "X-MBX-APIKEY: $BINANCE_API_KEY" \
    "https://fapi.binance.com/fapi/v1/account?${query}&signature=${sig}")

  if echo "$resp" | grep -q '"canTrade":true'; then
    echo -e "✅ \033[1;32mBinance API connection OK\033[0m"
  elif echo "$resp" | grep -q '"code":-2015'; then
    echo -e "❌ \033[1;31mInvalid API key or permissions — check IP restriction\033[0m"
  else
    echo -e "⚠️ \033[1;33mUnknown response from Binance:\033[0m"
    echo "$resp"
  fi
}

# === פונקציה לדוח מערכת מלא ===
full_system_report() {
  echo "🧾 Generating full system report..."
  echo "==============================================="
  echo "🌐 Render: $(curl -fsS "$BASE/readyz" >/dev/null && echo '🟢 OK' || echo '🔴 DOWN')"
  echo "💡 Health:"
  curl -fsS "$BASE/health" | grep -E 'version|uptime|status' | sed 's/[{}\",]//g'
  echo "-----------------------------------------------"
  echo "🤖 Telegram Bot:"
  curl -fsS -H "Authorization: Bearer $BEARER" "$BASE/telegram/status" | grep -E '"state"|"ws_up"|"reconnects"'
  echo "-----------------------------------------------"
  echo "💰 Active Trades:"
  curl -fsS -H "Authorization: Bearer $BEARER" "$BASE/trade/active" | grep -E '"symbol"|"side"|"entryPrice"'
  echo "-----------------------------------------------"
  echo "📊 PnL Summary:"
  curl -fsS -H "Authorization: Bearer $BEARER" "$BASE/export/daily" | head -10
  echo "-----------------------------------------------"
  echo "🔐 Binance API:"
  test_binance_api
  echo "==============================================="
  echo "📅 Report generated at: $(date '+%Y-%m-%d %H:%M:%S %Z')"
}

# === פונקציה מרכזית ===
menu() {
  echo ""
  echo "=============================="
  echo "     🤖 AlgoGPT Super Menu"
  echo "=============================="
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
  echo "13) ⚡ Quick Status (System Summary)"
  echo "14) 🔐 Test Binance API Connection"
  echo "15) 🧾 Full System Report"
  echo "0) ❌ Exit"
  echo "=============================="
  read -rp "Choose option: " opt

  case $opt in
    1)  echo "🛰️ Running market scan..."; curl -fsS -H "Authorization: Bearer $BEARER" "$BASE/scan/public-now?indicators=1" | show_output ;;
    2)  echo "💰 Executing dry-run trade..."; curl -fsS -X POST "$BASE/trade/execute" -H "Authorization: Bearer $BEARER" -H "Content-Type: application/json" --data '{"symbol":"BTCUSDT","side":"BUY","quantity":0.01,"leverage":10,"dry_run":true}' | show_output ;;
    3)  echo "📈 Fetching active trades..."; curl -fsS -H "Authorization: Bearer $BEARER" "$BASE/trade/active" | show_output ;;
    4)  echo "⚙️ Managing open trades automatically..."; curl -fsS -X POST -H "Authorization: Bearer $BEARER" "$BASE/trade/manage" | show_output ;;
    5)  echo "📊 Generating daily PnL report..."; curl -fsS -H "Authorization: Bearer $BEARER" "$BASE/export/daily" | show_output ;;
    6)  echo "🧠 Running AI market summary..."; curl -fsS -H "Authorization: Bearer $BEARER" "$BASE/ai/summary" | show_output ;;
    7)  echo "🛠️ Deploying latest version..."; bash scripts/deploy.sh ;;
    8)  echo "🩺 Checking Render health..."; curl -fsS "$BASE/readyz" && echo "✅ ready OK" || echo "⚠️ not ready" ;;
    9)  echo "🤖 Checking Telegram bot status..."; curl -fsS -H "Authorization: Bearer $BEARER" "$BASE/telegram/status" | show_output || echo "⚠️ Telegram endpoint not found" ;;
    10) echo "📡 Fetching system metrics..."; curl -fsS -H "Authorization: Bearer $BEARER" "$BASE/metrics" | show_output ;;
    11) echo "🔄 Toggling Auto-Trading mode..."; curl -fsS -X POST -H "Authorization: Bearer $BEARER" "$BASE/trade/toggle-auto" | show_output ;;
    12) echo "🧨 KILL SWITCH – stopping all auto-trading!"; read -rp "Type YES to confirm: " conf; [[ "$conf" == "YES" ]] && curl -fsS -X POST -H "Authorization: Bearer $BEARER" "$BASE/trade/stop-all" | show_output && echo "🛑 All trading stopped." || echo "❌ Cancelled." ;;
    13) quick_status ;;
    14) test_binance_api ;;
    15) full_system_report ;;
    0)  echo "👋 Exiting. Stay sharp!"; exit 0 ;;
    *)  echo "❌ Invalid option." ;;
  esac
}

# === לולאה מתמדת ===
while true; do
  menu
done

