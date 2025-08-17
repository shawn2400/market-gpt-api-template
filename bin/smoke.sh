#!/usr/bin/env bash
set -Eeuo pipefail

BASE="${BASE:-https://algogpt-docker.onrender.com}"
TOKEN="${API_BEARER_TOKEN:-${TOKEN:-}}"

ok=0; fail=0
get(){ code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$1"); echo "GET  $1 -> $code"; [ "$code" = 200 ] && ((ok++)) || ((fail++)); }
get_auth(){ code=$(curl -s -H "Authorization: Bearer $TOKEN" -o /dev/null -w "%{http_code}" --max-time 15 "$1"); echo "GET  $1 -> $code"; [ "$code" = 200 ] && ((ok++)) || ((fail++)); }
post_auth(){ code=$(curl -s -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d "$2" -o /dev/null -w "%{http_code}" --max-time 20 "$1"); echo "POST $1 -> $code"; [ "$code" = 200 ] && ((ok++)) || ((fail++)); }

echo "== Smoke Test $(date -u +%Y-%m-%dT%H:%M:%SZ) BASE=$BASE TOKEN_PRESENT=$( [ -n "$TOKEN" ] && echo yes || echo no ) =="
get "$BASE/"
get "$BASE/metrics"
get "$BASE/scan"               # heartbeat
get "$BASE/scan-info" || true  # alias (יעבוד רק אם שודרג)

if [ -n "$TOKEN" ]; then
  post_auth "$BASE/scan"       '{"symbol":"BTCUSDT","timeframe":"15m","limit":120}'
  post_auth "$BASE/scan/multi" '{"symbols":["BTCUSDT","ETHUSDT"],"timeframe":"15m","limit":200}'
fi

echo "RESULT: OK=$ok FAIL=$fail"
[ "$fail" -eq 0 ]

