#!/usr/bin/env bash
set -euo pipefail

BASE="https://algogpt-docker.onrender.com"
BEARER="${API_BEARER_TOKEN:?set API_BEARER_TOKEN in Replit/Render secrets}"

separator() {
  echo "-------------------------------------------"
}

check_api() {
  echo "🔑 Checking Bearer token..."
  curl -s -w "\nHTTP %{http_code}\n" -H "Authorization: Bearer $BEARER" "$BASE/version" | tee /tmp/version.json
  grep -q '"ok":true' /tmp/version.json && echo "✅ API token valid." || echo "❌ Invalid or mismatched API token."
}

check_binance() {
  echo "🟡 Checking Binance Futures..."
  curl -s https://fapi.binance.com/fapi/v1/ping >/dev/null && echo "✅ Binance reachable." || echo "❌ Binance unreachable!"
}

check_telegram() {
  echo "🤖 Checking Telegram bot..."
  curl -s -H "Authorization: Bearer $BEARER" "$BASE/telegram/status" || echo "⚠️ Telegram endpoint not found."
}

check_render() {
  echo "☁️ Checking Render health..."
  curl -s "$BASE/readyz" >/dev/null && echo "✅ Ready OK." || echo "⚠️ Not ready."
  curl -s "$BASE/healthz" >/dev/null && echo "✅ Health OK." || echo "⚠️ /healthz may require POST."
}

check_trade() {
  echo "💰 Testing dry-run trade..."
  curl -s -X POST "$BASE/trade/execute" \
    -H "Authorization: Bearer $BEARER" \
    -H "Content-Type: application/json" \
    --data '{"symbol":"BTCUSDT","side":"BUY","quantity":0.01,"leverage":10,"dry_run":true}' | tee /tmp/trade_test.json
  grep -q '"ok":true' /tmp/trade_test.json && echo "✅ Trade endpoint OK." || echo "⚠️ Trade failed (check Futures perms)."
}

check_metrics() {
  echo "📊 Fetching metrics..."
  curl -s -H "Authorization: Bearer $BEARER" "$BASE/metrics" | head -20
}

menu() {
  echo ""
  echo "=============================="
  echo "   🧠 AlgoGPT System Checker"
  echo "=============================="
  echo "1) 🔑 Check API Token"
  echo "2) 🟡 Check Binance Futures"
  echo "3) 🤖 Check Telegram Bot"
  echo "4) ☁️ Check Render Health"
  echo "5) 💰 Test Trade (dry-run)"
  echo "6) 📊 Show System Metrics"
  echo "7) 🚀 Run FULL Check (All)"
  echo "0) ❌ Exit"
  echo "=============================="
  read -rp "Select: " choice

  case $choice in
    1) check_api ;;
    2) check_binance ;;
    3) check_telegram ;;
    4) check_render ;;
    5) check_trade ;;
    6) check_metrics ;;
    7)
      separator; check_api
      separator; check_binance
      separator; check_telegram
      separator; check_render
      separator; check_trade
      separator; check_metrics
      separator
      echo "✅ FULL CHECK COMPLETE"
      ;;
    0)
      echo "👋 Bye."
      exit 0
      ;;
    *)
      echo "❌ Invalid option"
      ;;
  esac
}

while true; do
  menu
done

