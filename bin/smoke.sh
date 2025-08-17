#!/usr/bin/env bash
set -Eeuo pipefail
BASE="${BASE:-https://algogpt-docker.onrender.com}"
TOKEN="${TOKEN:-rnd_I7f7QQ6JXu55tuqfORcQKBdlxMPK}"
auth=(-H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json")

pp(){ python -m json.tool 2>/dev/null || cat; }

echo "== Smoke @ $BASE (token: ${TOKEN:0:6}…)"
echo "-- GET /";          curl -sS "$BASE/" | pp
echo "-- GET /metrics";   curl -sS "$BASE/metrics" | pp
echo "-- GET /ai/health"; curl -sS "$BASE/ai/health" | pp

echo "-- GET /symbols/top-volume"
TOP=$(curl -sS "${BASE}/symbols/top-volume?market=futures&quote=USDT&limit=12" "${auth[@]}") 
echo "$TOP" | pp
SYMS=$(echo "$TOP" | python - <<'PY'
import sys, json
d=json.load(sys.stdin); print(",".join(d.get("symbols",[])[:10]))
PY
)

echo "-- POST /scan/multi (first 10 top-volume)"
curl -sS -X POST "${BASE}/scan/multi" "${auth[@]}" \
  -d "{\"symbols\":[\"$(echo "$SYMS" | sed 's/,/","/g')\"],\"timeframe\":\"15m\",\"limit\":200}" | pp

echo "-- GET /analytics/correlation"
curl -sS "${BASE}/analytics/correlation?symbols=$(echo "$SYMS")&ref_symbol=BTCUSDT&timeframe=15m&window=200" "${auth[@]}" | pp

echo "-- GET /analytics/macro"; curl -sS "${BASE}/analytics/macro" "${auth[@]}" | pp
echo "-- GET /news/crypto";    curl -sS "${BASE}/news/crypto"  "${auth[@]}" | pp
echo "-- GET /sentiment/summary"; curl -sS "${BASE}/sentiment/summary" "${auth[@]}" | pp

echo "-- POST /eta/time-to-target"
curl -sS -X POST "${BASE}/eta/time-to-target" "${auth[@]}" \
  -d '{"entry":65000,"tp":66000,"sl":64000,"atr":500,"timeframe":"15m"}' | pp

echo "-- POST /decision/best-trades"
curl -sS -X POST "${BASE}/decision/best-trades" "${auth[@]}" -d @- <<'JSON' | pp
{"top_n":5,"diversify_by_symbol":true,"candidates":[
  {"symbol":"BTCUSDT","side":"LONG","quality_score":7.8,"success_pct":58,"eta_minutes":45,"corr_to_btc":1.0},
  {"symbol":"ETHUSDT","side":"SHORT","quality_score":8.9,"success_pct":62,"eta_minutes":35,"corr_to_btc":0.86},
  {"symbol":"BNBUSDT","side":"SHORT","quality_score":7.2,"success_pct":55,"eta_minutes":25,"corr_to_btc":0.78},
  {"symbol":"SOLUSDT","side":"LONG","quality_score":8.1,"success_pct":60,"eta_minutes":20,"corr_to_btc":0.72}
]}
JSON
echo "== DONE =="




