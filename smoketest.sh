#!/bin/bash
set -euo pipefail

# --- הגדרות בסיס ---
HOST="${HOST:-http://localhost:10000}"
TOKEN="${TOKEN:-rnd_I7f7QQ6JXu55tuqfORcQKBdlxMPK}"
AUTH="Authorization: Bearer ${TOKEN}"

# --- צבעים ---
NC='\033[0m'
G='\033[0;32m'
R='\033[0;31m'
C='\033[0;36m'

# --- פונקציית קריאה ל־API ---
http() {
  curl -sS -o /dev/null -w "%{http_code}" -H "$AUTH" "$@"
}

# --- פונקציית בדיקה צבעונית ---
check() {
  local name="$1"
  local url="$2"
  local method="${3:-GET}"
  local data="${4:-}"

  local code
  if [[ "$method" == "POST" ]]; then
    code=$(curl -sS -o /dev/null -w "%{http_code}" -X POST -H "$AUTH" -H "Content-Type: application/json" -d "$data" "$url")
  else
    code=$(http "$url")
  fi

  if [[ $code == 200 ]]; then
    echo -e "[$name] ${G}OK${NC} ($code)"
  else
    echo -e "[$name] ${R}FAIL${NC} ($code)"
  fi

  echo "\"$name\": $code," >> results.tmp
}

# --- התחלת טסט ---
echo -e "${C}=== AlgoGPT Full System Check ===${NC}"
rm -f results.tmp

# --- Config & Health ---
check "Root Status"       "$HOST/"
check "Metrics"           "$HOST/metrics"
check "Routes"            "$HOST/__routes"
check "Health"            "$HOST/health"
check "AI Health"         "$HOST/ai/health"

# --- Grid ---
check "Grid Status"       "$HOST/grid/status"

# --- Scan ---
check "Scan Info"         "$HOST/scan/info"
check "Scan (BTCUSDT)"    "$HOST/scan?symbols=BTCUSDT&interval=15m"

# --- AI ---
check "AI Quality"        "$HOST/ai/quality" "POST" '{"symbol":"BTCUSDT","side":"LONG","entry":42000,"sl":41500,"tp":44000,"leverage":10,"budget":100}'

# --- Trades ---
check "Open Trade"        "$HOST/trade" "POST" '{"symbol":"BTCUSDT","side":"LONG","entry":42000,"sl":41500,"tp":44000,"leverage":10,"budget":50}'
check "Get Trade"         "$HOST/trade/TEST-123"
check "Close Trade"       "$HOST/trade/TEST-123" "DELETE"

# --- Backtest ---
check "Run Backtest"      "$HOST/backtest" "POST" '{"symbol":"BTCUSDT","side":"LONG","interval":"15m","lookback_days":30,"leverage":5}'
check "Backtest Status"   "$HOST/backtest/status/BTCUSDT"

echo -e "${C}=== System check done ===${NC}"

# --- יצירת JSON מסכם ---
status="OK"
grep -q "FAIL" results.tmp && status="FAIL"

cat <<EOF > smoketest_result.json
{
  "timestamp": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
  "host": "$HOST",
  "token": "$TOKEN",
  "results": {
$(sed '$ s/,$//' results.tmp)
  },
  "status": "$status"
}
EOF
rm -f results.tmp

echo -e "📦 JSON saved to ${G}smoketest_result.json${NC}"






