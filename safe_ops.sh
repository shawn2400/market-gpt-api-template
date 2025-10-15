#!/usr/bin/env bash
set -euo pipefail

: "${PUBLIC_HOST:?need PUBLIC_HOST}"
: "${API_BEARER_TOKEN:?need API_BEARER_TOKEN}"

# חתימה: נעדיף OPS_SIGN_SECRET, ואם אין – נשתמש ב-API_SIGNING_SECRET
SIGN_SECRET="${OPS_SIGN_SECRET:-${API_SIGNING_SECRET:-}}"

# ===== Token bucket =====
BUCKET_FILE="/tmp/anti1003_bucket.ops"
BUCKET_CAP=${BUCKET_CAP:-30}
REFILL_INT=60
WEIGHT=${WEIGHT:-1}

now() { date +%s; }

bucket_refill() {
  local now_ts; now_ts=$(now)
  if [[ -f "$BUCKET_FILE" ]]; then
    awk -v cutoff=$((now_ts-REFILL_INT)) '$1>=cutoff {print $1}' "$BUCKET_FILE" > "${BUCKET_FILE}.tmp" || true
    mv "${BUCKET_FILE}.tmp" "$BUCKET_FILE"
  else
    : > "$BUCKET_FILE"
  fi
}

bucket_take() {
  local used; used=$(wc -l < "$BUCKET_FILE" || echo 0)
  if (( used + WEIGHT > BUCKET_CAP )); then
    local oldest remain sleep_sec
    oldest=$(head -n1 "$BUCKET_FILE" || echo $(now))
    remain=$(( oldest + REFILL_INT - $(now) ))
    (( remain > 0 )) && sleep "$remain"
  fi
  echo "$(now)" >> "$BUCKET_FILE"
}

json() { jq -c '.' 2>/dev/null || cat; }

sign_and_post() {
  # $1 method, $2 path, $3 raw_body
  local method="$1" path="$2" body="$3"
  local ts nonce sig
  ts=$(date +%s%3N)
  nonce=$(cat /proc/sys/kernel/random/uuid)
  if [[ -z "${SIGN_SECRET:-}" ]]; then
    echo '{"ok":false,"reason":"missing_sign_secret"}'
    return 4
  fi
  sig=$(printf "%s\n%s\n%s\n%s\n%s" "$method" "$path" "$body" "$ts" "$nonce" | \
        openssl dgst -sha256 -hmac "$SIGN_SECRET" -binary | od -An -tx1 | tr -d ' \n')
  curl -sS -X "$method" "$PUBLIC_HOST$path" \
    -H "Authorization: Bearer $API_BEARER_TOKEN" \
    -H "Content-Type: application/json" \
    -H "X-TS: $ts" -H "X-Nonce: $nonce" -H "X-Signature: $sig" \
    --data-binary "$body"
}

# ===== פריסה של ארגומנטים/ENV =====
# נקבל SYMBOL גם מ-env וגם מארגומנט ראשון אחרי הפקודה
require_symbol() {
  local _sym="${SYMBOL:-${1:-}}"
  if [[ -z "$_sym" ]]; then
    echo "SYMBOL: need SYMBOL" >&2
    exit 2
  fi
  echo "$_sym"
}

# ===== פקודות נתמכות =====
usage() {
  cat <<'USAGE'
safe_ops.sh — שומר על קצב קריאות ומבצע חתימה ל-OPS
שימוש:
  SYMBOL=BTCUSDT ./safe_ops.sh manage-once
  ./safe_ops.sh manage-once BTCUSDT

  SYMBOL=BTCUSDT PRICE=12345 QTY=0.01 ./safe_ops.sh tp-one
  ./safe_ops.sh tp-one BTCUSDT 12345 0.01

  SYMBOL=BTCUSDT ./safe_ops.sh tp-cancel
  ./safe_ops.sh tp-cancel BTCUSDT

  SYMBOL=BTCUSDT ./safe_ops.sh trail
  ./safe_ops.sh trail BTCUSDT

משתנים:
  PUBLIC_HOST, API_BEARER_TOKEN — חובה
  OPS_SIGN_SECRET או API_SIGNING_SECRET — לחתימה
  WEIGHT (ברירת מחדל 1), BUCKET_CAP (ברירת מחדל 30/דקה)
פקודות:
  manage-once  — POST /manage-once {"symbol":SYMBOL,"force":true}  (ללא חתימה)
  tp-one       — POST /position-ops/tp/one {"symbol", "price", "qty", "side":"SELL","reduceOnly":true}
  tp-cancel    — POST /position-ops/tp/cancel {"symbol":SYMBOL}
  trail        — POST /position-ops/trail {"symbol":SYMBOL,"enable":true}
USAGE
}

cmd="${1:-}"; shift || true
bucket_refill; bucket_take

case "$cmd" in
  manage-once)
    sym=$(require_symbol "${1:-}")
    curl -sS -X POST "$PUBLIC_HOST/manage-once" \
      -H "Authorization: Bearer $API_BEARER_TOKEN" \
      -H "Content-Type: application/json" \
      --data-binary "$(jq -nc --arg s "$sym" '{symbol:$s,force:true}')" | json
    ;;
  tp-one)
    # args: SYMBOL PRICE QTY  (או דרך ENV)
    if [[ -n "${1:-}" ]]; then SYMBOL="$1"; shift; fi
    if [[ -n "${1:-}" ]]; then PRICE="$1"; shift; fi
    if [[ -n "${1:-}" ]]; then QTY="$1"; shift; fi
    sym=$(require_symbol)
    : "${PRICE:?need PRICE}"; : "${QTY:?need QTY}"
    body=$(jq -nc --arg s "$sym" --argjson p "$PRICE" --argjson q "$QTY" \
            '{symbol:$s,price:$p,qty:$q,side:"SELL",reduceOnly:true}')
    sign_and_post POST "/position-ops/tp/one" "$body" | json
    ;;
  tp-cancel)
    sym=$(require_symbol "${1:-}")
    body=$(jq -nc --arg s "$sym" '{symbol:$s}')
    sign_and_post POST "/position-ops/tp/cancel" "$body" | json
    ;;
  trail)
    sym=$(require_symbol "${1:-}")
    body=$(jq -nc --arg s "$sym" '{symbol:$s,enable:true}')
    sign_and_post POST "/position-ops/trail" "$body" | json
    ;;
  ""|-h|--help|help)
    usage;;
  *)
    echo "Unknown command: $cmd" >&2
    usage; exit 1;;
esac




