#!/bin/bash
HOST="${HOST:-http://localhost:10000}"
TOKEN="${TOKEN:-rnd_I7f7QQ6JXu55tuqfORcQKBdlxMPK}"
AUTH="Authorization: Bearer ${TOKEN}"

NC='\033[0m'
G='\033[0;32m'
R='\033[0;31m'

RESULT_FILE="smoketest_result.json"
echo "{}" > "$RESULT_FILE"  # התחלה נקייה

check() {
  local name="$1"
  local key=$(echo "$name" | tr ' ' '_' | tr '[:upper:]' '[:lower:]')
  local url="$2"
  local method="${3:-GET}"
  local data="$4"

  if [[ "$method" == "POST" ]]; then
    response=$(curl -s -w "|||%{http_code}" -X POST -H "$AUTH" -H "Content-Type: application/json" -d "$data" "$url")
  else
    response=$(curl -s -w "|||%{http_code}" -H "$AUTH" "$url")
  fi

  body=$(echo "$response" | cut -d"|||" -f1)
  code=$(echo "$response" | cut -d"|||" -f2)

  if [[ "$code" == 200 ]]; then
    echo -e "[$name] ${G}OK${NC} ($code)"
  else
    echo -e "[$name] ${R}FAIL${NC} ($code)"
  fi

  # עדכון JSON עם jq (אם קיים) או echo פשוט
  if command -v jq &>/dev/null; then
    tmp=$(mktemp)
    jq --arg key "$key" --argjson body "$body" '. + {($key): $body}' "$RESULT_FILE" > "$tmp" && mv "$tmp" "$RESULT_FILE"
  else
    echo "\"$key\": $body" >> "$RESULT_FILE"
  fi
}

echo "=== AlgoGPT Smoke Test ==="

# --- Health ---
check "Root Status" "$HOST/"
check "Health" "$HOST/health"
check "Live" "$HOST/health/live"

# --- AI ---
check "AI Health" "$HOST/ai/health"

# --- PnL ---
check "PnL Update" "$HOST/pnl/update" "POST" '{"symbol":"BTCUSDT","direction":"LONG","entry":64000,"exit_price":65000,"leverage":5,"qty":0.01}'
check "PnL Daily" "$HOST/pnl/daily"
check "PnL Report" "$HOST/pnl/report"

# --- Risk ---
check "Risk Suggest" "$HOST/risk/suggest" "POST" '{"symbol":"BTCUSDT","budget":100,"leverage":10,"entry":64000,"sl":63000,"tp":66000}'

# --- Indicators ---
check "Indicators Sample" "$HOST/indicators"
check "Indicators Symbol" "$HOST/indicators/BTCUSDT?timeframe=1h&limit=180"

echo "=== Done ==="
echo "📦 JSON saved to $RESULT_FILE"








