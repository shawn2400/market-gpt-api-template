#!/usr/bin/env bash
# algo_helpers.sh — helper CLI for AlgoGPT FastAPI (no jq)
# טעינה:  source /app/algo_helpers.sh
# דרישות: curl, python3

set -euo pipefail

# ====== CONFIG ======
ALGOGPT_HOST_DEFAULT="http://127.0.0.1:10000"
ALGOGPT_HOST="${ALGOGPT_HOST:-${WEBHOOK_HOST:-${PUBLIC_HOST:-$ALGOGPT_HOST_DEFAULT}}}"
API_BEARER_TOKEN="${API_BEARER_TOKEN:-${API_TOKEN:-}}"
WATCHLIST="${WATCHLIST:-BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,NEARUSDT}"

# ====== INTERNAL ======
_need() { command -v "$1" >/dev/null 2>&1 || { echo "missing dependency: $1"; exit 1; }; }
_need curl
_need python3

_auth_header() {
  if [[ -n "${API_BEARER_TOKEN:-}" ]]; then
    printf "Authorization: Bearer %s" "$API_BEARER_TOKEN"
  fi
}

_json_escape() {
  # מקבל stdin, מחזיר מחרוזת JSON-escaped בודדת
  python3 - <<'PY'
import json, sys
print(json.dumps(sys.stdin.read()))
PY
}

_now_utc() { date -u +%Y-%m-%dT%H:%M:%SZ; }

# הדפסה פשוטה של תגובת השרת כמו שהיא (אין jq)
_show() { cat; }

# ====== INFO ======
algoinfo() {
  cat <<EOF
Algo Helpers (no-jq)
--------------------
HOST: ${ALGOGPT_HOST}
TOKEN set: $([[ -n "${API_BEARER_TOKEN:-}" ]] && echo yes || echo no)

דוגמאות:
  mk_ticket BTCUSDT BUY 0.5 15 "[mode: HYBRID] test" --tp1 70000 --sl 61000
  approve <ticket_id>
  reject  <ticket_id>
  manage_once BTCUSDT
EOF
}

pick_symbol() {
  local idx="${1:-}"
  IFS=',' read -r -a arr <<< "$WATCHLIST"
  local n="${#arr[@]}"
  if [[ -z "$idx" ]]; then idx=$(( RANDOM % n )); fi
  echo "${arr[$idx]}"
}

# ====== MK_TICKET ======
# שימוש: mk_ticket <SYMBOL> <BUY|SELL> <QTY> <LEV> [NOTE]
#        [--tp1 P] [--tp2 P] [--tp3 P] [--sl P] [--splits "0.3,0.3,0.4"] [--budget USD]
mk_ticket() {
  [[ $# -lt 4 ]] && { echo "usage: mk_ticket SYMBOL BUY|SELL QTY LEV [NOTE] [--tp1 P] [--tp2 P] [--tp3 P] [--sl P] [--splits \"0.3,0.3,0.4\"] [--budget USD]"; return 2; }
  local symbol="$1"; shift
  local side="$1"; shift
  local qty="$1"; shift
  local lev="$1"; shift

  local note=""
  if [[ $# -gt 0 && "$1" != --* ]]; then
    note="$1"; shift
  fi

  local tp1="" tp2="" tp3="" sl="" splits="" budget=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --tp1) tp1="$2"; shift 2;;
      --tp2) tp2="$2"; shift 2;;
      --tp3) tp3="$2"; shift 2;;
      --sl) sl="$2"; shift 2;;
      --splits) splits="$2"; shift 2;;
      --budget) budget="$2"; shift 2;;
      *) echo "unknown flag: $1"; return 2;;
    esac
  done

  # נבנה JSON בצורה בטוחה עם python
  local payload
  payload="$(python3 - "$symbol" "$side" "$qty" "$lev" "$note" "$tp1" "$tp2" "$tp3" "$sl" "$splits" "$budget" <<'PY'
import json, sys
symbol, side, qty, lev, note, tp1, tp2, tp3, sl, splits, budget = sys.argv[1:]
def fnum(x):
    try:
        return None if (x=="" or x.lower()=="null") else float(x)
    except Exception:
        return None
def farr(s):
    if not s: return None
    try:
        return [float(x) for x in s.split(",") if x.strip()]
    except Exception:
        return None
