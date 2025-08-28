#!/usr/bin/env bash
set -Eeuo pipefail

HOST="${1:-http://127.0.0.1:10000}"
TOKEN="${2:-dev_token}"
AUTH="Authorization: Bearer ${TOKEN}"

G='\033[0;32m'; R='\033[0;31m'; Y='\033[1;33m'; N='\033[0m'
ok()   { echo -e "${G}OK${N}  - $1"; }
warn() { echo -e "${Y}WARN${N}- $1"; }
fail() { echo -e "${R}FAIL${N}- $1"; exit 1; }

echo "=== 🚀 Smoke: ${HOST} ==="

# 1) Core health (no auth)
curl -fsS "${HOST}/health" >/dev/null && ok "/health" || fail "/health"

# 2) Full health (no auth)
if curl -fsS "${HOST}/health_full" | jq . >/dev/null 2>&1; then
  ok "/health_full"
else
  warn "/health_full (no jq or endpoint missing)"
fi

# 3) Auth-protected ping (market route לדוגמה)
if curl -fsS -H "${AUTH}" "${HOST}/market/ping" >/dev/null 2>&1; then
  ok "market/ping (auth)"
else
  warn "market/ping (auth)"
fi

# 4) Binance sanity (account via backend route אם קיים)
if curl -fsS -H "${AUTH}" "${HOST}/binance/status" | jq . >/dev/null 2>&1; then
  ok "/binance/status"
else
  warn "/binance/status (missing route or no jq)"
fi

echo "=== ✅ Smoke finished ==="
