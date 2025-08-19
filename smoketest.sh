#!/bin/bash
set -e

# ====== CONFIG ======
HOST="https://algogpt-docker.onrender.com"
TOKEN="rnd_I7f7QQ6JXu55tuqfORcQKBdlxMPK"
AUTH="Authorization: Bearer ${TOKEN}"

# ====== COLORS ======
NC='\033[0m'; GREEN='\033[0;32m'; RED='\033[0;31m'; CYAN='\033[0;36m'
pass() { echo -e "[$1] ${GREEN}OK${NC} (200)"; }
fail() { echo -e "[$1] ${RED}FAIL${NC} ($2)"; }

echo -e "${CYAN}=== AlgoGPT Smoke Test ===${NC}"

code=$(curl -sS -o /dev/null -w "%{http_code}" "$HOST/health");                                [[ "$code" == "200" ]] && pass "Health" || fail "Health" "$code"
code=$(curl -sS -o /dev/null -w "%{http_code}" "$HOST/health/live");                           [[ "$code" == "200" ]] && pass "Liveness" || fail "Liveness" "$code"
code=$(curl -sS -o /dev/null -w "%{http_code}" "$HOST/health/strategy-version");               [[ "$code" == "200" ]] && pass "Strategy Version" || fail "Strategy Version" "$code"
code=$(curl -sS -o /dev/null -w "%{http_code}" "$HOST/ai/health");                             [[ "$code" == "200" ]] && pass "AI Health" || fail "AI Health" "$code"

code=$(curl -sS -H "$AUTH" -o /dev/null -w "%{http_code}" "$HOST/ai/manual-scan?symbol=BTCUSDT&interval=15m&limit=200")
[[ "$code" == "200" ]] && pass "AI Manual Scan (BTCUSDT)" || fail "AI Manual Scan (BTCUSDT)" "$code"

code=$(curl -sS -H "$AUTH" -o /dev/null -w "%{http_code}" "$HOST/grid/status");                [[ "$code" == "200" ]] && pass "Grid Status" || fail "Grid Status" "$code"
code=$(curl -sS -H "$AUTH" -o /dev/null -w "%{http_code}" "$HOST/executor/status");            [[ "$code" == "200" ]] && pass "Executor Status" || fail "Executor Status" "$code"
code=$(curl -sS -X POST -H "$AUTH" -o /dev/null -w "%{http_code}" "$HOST/executor/start");     [[ "$code" == "200" ]] && pass "Executor Start" || fail "Executor Start" "$code"
code=$(curl -sS -H "$AUTH" -o /dev/null -w "%{http_code}" "$HOST/executor/status");            [[ "$code" == "200" ]] && pass "Executor Status (after start)" || fail "Executor Status (after start)" "$code"
code=$(curl -sS -X POST -H "$AUTH" -o /dev/null -w "%{http_code}" "$HOST/executor/stop");      [[ "$code" == "200" ]] && pass "Executor Stop" || fail "Executor Stop" "$code"
code=$(curl -sS -H "$AUTH" -o /dev/null -w "%{http_code}" "$HOST/executor/status");            [[ "$code" == "200" ]] && pass "Executor Status (after stop)" || fail "Executor Status (after stop)" "$code"

code=$(curl -sS -H "$AUTH" -o /dev/null -w "%{http_code}" "$HOST/symbols/top-volume?market=futures&quote=USDT&limit=5")
[[ "$code" == "200" ]] && pass "Symbols Top-Volume" || fail "Symbols Top-Volume" "$code"

code=$(curl -sS -H "$AUTH" -o /dev/null -w "%{http_code}" "$HOST/scan/top-volume?market=futures&quote=USDT&limit=5&timeframe=15m")
[[ "$code" == "200" ]] && pass "Scan Top-Volume 15m" || fail "Scan Top-Volume 15m" "$code"

code=$(curl -sS -H "$AUTH" -o /dev/null -w "%{http_code}" "$HOST/orderflow/BTCUSDT")
[[ "$code" == "200" ]] && pass "Orderflow (BTCUSDT)" || fail "Orderflow (BTCUSDT)" "$code"

echo -e "${CYAN}=== Smoke test done ===${NC}"

