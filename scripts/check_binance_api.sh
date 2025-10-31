#!/usr/bin/env bash
set -euo pipefail

# === CONFIG ===
G="\033[1;32m"; R="\033[1;31m"; Y="\033[1;33m"; C="\033[1;36m"; N="\033[0m"
API_KEY="${BINANCE_API_KEY:?missing key}"
API_SECRET="${BINANCE_API_SECRET:?missing secret}"
TG_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
TG_CHAT="${TELEGRAM_CHAT_ID:-}"

BASE_SPOT="https://api.binance.com"
BASE_FUT="https://fapi.binance.com"

send_tg() {
  local msg="$1"
  if [[ -n "$TG_TOKEN" && -n "$TG_CHAT" ]]; then
    curl -s -X POST "https://api.telegram.org/bot${TG_TOKEN}/sendMessage" \
      -d "chat_id=${TG_CHAT}" -d "text=${msg}" -d "parse_mode=HTML" >/dev/null || true
  fi
}

# === Helper: sign query with HMAC ===
sign_query() {
  local query="$1"
  printf '%s' "$query" | openssl dgst -sha256 -hmac "$API_SECRET" -hex | sed 's/^.* //'
}

check_endpoint() {
  local base="$1" endpoint="$2" label="$3"
  local start=$(date +%s%3N)
  local query="timestamp=$start"
  local sig=$(sign_query "$query")
  local res=$(curl -s -w "\n%{http_code}" -H "X-MBX-APIKEY: $API_KEY" "$base$endpoint?$query&signature=$sig")
  local body=$(echo "$res" | head -n1)
  local code=$(echo "$res" | tail -n1)
  local end=$(date +%s%3N)
  local latency=$((end-start))
  if [[ "$code" == "200" ]]; then
    echo -e "${G}✅ $label OK${N} (${latency}ms)"
  else
    local msg=$(echo "$body" | jq -r '.msg // empty' 2>/dev/null || echo "")
    echo -e "${R}❌ $label failed (${code})${N} ${Y}${msg}${N}"
    send_tg "⚠️ <b>Binance $label Error</b> (${code})\n<code>${msg}</code>\nLatency: ${latency}ms"
  fi
}

echo -e "${C}🔍 Checking Binance API connectivity...${N}"
echo "------------------------------------"

# === Futures checks ===
check_endpoint "$BASE_FUT" "/fapi/v2/balance" "Futures Balance"
check_endpoint "$BASE_FUT" "/fapi/v2/account" "Futures Account"
check_endpoint "$BASE_FUT" "/fapi/v2/positionRisk" "Futures PositionRisk"

# === Spot checks ===
check_endpoint "$BASE_SPOT" "/api/v3/account" "Spot Account"
check_endpoint "$BASE_SPOT" "/api/v3/openOrders" "Spot Open Orders"

# === Spot USDT Balance ===
echo -e "${C}💰 Fetching Spot USDT balance...${N}"
query="timestamp=$(date +%s%3N)"
sig=$(sign_query "$query")
balance_json=$(curl -s -H "X-MBX-APIKEY: $API_KEY" "$BASE_SPOT/api/v3/account?$query&signature=$sig")
usdt=$(echo "$balance_json" | jq -r '.balances[] | select(.asset=="USDT") | .free' 2>/dev/null || echo "")
if [[ -n "$usdt" ]]; then
  echo -e "${G}✅ USDT Free Balance:${N} ${Y}${usdt}${N}"
else
  echo -e "${R}❌ Could not retrieve USDT balance${N}"
fi

echo -e "${C}------------------------------------"
echo -e "${G}✅ Binance connectivity test finished.${N}"
