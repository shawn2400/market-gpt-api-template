cat >/app/safe_ops.sh <<'BASH'
#!/usr/bin/env bash
set -euo pipefail

: "${PUBLIC_HOST:?need PUBLIC_HOST}"
: "${API_BEARER_TOKEN:?need API_BEARER_TOKEN}"
: "${OPS_SIGN_SECRET:?need OPS_SIGN_SECRET}"

BASE="$PUBLIC_HOST"

canon_json() {
  # מקבל JSON בכל צורה, פולט JSON קומפקטי ממויין מפתחות (כמו בצד השרת)
  python3 - "$@" <<'PY'
import sys,json
s=sys.stdin.read()
try:
  obj=json.loads(s)
except Exception as e:
  print(s.strip())
  sys.exit(0)
print(json.dumps(obj, separators=(",",":"), sort_keys=True))
PY
}

_sign_post() {
  local path="$1"; shift
  local body="$1"; shift || true

  # קנוניזציה של ה-JSON (חשוב! תואם לשרת)
  local body_canon
  body_canon="$(printf '%s' "$body" | canon_json)"

  local ts nonce payload sig
  ts=$(date +%s)
  nonce=$(cat /proc/sys/kernel/random/uuid)
  payload=$'POST\n'"$path"$'\n'"$body_canon"$'\n'"$ts"$'\n'"$nonce"

  sig=$(printf '%s' "$payload" \
        | openssl dgst -sha256 -hmac "$OPS_SIGN_SECRET" -r \
        | awk '{print $1}')

  curl -sS -X POST "$BASE$path" \
    -H "Authorization: Bearer $API_BEARER_TOKEN" \
    -H "Content-Type: application/json" \
    -H "X-Timestamp: $ts" \
    -H "X-TS: $ts" \
    -H "X-Nonce: $nonce" \
    -H "X-Signature: $sig" \
    --data-binary "$body_canon"
}

_post_bearer() {
  local path="$1"; shift
  local body="${1:-{}}"
  curl -sS -X POST "$BASE$path" \
    -H "Authorization: Bearer $API_BEARER_TOKEN" \
    -H "Content-Type: application/json" \
    --data-binary "$body"
}

_usage() {
  cat <<'HLP'
usage:
  manage-once-lite SYMBOL
  be SYMBOL [OFFSET_BPS]
  trail SYMBOL [CALLBACK_RATE|auto] [ATR_MULT]
  trail-off SYMBOL
  tp-one SYMBOL (--price PX | --pct PCT)
  tp-ladder SYMBOL [PCTS_CSV] [SPLITS_CSV]
  tp-cancel SYMBOL
  sl-move SYMBOL PRICE
  close SYMBOL [FRACTION 0..1]
  status SYMBOL
  auto-start ["SYM1,SYM2"] [EVERY_SEC]
  auto-stop
  open-top BUDGET_USD LEVERAGE [long|short|auto|auto_up|auto_down] [MARGIN_TYPE] [SYMBOL?]
HLP
}

cmd="${1:-help}"; shift || true

