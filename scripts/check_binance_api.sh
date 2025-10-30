#!/usr/bin/env bash
set -euo pipefail

# === CONFIG ===
<<<<<<< HEAD
G="\033[1;32m"; R="\033[1;31m"; Y="\033[1;33m"; C="\033[1;36m"; N="\033[0m"
=======
G="\033[1;32m"; R="\033[1;31m"; Y="\033[1;33m"; N="\033[0m"
>>>>>>> a48ff12 (Add script to monitor Binance API endpoints and send Telegram alerts)
API_KEY="${BINANCE_API_KEY:?missing key}"
API_SECRET="${BINANCE_API_SECRET:?missing secret}"
TG_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
TG_CHAT="${TELEGRAM_CHAT_ID:-}"

<<<<<<< HEAD
BASE_SPOT="https://api.binance.com"
=======
>>>>>>> a48ff12 (Add script to monitor Binance API endpoints and send Telegram alerts)
BASE_FUT="https://fapi.binance.com"

send_tg() {
  local msg="$1"
  if [[ -n "$TG_TOKEN" && -n "$TG_CHAT" ]]; then
    curl -s -X POST "https://api.telegram.org/bot${TG_TOKEN}/sendMessage" \
      -d "chat_id=${TG_CHAT}" -d "text=${msg}" -d "parse_mode=HTML" >/dev/null || true
  fi
}

<<<<<<< HEAD
=======
# === Helper: sign query with HMAC ===
>>>>>>> a48ff12 (Add script to monitor Binance API endpoints and send Telegram alerts)
sign_query() {
  local query="$1"
  printf '%s' "$query" | openssl dgst -sha256 -hmac "$API_SECRET" -hex | sed 's/^.* //'
}

check_endpoint() {
<<<<<<< HEAD
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
=======
  local endpoint="$1"
  local query="timestamp=$(($(date +%s%3N)))"
  local sig
  sig=$(sign_query "$query")
  local res
  res=$(curl -s -w "\n%{http_code}" -H "X-MBX-APIKEY: $API_KEY" "$BASE_FUT$endpoint?$query&signature=$sig")
  local body http_code
  body=$(echo "$res" | head -n1)
  http_code=$(echo "$res" | tail -n1)
  echo "$body" | grep -q 'code' && echo "$body" | jq -r '.msg' 2>/dev/null || true
  echo "$http_code"
}

echo -e "${Y}🔍 Checking Binance Futures connectivity...${N}"

# === Step 1: Check balance endpoint ===
code=$(check_endpoint "/fapi/v2/balance")
if [[ "$code" == "200" ]]; then
  echo -e "${G}✅ Balance endpoint OK${N}"
else
  echo -e "${R}❌ Balance check failed (${code})${N}"
  send_tg "⚠️ <b>Binance API Error</b>: /fapi/v2/balance failed (${code})"
fi

# === Step 2: Check account info ===
code=$(check_endpoint "/fapi/v2/account")
if [[ "$code" == "200" ]]; then
  echo -e "${G}✅ Account endpoint OK${N}"
else
  echo -e "${R}❌ Account check failed (${code})${N}"
  send_tg "⚠️ <b>Binance API Error</b>: /fapi/v2/account failed (${code})"
fi

# === Step 3: Check position risk ===
code=$(check_endpoint "/fapi/v2/positionRisk")
if [[ "$code" == "200" ]]; then
  echo -e "${G}✅ PositionRisk OK${N}"
else
  echo -e "${R}❌ PositionRisk failed (${code})${N}"
  send_tg "⚠️ <b>Binance API Error</b>: /fapi/v2/positionRisk failed (${code})"
fi

echo -e "${Y}⏳ Done.${N}"
>>>>>>> a48ff12 (Add script to monitor Binance API endpoints and send Telegram alerts)
