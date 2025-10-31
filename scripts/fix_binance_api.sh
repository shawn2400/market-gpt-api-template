#!/bin/bash
set -euo pipefail
G="\033[1;32m"; R="\033[1;31m"; Y="\033[1;33m"; N="\033[0m"

echo -e "${Y}🔍 Checking Binance API connectivity...${N}"
if [ -z "${BINANCE_API_KEY:-}" ] || [ -z "${BINANCE_API_SECRET:-}" ]; then
  echo -e "${R}❌ Missing BINANCE_API_KEY or BINANCE_API_SECRET${N}"
  exit 1
fi

TS=$(date +%s%3N)
QS="timestamp=$TS"
SIG=$(echo -n "$QS" | openssl dgst -sha256 -hmac "$BINANCE_API_SECRET" -hex | sed 's/^.* //')
URL="https://fapi.binance.com/fapi/v2/account?$QS&signature=$SIG"

RESP=$(curl -s -w "\nHTTP %{http_code}\n" -H "X-MBX-APIKEY: $BINANCE_API_KEY" "$URL")
CODE=$(echo "$RESP" | tail -n1 | awk '{print $2}')
BODY=$(echo "$RESP" | head -n1)

if [[ "$CODE" == "200" ]]; then
  echo -e "${G}✅ Binance Futures API OK${N}"
elif [[ "$BODY" == *"-2015"* ]]; then
  echo -e "${R}❌ Invalid API-key, IP, or permissions for action${N}"
  echo -e "${Y}➡️ Check that:${N}\n  ☑️ Enable Reading\n  ☑️ Enable Futures\n  ☑️ IP = Unrestricted\n"
else
  echo -e "${R}⚠️ Unexpected response (${CODE})${N}"
  echo "$BODY"
fi