case "$cmd" in
  help|-h|--help) _usage; exit 0 ;;

  manage-once-lite)
    sym="${1:?need SYMBOL}"
    # גרסה ללא חתימה (אם יש לך /manage-once-lite בצד השרת); אחרת אפשר /position-ops/manage-once עם חתימה:
    _sign_post "/position-ops/manage-once" "{\"symbol\":\"$sym\",\"do\":[\"be\",\"tp_ladder\"],\"atr_mult\":null}" | jq -r . 2>/dev/null || cat
    ;;

  be)
    sym="${1:?need SYMBOL}"; off="${2:-8}"
    _sign_post "/position-ops/be" "{\"symbol\":\"$sym\",\"offset_bps\":$off}" | jq -r . 2>/dev/null || cat
    ;;

  trail)
    sym="${1:?need SYMBOL}"; cb="${2:-auto}"; atr="${3:-}"
    if [ "$cb" = "auto" ]; then
      body="{\"symbol\":\"$sym\",\"atr_mult\":${atr:-1.2}}"
    else
      body="{\"symbol\":\"$sym\",\"callbackRate\":$cb}"
    fi
    _sign_post "/position-ops/trail" "$body" | jq -r . 2>/dev/null || cat
    ;;

  trail-off)
    sym="${1:?need SYMBOL}"
    _sign_post "/position-ops/trail/cancel" "{\"symbol\":\"$sym\"}" | jq -r . 2>/dev/null || cat
    ;;

  tp-one)
    sym="${1:?need SYMBOL}"; arg2="${2:?need --price PX | --pct PCT}"
    if [[ "$arg2" =~ ^--price$ ]]; then
      px="${3:?need price}"; body="{\"symbol\":\"$sym\",\"price\":$px}"
    elif [[ "$arg2" =~ ^--pct$ ]]; then
      pct="${3:?need pct}"; body="{\"symbol\":\"$sym\",\"pct\":$pct}"
    else
      echo "tp-one: use --price PX or --pct PCT" >&2; exit 2
    fi
    _sign_post "/position-ops/tp/one" "$body" | jq -r . 2>/dev/null || cat
    ;;

  tp-ladder)
    sym="${1:?need SYMBOL}"
    pcts="${2:-\"1.8,3.2,5.5\"}"; splits="${3:-\"0.4,0.35,0.25\"}"
    body="{\"symbol\":\"$sym\",\"pcts\":[${pcts//,/\,}],\"splits\":[${splits//,/\,}]}"
    # ↑ מאפשר לכתוב "3,6,12" וכו'
    _sign_post "/position-ops/tp/ladder" "$body" | jq -r . 2>/dev/null || cat
    ;;

  tp-cancel)
    sym="${1:?need SYMBOL}"
    _sign_post "/position-ops/tp/cancel" "{\"symbol\":\"$sym\"}" | jq -r . 2>/dev/null || cat
    ;;

  sl-move)
    sym="${1:?need SYMBOL}"; px="${2:?need PRICE}"
    _sign_post "/position-ops/sl/move" "{\"symbol\":\"$sym\",\"price\":$px}" | jq -r . 2>/dev/null || cat
    ;;

  close)
    sym="${1:?need SYMBOL}"; frac="${2:-1}"
    _sign_post "/position-ops/close" "{\"symbol\":\"$sym\",\"fraction\":$frac}" | jq -r . 2>/dev/null || cat
    ;;

  status)
    sym="${1:?need SYMBOL}"
    # GET חתום (קליינט קצר) – כאן נשתמש ב-bearer בלבד, כי יש רוט GET:
    curl -sS "$BASE/position-ops/status?symbol=$sym" -H "Authorization: Bearer $API_BEARER_TOKEN" | jq -r . 2>/dev/null || cat
    ;;

  auto-start)
    syms="${1:-}"; every="${2:-20}"
    if [ -n "$syms" ]; then
      body="{\"symbols\":[\"${syms//,/\",\"}\"],\"every_sec\":$every}"
    else
      body="{\"every_sec\":$every}"
    fi
    _sign_post "/position-ops/auto/start" "$body" | jq -r . 2>/dev/null || cat
    ;;

  auto-stop)
    # /auto/stop לא צריך body
    _sign_post "/position-ops/auto/stop" "{}" | jq -r . 2>/dev/null || cat
    ;;

  open-top)
    budget="${1:?need BUDGET_USD}"; lev="${2:?need LEVERAGE}"
    gate="${3:-auto}"; margin="${4:-ISOLATED}"; sym="${5:-}"
    # סימבול אופציונלי (אם יינתן — עוקפים TopK)
    if [ -n "$sym" ]; then
      body="{\"budget_usd\":$budget,\"leverage\":$lev,\"gate\":\"$gate\",\"margin_type\":\"$margin\",\"symbol\":\"$sym\"}"
    else
      body="{\"budget_usd\":$budget,\"leverage\":$lev,\"gate\":\"$gate\",\"margin_type\":\"$margin\"}"
    fi
    _sign_post "/position-ops/auto/open-top" "$body" | jq -r . 2>/dev/null || cat
    ;;

  *)
    _usage; exit 1 ;;
esac
BASH
chmod 755 /app/safe_ops.sh
sed -i 's/\r$//' /app/safe_ops.sh 2>/dev/null || true




