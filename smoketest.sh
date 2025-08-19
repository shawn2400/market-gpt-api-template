# שמור בקובץ /app/smoketest.sh
cat > /app/smoketest.sh <<'SH'
#!/bin/bash
set -e

# ====== CONFIG ======
HOST="https://algogpt-docker.onrender.com"
TOKEN="rnd_I7f7QQ6JXu55tuqfORcQKBdlxMPK"
AUTH="Authorization: Bearer ${TOKEN}"

# ====== COLORS ======
OK='\033[0;32mOK\033[0m'
FAIL='\033[0;31mFAIL\033[0m'
HDR='\033[1;36m'
NC='\033[0m'

check() {
  local name="$1" url="$2" method="${3:-GET}" use_auth="${4:-no}"
  local code out
  if [ "$method" = "POST" ]; then
    if [ "$use_auth" = "yes" ]; then
      code=$(curl -sS -o /dev/null -w "%{http_code}" -X POST -H "$AUTH" "$url")
    else
      code=$(curl -sS -o /dev/null -w "%{http_code}" -X POST "$url")
    fi
  else
    if [ "$use_auth" = "yes" ]; then
      code=$(curl -sS -o /dev/null -w "%{http_code}" -H "$AUTH" "$url")
    else
      code=$(curl -sS -o /dev/null -w "%{http_code}" "$url")
    fi
  fi
  if [[ "$code" =~ ^2[0-9]{2}$ ]]; then
    echo -e "[$name] $OK ($code)"
  else
    echo -e "[$name] $FAIL ($code)"
  fi
}

preview() {
  # הדפסה קצרה של גוף תגובה (ללא jq)
  local title="$1" url="$2" use_auth="${3:-no}"
  echo -e "${HDR}== $title ==${NC}"
  if [ "$use_auth" = "yes" ]; then
    curl -sS -H "$AUTH" "$url" | head -c 800; echo
  else
    curl -sS "$url" | head -c 800; echo
  fi
  echo
}

echo -e "${HDR}=== AlgoGPT Smoke Test ===${NC}"

# בריאות כללית
check "Health"                  "$HOST/health"
check "Liveness"                "$HOST/health/live"
check "Strategy Version"        "$HOST/health/strategy-version"

# AI
check "AI Health"               "$HOST/ai/health"
check "AI Manual Scan (BTCUSDT)" "$HOST/ai/manual-scan?symbol=BTCUSDT&interval=15m&limit=200" GET yes

# Grid / Executor
check "Grid Status"             "$HOST/grid/status" GET yes
check "Executor Status"         "$HOST/executor/status" GET yes
check "Executor Start"          "$HOST/executor/start" POST yes
check "Executor Stop"           "$HOST/executor/stop" POST yes

# Scans
check "Symbols Top-Volume"      "$HOST/symbols/top-volume?market=futures&quote=USDT&limit=5" GET yes
check "Scan Top-Volume 15m"     "$HOST/scan/top-volume?market=futures&quote=USDT&limit=5&timeframe=15m" GET yes

# Orderflow (צפוי 404 אם לא ממומש – נציג בתצוגה)
preview "Orderflow Snapshot (BTCUSDT)" "$HOST/orderflow?symbol=BTCUSDT" no

# תצוגות קצרות מועילות
preview "Strategy Version (preview)"   "$HOST/health/strategy-version"
preview "Scan Top-Volume (preview)"    "$HOST/scan/top-volume?market=futures&quote=USDT&limit=5&timeframe=15m" yes
preview "Grid Status (preview)"        "$HOST/grid/status" yes

echo -e "${HDR}=== Smoke test done ===${NC}"
SH

# הרשאות והרצה
chmod +x /app/smoketest.sh
/app/smoketest.sh
