cat > algo_helpers.sh <<'BASH'
# ======= algo_helpers.sh =======

urlenc() {
  python3 - <<'PY' <<< "${1:-}"
import sys, urllib.parse
print(urllib.parse.quote(sys.stdin.read().strip(), safe=''))
PY
}

pick_symbol() {
  local HOST="${1:?usage: pick_symbol HOST}"
  python3 - <<'PY' < <(curl -sS "$HOST/topk?limit=25&min_score=6.0")
import sys, json
arr=json.load(sys.stdin)
print(next(s for s in arr if s.endswith('USDT')))
PY
}

mk_ticket() {
  local HOST="${1:?usage: mk_ticket HOST TOK SYMBOL SIDE [BUDGET] [LEVERAGE]}"
  local TOK="${2:?}"
  local SYMBOL="${3:?}"
  local SIDE="${4:?}"      # BUY/SELL
  local BUDGET="${5:-150}"
  local LEV="${6:-20}"

  local TID="T_$(date +%s)"
  local PAYLOAD
  PAYLOAD=$(cat <<JSON
{"ticket_id":"$TID","symbol":"$SYMBOL","side":"$SIDE","reduce_only":false,
 "note":"[mode: MARKET]","leverage":$LEV,"budget":$BUDGET}
JSON
)
  echo "↳ יצירת טיקט: $TID ($SYMBOL $SIDE, lev=$LEV, budget=$BUDGET)"
  local R
  R=$(curl -sS -X POST -H "Authorization: Bearer $TOK" -H "Content-Type: application/json" \
        -d "$PAYLOAD" "$HOST/ops/ticket")
  echo "$R"

  local TID_ENC
  TID_ENC="$(urlenc "$TID")"
  echo "אישור (שתי הצורות):"
  echo "  $HOST/ops/approve?id=$TID_ENC"
  echo "  $HOST/ops/approve?ticket_id=$TID_ENC"

  printf "%s" "$TID"
}

approve() {
  local HOST="${1:?usage: approve HOST TOK ID}"
  local TOK="${2:?}"
  local ID_RAW="${3:?}"
  local ID_ENC
  ID_ENC="$(urlenc "$ID_RAW")"

  local R
  R=$(curl -sS -H "Authorization: Bearer $TOK" "$HOST/ops/approve?id=$ID_ENC")
  echo "$R" | grep -q '"ok":true' && { echo "✔ אושר עם id="; echo "$R"; return 0; }

  R=$(curl -sS -H "Authorization: Bearer $TOK" "$HOST/ops/approve?ticket_id=$ID_ENC")
  echo "$R"
}

manage_once() {
  local HOST="${1:?usage: manage_once HOST TOK SYMBOL}"
  local TOK="${2:?}"
  local SYMBOL="${3:?}"
  curl -sS -X POST -H "Authorization: Bearer $TOK" -H "Content-Type: application/json" \
    -d '{"symbol":"'"$SYMBOL"'"}' "$HOST/manage-once"
}

manage_loop() {
  local HOST="${1:?usage: manage_loop HOST TOK SYMBOL [INTERVAL_SEC]"}; shift
  local TOK="${1:?}"; shift
  local SYMBOL="${1:?}"; shift
  local INTERVAL="${1:-20}"
  echo "ניהול דינמי פעיל ($SYMBOL, כל $INTERVAL שניות). עצירה עם Ctrl+C."
  while true; do
    local OUT
    OUT=$(manage_once "$HOST" "$TOK" "$SYMBOL")
    echo "[$(date +%H:%M:%S)] $OUT"
    sleep "$INTERVAL"
  done
}
# ======= /algo_helpers.sh =======
BASH

# טען לפגישה הנוכחית:
source algo_helpers.sh
