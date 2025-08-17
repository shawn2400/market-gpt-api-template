#!/usr/bin/env bash
set -Eeuo pipefail

BASE="${BASE:-https://algogpt-docker.onrender.com}"
TOKEN="${API_BEARER_TOKEN:-${TOKEN:-}}"

ok=0; fail=0
inc_ok(){ ok=$((ok+1)); return 0; }
inc_fail(){ fail=$((fail+1)); return 0; }

get(){ local url="$1" name="${2:-GET $1}" code
  code=$(curl -sS -o /dev/null -w "%{http_code}" --max-time 10 "$url") || code="CURLE"
  if [ "$code" = 200 ]; then echo "✅ $name -> 200"; inc_ok; else echo "❌ $name -> $code"; inc_fail; fi
  return 0
}

post_auth(){ local url="$1" body="$2" name="${3:-POST $1}" code
  code=$(curl -sS -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
              -d "$body" -o /dev/null -w "%{http_code}" --max-time 20 "$url") || code="CURLE"
  if [ "$code" = 200 ]; then echo "✅ $name -> 200"; inc_ok; else echo "❌ $name -> $code"; inc_fail; fi
  return 0
}

echo "== Smoke Test $(date -u +%Y-%m-%dT%H:%M:%SZ) BASE=$BASE TOKEN_PRESENT=$( [ -n "$TOKEN" ] && echo yes || echo no ) =="

get "$BASE/"        "GET /"
get "$BASE/metrics" "GET /metrics"

# /scan heartbeat: נסה בלי טוקן, אם צריך – עם טוקן
code=$(curl -sS -o /tmp/.scan -w "%{http_code}" --max-time 10 "$BASE/scan") || code="CURLE"
if [ "$code" = 200 ] && grep -q '"ok":true' /tmp/.scan; then
  echo "✅ GET /scan (open) -> 200 & ok:true"; inc_ok
else
  code=$(curl -sS -H "Authorization: Bearer $TOKEN" -o /tmp/.scan -w "%{http_code}" --max-time 10 "$BASE/scan") || code="CURLE"
  if [ "$code" = 200 ] && grep -q '"ok":true' /tmp/.scan; then
    echo "✅ GET /scan (auth) -> 200 & ok:true"; inc_ok
  else
    echo "❌ GET /scan -> $code"; inc_fail
  fi
fi

# מוגנים
if [ -n "$TOKEN" ]; then
  post_auth "$BASE/scan"       '{"symbol":"BTCUSDT","timeframe":"15m","limit":120}' "POST /scan"
  post_auth "$BASE/scan/multi" '{"symbols":["BTCUSDT","ETHUSDT"],"timeframe":"15m","limit":200}' "POST /scan/multi"
else
  echo "⚠️ TOKEN not set; skipping protected endpoints"
fi

echo "RESULT: OK=$ok FAIL=$fail"
[ "$fail" -eq 0 ]