obj = {
  "symbol": symbol.upper(),
  "side": side.upper(),
  "qty": float(qty),
  "leverage": int(float(lev)),
  "note": note,
  "tp1": fnum(tp1),
  "tp2": fnum(tp2),
  "tp3": fnum(tp3),
  "sl":  fnum(sl),
  "tp_splits": farr(splits),
  "budget": fnum(budget) or 0.0,
  "expiry_ts": None
}
print(json.dumps(obj,separators=(",",":")))
PY
)"

  curl -sS -X POST "${ALGOGPT_HOST}/ops/ticket" \
    -H "Content-Type: application/json" \
    -H "$(_auth_header)" \
    -d "$payload" | _show
}

# ====== APPROVE / REJECT ======
approve() {
  [[ $# -lt 1 ]] && { echo "usage: approve <TICKET_ID>"; return 2; }
  local tid="$1"
  curl -sS -G "${ALGOGPT_HOST}/ops/approve" \
    -H "$(_auth_header)" \
    --data-urlencode "ticket_id=${tid}" | _show
}

reject() {
  [[ $# -lt 1 ]] && { echo "usage: reject <TICKET_ID>"; return 2; }
  local tid="$1"
  curl -sS -G "${ALGOGPT_HOST}/ops/reject" \
    -H "$(_auth_header)" \
    --data-urlencode "ticket_id=${tid}" | _show
}

# ====== MANAGE_ONCE ======
# שימוש: manage_once <SYMBOL> [--offset_bps 5] [--pcts "4,8,16"] [--splits "0.3,0.3,0.4"] [--atr_mult 1.6]
manage_once() {
  [[ $# -lt 1 ]] && { echo "usage: manage_once SYMBOL [--offset_bps 5] [--pcts \"4,8,16\"] [--splits \"0.3,0.3,0.4\"] [--atr_mult 1.6]"; return 2; }
  local symbol="$1"; shift || true
  local offset_bps="" pcts="" splits="" atr_mult=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --offset_bps) offset_bps="$2"; shift 2;;
      --pcts) pcts="$2"; shift 2;;
      --splits) splits="$2"; shift 2;;
      --atr_mult) atr_mult="$2"; shift 2;;
      *) echo "unknown flag: $1"; return 2;;
    esac
  done

  local payload
  payload="$(python3 - "$symbol" "$offset_bps" "$pcts" "$splits" "$atr_mult" <<'PY'
import json, sys
symbol, offset_bps, pcts, splits, atr_mult = sys.argv[1:]
def fnum(x):
    try:
        return None if (x=="" or x.lower()=="null") else float(x)
    except Exception:
        return None
def farr(s):
    if not s: return None
    try:
        return [float(x) for x in s.split(",") if x.strip()]
    except Exception:
        return None
obj = {
  "symbol": symbol.upper(),
  "offset_bps": None if offset_bps=="" else int(float(offset_bps)),
  "pcts": farr(pcts),
  "splits": farr(splits),
  "atr_mult": fnum(atr_mult)
}
print(json.dumps(obj,separators=(",",":")))
PY
)"

  curl -sS -X POST "${ALGOGPT_HOST}/manage-once" \
    -H "Content-Type: application/json" \
    -H "$(_auth_header)" \
    -d "$payload" | _show
}

# ====== QUICK DEMO (ללא jq) ======
demo_mk_and_approve() {
  local sym="$(pick_symbol)"
  echo "[$(_now_utc)] creating ticket on ${sym}…"
  local out
  out="$(mk_ticket "$sym" BUY 0.5 15 "[mode: HYBRID] demo from CLI" --tp1 999999 --sl 1 || true)"
  echo "$out"

  # חילוץ ticket_id בלי jq — בעזרת grep/sed פשוט
  local tid
  tid="$(printf "%s" "$out" | sed -n 's/.*"ticket_id":"\([^"]*\)".*/\1/p' | head -n1)"
  if [[ -z "$tid" ]]; then
    echo "could not parse ticket_id from response" >&2
    return 1
  fi
  echo "[$(_now_utc)] approving ${tid}…"
  approve "$tid"
}

# ====== UI HELPERS ======
pending_url() { echo "${ALGOGPT_HOST%/}/ops/ui/pending"; }
ticket_url()  { [[ $# -lt 1 ]] && { echo "usage: ticket_url <TICKET_ID>"; return 2; }; echo "${ALGOGPT_HOST%/}/ops/ui/ticket?ticket_id=$1"; }

# EOF
