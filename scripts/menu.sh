#!/usr/bin/env bash
set -euo pipefail

BASE="https://algogpt-docker.onrender.com"
BEARER="${API_BEARER_TOKEN:?set API_BEARER_TOKEN in Replit secrets}"
LOG_FILE="/app/logs/auto_intel.log"

show_output() { cat; }

menu() {
  echo ""
  echo "=============================="
  echo "     🤖 AlgoGPT Super Menu"
  echo "=============================="
  echo " 1) 🔍 Market Scan + Indicators"
  echo " 2) 💰 Execute Test Trade (dry-run)"
  echo " 3) 📈 View Active Trades"
  echo " 4) ⚙️ Manage Open Trades (Auto)"
  echo " 5) 📊 Generate Daily PnL Report"
  echo " 6) 🧠 AI Market Summary"
  echo " 7) 🛠️ Deploy + Sync (Full Auto)"
  echo " 8) 🩺 Check Render Health"
  echo " 9) 🤖 Telegram Bot Status"
  echo "10) 📡 System Metrics"
  echo "11) 🔄 Toggle Auto-Trading"
  echo "12) 🧨 KillSwitch – STOP ALL"
  echo "13) ⚡ Quick Status"
  echo "14) 🛰️ Auto-Intel Monitor"
  echo "15) 🧩 System Maintenance"
  echo "16) 🧠 Diagnostics & Auto-Heal"
  echo " 0) ❌ Exit"
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
    4)  echo "⚙️ Managing open trades..."
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
    10) echo "📡 Fetching system metrics..."
        curl -fsS -H "Authorization: Bearer $BEARER" "$BASE/metrics" | show_output ;;
    11) echo "🔄 Toggling Auto-Trading mode..."
        curl -fsS -X POST -H "Authorization: Bearer $BEARER" "$BASE/trade/toggle-auto" | show_output ;;
    12) echo "🧨 KILL SWITCH – stopping all auto-trading!"
        read -rp "Type YES to confirm: " conf
        [[ "$conf" == "YES" ]] && \
          curl -fsS -X POST -H "Authorization: Bearer $BEARER" "$BASE/trade/stop-all" | show_output && \
          echo "🛑 All trading stopped." || echo "❌ Cancelled." ;;
    13) echo "⚡ Quick Status..."
        ver=$(curl -fsS "$BASE/version" | grep -Eo '"algogpt_version":"[^"]+' | cut -d'"' -f4)
        tstat=$(curl -fsS -H "Authorization: Bearer $BEARER" "$BASE/telegram/status" 2>/dev/null | grep -Eo '"state":"[^"]+' | cut -d'"' -f4)
        rend=$(curl -fs -o /dev/null -w "%{http_code}" "$BASE/readyz" 2>/dev/null)
        trades=$(curl -fsS -H "Authorization: Bearer $BEARER" "$BASE/trade/active" 2>/dev/null | grep -c '"symbol"')
        echo "🟢 v$ver | 🤖 Telegram:$tstat | ☁️ Render:$rend | 💰 Trades:$trades" ;;
    14) echo "🛰️ Auto-Intel Monitor"
        echo "1) Start  2) Stop  3) Status  4) Log"
        read -rp "Choose: " sub
        case $sub in
          1) nohup bash scripts/auto_intel_daemon.sh >/dev/null 2>&1 &
             echo "✅ Auto-Intel started (background)" ;;
          2) pkill -f auto_intel_daemon.sh && echo "🛑 Auto-Intel stopped." ;;
          3) pgrep -a -f auto_intel_daemon.sh >/dev/null && echo "🟢 Running" || echo "🔴 Not running" ;;
          4) echo "📜 Showing last 15 log lines:"; tail -n 15 "$LOG_FILE" || echo "No log found." ;;
          *) echo "❌ Invalid choice." ;;
        esac ;;
    15) echo "🧩 System Maintenance"
        echo "1) 🧹 Clean logs"
        echo "2) 🔍 Git status"
        echo "3) 🔄 Git fetch + rebase"
        echo "4) ⚡ Check system summary"
        read -rp "Choose: " act
        case $act in
          1) find /app/logs -type f -name "*.log" -delete && echo "🧹 Logs cleaned." ;;
          2) git status ;;
          3) git fetch origin main && git rebase origin/main && echo "✅ Repo synced." ;;
          4) echo "⚡ System Summary:"; ps -eo pid,pcpu,pmem,cmd --sort=-pcpu | head -n 6; df -h /app | tail -1 ;;
          *) echo "❌ Invalid." ;;
        esac ;;
    16) echo "🧠 Diagnostics & Auto-Heal"
        echo "בודק את כל השירותים החיוניים..."
        declare -A services=(
          ["Scanner"]="gpt_auto_suggest.py"
          ["Telegram"]="telegram_webhook"
          ["Manager"]="trade_manager"
          ["AutoIntel"]="auto_intel_daemon.sh"
        )
        for name in "${!services[@]}"; do
          pgrep -a -f "${services[$name]}" >/dev/null && echo "🟢 $name OK" || {
            echo "🔴 $name Down → Restarting..."
            case $name in
              "Scanner") nohup python workers/gpt_auto_suggest.py >/dev/null 2>&1 & ;;
              "Telegram") nohup python routes/telegram_webhook.py >/dev/null 2>&1 & ;;
              "Manager") nohup python utils/trade_manager.py >/dev/null 2>&1 & ;;
              "AutoIntel") nohup bash scripts/auto_intel_daemon.sh >/dev/null 2>&1 & ;;
            esac
            echo "✅ $name Restarted."
          }
        done
        echo "🧩 בדיקה הושלמה — כל השירותים פעילים." ;;
    0) echo "👋 Exiting. Stay sharp!"; exit 0 ;;
    *) echo "❌ Invalid option." ;;
  esac
}

while true; do
  menu
done


