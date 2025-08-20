#!/bin/bash
HOST="${HOST:-http://localhost:10000}"
TOKEN="${TOKEN:-rnd_I7f7QQ6JXu55tuqfORcQKBdlxMPK}"
AUTH="Authorization: Bearer ${TOKEN}"

NC='\033[0m'
G='\033[0;32m'
R='\033[0;31m'

check() {
  local name="$1"
  local url="$2"
  local method="${3:-GET}"
  local data="$4"

  if [[ "$method" == "POST" ]]; then
    code=$(curl -s -o /dev/null -w "%{http_code}" -X POST -H "$AUTH" -H "Content-Type: application/json" -d "$data" "$url")
  else
    code=$(curl -s -o /dev/null -w "%{http_code}" -H "$AUTH" "$url")
  fi

  if [[ "$code" == 200 ]]; then
    echo -e "[$name] ${G}OK${NC} ($code)"
  else
    echo -e "[$name] ${R}FAIL${NC} ($code)"
  fi
}

echo "=== AlgoGPT Smoke Test ==="

# בריאות
check "Root Status" "$HOST/"
check "Health" "$HOST/health"
check "Live" "$HOST/health/live"

# AI
check "AI Health" "$HOST/ai/health"

# 🔹 PnL
check "PnL Update" "$HOST/pnl/update" "POST" '{"symbol":"BTCUSDT","direction":"LONG","entry":64000,"exit_price":65000,"leverage":5,"qty":0.01}'
check "PnL Daily" "$HOST/pnl/daily"
check "PnL Report" "$HOST/pnl/report"

echo "=== Done ==="







