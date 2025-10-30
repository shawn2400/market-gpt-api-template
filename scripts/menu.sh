#!/usr/bin/env bash
set -euo pipefail
BASE="https://algogpt-docker.onrender.com"
BEARER="${API_BEARER_TOKEN:?set API_BEARER_TOKEN in Replit secrets}"

menu() {
  echo ""
  echo "=============================="
  echo "   🚀 AlgoGPT Command Menu"
  echo "=============================="
  echo "1) 🔍 Scan market (public-now)"
  echo "2) 💰 Execute test trade (dry-run)"
  echo "3) 📊 Get daily PnL report"
  echo "4) 🧠 AI analysis (summary)"
  echo "5) 🛠️ Deploy new version"
  echo "6) 🩺 Check Render health"
  echo "0) ❌ Exit"
  echo "=============================="
  read -rp "Choose option: " opt

  case $opt in
    1)
      curl -fsS -H "Authorization: Bearer $BEARER" "$BASE/scan/public-now" | jq .
      ;;
    2)
      curl -fsS -X POST "$BASE/trade/execute" \
        -H "Authorization: Bearer $BEARER" \
        -H "Content-Type: application/json" \
        --data '{"symbol":"BTCUSDT","side":"BUY","quantity":0.01,"leverage":10,"dry_run":true}' | jq .
      ;;
    3)
      curl -fsS -H "Authorization: Bearer $BEARER" "$BASE/export/daily" | jq .
      ;;
    4)
      curl -fsS -H "Authorization: Bearer $BEARER" "$BASE/ai/summary" | jq .
      ;;
    5)
      bash scripts/deploy.sh
      ;;
    6)
      echo "Checking health..."
      curl -fsS "$BASE/readyz" && echo "✅ ready OK"
      curl -fsS "$BASE/healthz" || echo "⚠️ may require POST"
      ;;
    0)
      echo "Bye 👋"
      exit 0
      ;;
    *)
      echo "Invalid option"
      ;;
  esac
}

while true; do
  menu
done
