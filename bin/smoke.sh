#!/usr/bin/env bash
set -Eeuo pipefail

BASE="${BASE:-https://algogpt-docker.onrender.com}"
TOKEN="${TOKEN:-${API_BEARER_TOKEN:-}}"

pp(){ python -m json.tool 2>/dev/null || cat; }
hdrs_auth=(-H "Authorization: Bearer ${TOKEN}")
hdrs_json=(-H "Content-Type: application/json")

ts(){ date -u +"%Y-%m-%dT%H:%M:%SZ"; }

echo "== Smoke Test $(ts) BASE=${BASE} TOKEN_PRESENT=$([ -n "${TOKEN}" ] && echo yes || echo no) =="

get(){  # name path [need_auth?]
  local name="$1" path="$2" need_auth="${3:-0}" code body
  if [ "$need_auth" = "1" ] && [ -z "${TOKEN}" ]; then
    echo "-- $name (skip, no TOKEN)"
    return 0
  fi
  echo "-- $name"
  if [ "$need_auth" = "1" ]; then
    curl -sS "${hdrs_auth[@]}" "${BASE}${path}" | pp
    code=$(curl -sS -o /dev/null -w "%{http_code}" "${hdrs_auth[@]}" "${BASE}${path}" || true)
  else
    curl -sS "${BASE}${path}" | pp
    code=$(curl -sS -o /dev/null -w "%{http_code}" "${BASE}${path}" || true)
  fi
  echo "HTTP $code"
}

post(){ # name path data_json need_auth?
  local name="$1" path="$2" data="$3" need_auth="${4:-1}" code
  if [ "$need_auth" = "1" ] && [ -z "${TOKEN}" ]; then
    echo "-- $name (skip, no TOKEN)"
    return 0
  fi
  echo "-- $name"
  if [ "$need_auth" = "1" ]; then
    curl -sS "${hdrs_auth[@]}" "${hdrs_json[@]}" -d "$data" "${BASE}${path}" | pp
    code=$(curl -sS -o /dev/null -w "%{http_code}" "${hdrs_auth[@]}" "${hdrs_json[@]}" -d "$data" "${BASE}${path}" || true)
  else
    curl -sS "${hdrs_json[@]}" -d "$data" "${BASE}${path}" | pp
    code=$(curl -sS -o /dev/null -w "%{http_code}" "${hdrs_json[@]}" -d "$data" "${BASE}${path}" || true)
  fi
  echo "HTTP $code"
}

# ---- Basic ----
get "GET /"                 "/"
get "GET /metrics"          "/metrics"
get "GET /ai/health"        "/ai/health"

# ---- Scan (auth) ----
get "GET /scan"             "/scan" 1
get "GET /scan/top-volume (limit=10)" "/scan/top-volume?limit=10&quote=USDT" 1

post "POST /scan (BTCUSDT)" "/scan" '{"symbol":"BTCUSDT","timeframe":"15m","limit":150}' 1
post "POST /scan/multi (explicit)" "/scan/multi" '{"symbols":["BTCUSDT","ETHUSDT"],"timeframe":"15m","limit":150}' 1
post "POST /scan/multi (top_volume)" "/scan/multi" '{"top_volume":true,"top_limit":10,"quote":"USDT","timeframe":"15m","limit":150}' 1

# ---- AI (auth) ----
post "POST /ai/quality (sample LONG)" "/ai/quality" '{"symbol":"BTCUSDT","side":"LONG","entry":65000,"sl":64000,"tp":66000,"leverage":10,"budget":100}' 1
post "POST /ai-analyze (same engine)" "/ai-analyze" '{"symbol":"BTCUSDT","side":"LONG","entry":65000,"sl":64000,"tp":66000,"leverage":10,"budget":100}' 1
post "POST /ai/eta" "/ai/eta" '{"symbol":"BTCUSDT","timeframe":"15m","entry":65000,"sl":64000,"tp":66000,"limit":200}' 1
post "POST /ai/decision (top_volume picks)" "/ai/decision" '{"top_volume":true,"top_limit":20,"quote":"USDT","timeframe":"15m","limit":150,"max_results":5}' 1

# ---- Trades (auth) ----
post "POST /trade/sltp" "/trade/sltp" '{"symbol":"BTCUSDT","direction":"LONG","entry":65000,"atr":500}' 1
post "POST /trade/execute (dry)" "/trade/execute" '{"symbol":"BTCUSDT","side":"LONG","budget":100,"leverage":10,"entry":65000,"sl":64000,"tp":66000,"dry_run":true}' 1

# ---- Indicators (no auth) ----
get "GET /indicators" "/indicators"
get "GET /indicators/BTCUSDT" "/indicators/BTCUSDT?timeframe=1h&limit=120"

# ---- Market/News/Sentiment (auth; optional providers) ----
post "POST /market/correlation (ETH/BTC)" "/market/correlation" '{"symbols":["ETHUSDT","BTCUSDT"],"timeframe":"1h","limit":200}' 1
get  "GET /macro/overview" "/macro/overview" 1
get  "GET /news/headlines" "/news/headlines?filter=hot" 1
get  "GET /news/analyze"   "/news/analyze" 1
get  "GET /sentiment/summary" "/sentiment/summary" 1

echo "---- DONE ----"



