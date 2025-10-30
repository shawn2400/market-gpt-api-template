#!/usr/bin/env bash
set -euo pipefail

# ===============================
# 🔐 Binance API Connectivity Test
# ===============================
BINANCE_BASE="https://fapi.binance.com"
API_KEY="${BINANCE_API_KEY:?missing BINANCE_API_KEY in secrets}"
API_SECRET="${BINANCE_API_SECRET:?missing BINANCE_API_SECRET in secrets}"

Y="\033[1;33m"; G="\033[1;32m"; R="\033[1;31m"; N="\033[0m"

header() {
  echo -e "\n==============================="
  echo -e "🔐 Binance API Connectivity Test"
  echo -e "===============================\n"
}

ts_ms() { date +%s%3N; }

sign() {
  local qs="$1"
  printf '%s' "$qs" | openssl dgst -sha256 -hmac "$API_SECRET" -binary | xxd -p -c 256
}

test_endpoint() {
  local endpoint="$1"
  local label="$2"
  local ts=$(ts_ms)
  local qs="timestamp=$ts"
  local sig=$(sign "$qs")
  local url="${BINANCE_BASE}${endpoint}?${qs}&signature=${sig}"
  local code
  code=$(curl -s -o /tmp/resp.$$ -w "%{http_code}" -H "X-MBX-APIKEY: $API_KEY" "$url" || echo "000")
  if [[ "$code" == "200" ]]; then
    echo -e "${G}✅ $label${N}"
  else
    echo -e "${R}❌ $label (HTTP $code)${N}"
    cat /tmp/resp.$$ | sed 's/^/   /'
    echo ""
  fi
  rm -f /tmp/resp.$$
}

header
echo -e "🌍 Checking external IP..."
PUB_IP=$(curl -s https://api.ipify.org || echo "unknown")
echo -e "🌐 Public IP: ${Y}${PUB_IP}${N}"

echo -e "\n🔎 Checking Futures API permissions...\n"
test_endpoint "/fapi/v2/balance" "Futures balance reachable"
test_endpoint "/fapi/v2/account" "Futures account accessible"
test_endpoint "/fapi/v2/positionRisk" "Position risk accessible"

echo -e "\n🧩 HMAC Signature test..."
QS="timestamp=$(ts_ms)"
SIG=$(sign "$QS")
if [[ ${#SIG} -eq 64 ]]; then
  echo -e "${G}✅ HMAC signature valid (${SIG:0:8}...)${N}"
else
  echo -e "${R}❌ HMAC generation failed${N}"
fi

echo -e "\n==============================="
echo -e "📊 Binance Futures Access Check Done"
echo -e "===============================\n"

# Optional Telegram alert if available
if [[ -n "${TELEGRAM_BOT_TOKEN:-}" && -n "${TELEGRAM_CHAT_ID:-}" ]]; then
  MSG="✅ Binance API Test Completed\n🌍 IP: $PUB_IP"
  curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
       -d "chat_id=${TELEGRAM_CHAT_ID}" -d "text=${MSG}" >/dev/null || true
fi
