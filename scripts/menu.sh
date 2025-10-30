#!/usr/bin/env bash
set -euo pipefail

# === הגדרות בסיס ===
BASE="https://algogpt-docker.onrender.com"
BEARER="${API_BEARER_TOKEN:?set API_BEARER_TOKEN in Replit secrets}"

# === פונקציה להצגת פלט ===
show_output() {
  # מציג פלט גולמי בלבד (ללא jq)
  cat
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
  echo "0) ❌ Exit"
  echo "=============================="
  read -rp "Choose option: " opt

  case $opt in
    1)
      echo "🛰️ Running market scan..."
      curl -fsS -H "Authorization: Bearer $BEARER" \
        "$BASE/scan/public-now?indicators=1" | show_output
      ;;
    2)
      echo "💰 Executing dry-run trade..."
      curl -fsS -X POST "$BASE/trade/execute" \
        -H "Authorization: Bearer $BEARER" \
        -H "Content-Type: application/json" \
        --data '{"symbol":"BTCUSDT","side":"BUY","quantity":0.01,"leverage":10,"dry_run":true}' | show_output
      ;;
    3)
      echo "📈 Fetching active trades..."
      curl -fsS -H "Authorization: Bearer $BEARER" \
        "$BASE/trade/active" | show_output
      ;;
    4)
      echo "⚙️ Managing open trades automatically..."
      curl -fsS -X POST -H "Authorization: Bearer $BEARER" \
        "$BASE/trade/manage" | show_output
      ;;
    5)
      echo "📊 Generating daily PnL report..."
      curl -fsS -H "Authorization: Bearer $BEARER" \
        "$BASE/export/daily" | show_output
      ;;
    6)
      echo "🧠 Running AI market summary..."
      curl -fsS -H "Authorization: Bearer $BEARER" \
        "$BASE/ai/summary" | show_output
      ;;
    7)
      echo "🛠️ Deploying latest version..."
      bash scripts/deploy.sh
      ;;
    8)
      echo "🩺 Checking Render health..."
      curl -fsS "$BASE/readyz" && echo "✅ ready OK"
      curl -fsS "$BASE/healthz" || echo "⚠️ may require POST"
      ;;
    9)
      echo "🤖 Checking Telegram bot status..."
      curl -fsS -H "Authorization: Bearer $BEARER" \
        "$BASE/telegram/status" | show_output || \
        echo "⚠️ Telegram endpoint not found"
      ;;
    10)
      echo "📡 Fetching system metrics..."
      curl -fsS -H "Authorization: Bearer $BEARER" \
        "$BASE/metrics" | show_output
      ;;
    11)
      echo "🔄 Toggling Auto-Trading mode..."
      curl -fsS -X POST -H "Authorization: Bearer $BEARER" \
        "$BASE/trade/toggle-auto" | show_output
      ;;
    12)
      echo "🧨 KILL SWITCH – stopping all auto-trading!"
      read -rp "Type YES to confirm: " conf
      if [[ "$conf" == "YES" ]]; then
        curl -fsS -X POST -H "Authorization: Bearer $BEARER" \
          "$BASE/trade/stop-all" | show_output
        echo "🛑 All trading stopped."
      else
        echo "❌ Cancelled."
      fi
      ;;
    0)
      echo "👋 Exiting. Stay sharp!"
      exit 0
      ;;
    *)
      echo "❌ Invalid option."
      ;;
  esac
}

# === לולאה מתמדת ===
while true; do
  menu
done
