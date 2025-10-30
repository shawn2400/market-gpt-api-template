#!/usr/bin/env bash
set -euo pipefail
G="\033[1;32m"; R="\033[1;31m"; Y="\033[1;33m"; N="\033[0m"
BASE="https://fapi.binance.com"
KEY="${BINANCE_API_KEY:?missing BINANCE_API_KEY}"
SEC="${BINANCE_API_SECRET:?missing BINANCE_API_SECRET}"
TG_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
TG_CHAT="${TELEGRAM_CHAT_ID:-}"

say() { echo -e "$1"; }
notify() {
  [ -n "$TG_TOKEN" ] && curl -s -X POST "https://api.telegram.org/bot${TG_TOKEN}/sendMessage" \
   -d "chat_id=${TG_CHAT}" -d "text=$1" >/dev/null || true
}

check_endpoint() {
  local endpoint="$1"
  local params="recvWindow=5000&timestamp=$(date +%s%3N)"
  local sig=$(printf '%s' "$params" | openssl dgst -sha256 -hmac "$SEC" -hex | awk '{print $2}')
  local resp; resp=$(curl -s -w "\n%{http_code}" -H "X-MBX-APIKEY: $KEY" "$BASE$endpoint?$params&signature=$sig")
  local body=$(echo "$resp" | head -1)
  local code=$(echo "$resp" | tail -1)
  echo "$code|$body"
}

say "${Y}🔍 Checking Binance Futures API connectivity...${N}"

read -r code_acc body_acc <<<"$(check_endpoint /fapi/v2/account)"
read -r code_bal body_bal <<<"$(check_endpoint /fapi/v2/balance)"
read -r code_pos body_pos <<<"$(check_endpoint /fapi/v2/positionRisk)"

ok_count=0
if [[ "$code_acc" == *200* ]]; then say "${G}✅ Account OK${N}"; ((ok_count++)); else say "${R}❌ Account check failed${N}"; fi
if [[ "$code_bal" == *200* ]]; then say "${G}✅ Balance OK${N}"; ((ok_count++)); else say "${R}❌ Balance check failed${N}"; fi
if [[ "$code_pos" == *200* ]]; then say "${G}✅ Position Risk OK${N}"; ((ok_count++)); else say "${R}❌ Position Risk check failed${N}"; fi

if [[ "$ok_count" -eq 3 ]]; then
  msg="✅ Binance API OK — Futures connected properly!"
  say "${G}$msg${N}"
  notify "$msg"
else
  msg="⚠️ Binance API issue — check API Key, Secret or IP restrictions."
  say "${R}$msg${N}"
  notify "$msg"
  echo "Details:"
  echo "$body_acc"
  echo "$body_bal"
  echo "$body_pos"
fi
