#!/bin/bash
set -euo pipefail
HOST="${HOST:-https://algogpt-docker.onrender.com}"
TOKEN="${TOKEN:-rnd_I7f7QQ6JXu55tuqfORcQKBdlxMPK}"
AUTH="Authorization: Bearer ${TOKEN}"
NC='\033[0m'; G='\033[0;32m'; R='\033[0;31m'; C='\033[0;36m'
ok(){ echo -e "[$1] ${G}OK${NC} ($2)"; }
ko(){ echo -e "[$1] ${R}FAIL${NC} ($2)"; }
http(){ curl -sS -o /dev/null -w "%{http_code}" "$@"; }
echo -e "${C}=== AlgoGPT Smoke Test ===${NC}"
c=$(http "$HOST/health");                           [[ $c = 200 ]] && ok "Health" $c || ko "Health" $c
c=$(http "$HOST/health/live");                      [[ $c = 200 ]] && ok "Liveness" $c || ko "Liveness" $c
c=$(http "$HOST/health/strategy-version");          [[ $c = 200 ]] && ok "Strategy Version" $c || ko "Strategy Version" $c
c=$(http -H "$AUTH" "$HOST/scan/top-volume?market=futures&quote=USDT&limit=10&timeframe=15m"); [[ $c = 200 ]] && ok "Scan Top-Volume" $c || ko "Scan Top-Volume" $c
c=$(http -H "$AUTH" "$HOST/orderflow/BTCUSDT");     [[ $c = 200 ]] && ok "Orderflow" $c || ko "Orderflow" $c
c=$(http -H "$AUTH" "$HOST/ai/manual-scan?symbol=BTCUSDT&interval=15m&limit=200&compact=1"); [[ $c = 200 ]] && ok "Manual Scan" $c || ko "Manual Scan" $c
echo -e "${C}=== Smoke test done ===${NC}"




