#!/usr/bin/env bash
set -euo pipefail

: "${PUBLIC_HOST:?need PUBLIC_HOST}"
: "${API_BEARER_TOKEN:?need API_BEARER_TOKEN}"

# ===== Token bucket (לקריאות OPS) =====
# נניח עד 30 "משקל" בדקה לפקודות ידניות (מספיק לניטור/טסטים),
# כל קריאה נספרת כמשקל 1 (אפשר לשנות עם WEIGHT=2 ./safe_ops.sh ...)
BUCKET_FILE="/tmp/anti1003_bucket.ops"
BUCKET_CAP=${BUCKET_CAP:-30}      # קיבולת לדקה
REFILL_INT=60                     # שניות
WEIGHT=${WEIGHT:-1}               # משקל לקריאה

now() { date +%s; }

bucket_refill() {
  local ts now_ts used
  now_ts=$(now)
  if [[ -f "$BUCKET_FILE" ]]; then
    # שמור רק זמני אירועים בדקה האחרונה
    awk -v cutoff=$((now_ts-REFILL_INT)) '$1>=cutoff {print $1}' "$BUCKET_FILE" > "${BUCKET_FILE}.tmp" || true
    mv "${BUCKET_FILE}.tmp" "$BUCKET_FILE"
  else
    : > "$BUCKET_FILE"
  fi
}

bucket_take() {
  local used
  used=$(wc -l < "$BUCKET_FILE" || echo 0)
  if (( used + WEIGHT > BUCKET_CAP )); then
    # צריך להמתין עד שייפלו אירועים ישנים
    local oldest remain sleep_sec
    oldest=$(head -n1 "$BUCKET_FILE" || echo $(now))
    remain=$(( oldest + REFILL_INT - $(now) ))
    (( remain < 1 )) && remain=1
    sleep "$remain"
    bucket_refill
  fi
  for ((i=0;i<WEIGHT;i++)); do echo "$(now)" >> "$BUCKET_FILE"; done
}

do_post_json() {
  local path="$1" body="$2"
  local backoff=1 max_backoff=32 attempt=0
  while :; do
    attempt=$((attempt+1))
    bucket_refill
    bucket_take

    resp="$(curl -sS -w '\n%{http_code}' -X POST "$PUBLIC_HOST$path" \
      -H "Authorization: Bearer $API_BEARER_TOKEN" \
      -H "Content-Type: application/json" \
      -d "$body" || true)"

    body_part="$(echo "$resp" | head -n -1)"
    code_part="$(echo "$resp" | tail -n1)"

    # זיהוי עומס: HTTP 429/418 או קוד ביננס -1003 בתוך הגוף
    if [[ "$code_part" == "200" ]] && ! echo "$body_part" | grep -qE 'code":-1003|Too many requests'; then
      echo "$body_part"
      return 0
    fi

    if echo "$body_part" | grep -qE 'code":-1003|Too many requests|IP banned|IP ban|weight'; then
      # backoff אקספוננציאלי עם ג'יטר 100–400ms
      jitter=$(( (RANDOM % 300) + 100 ))
      sleep_ms=$(( backoff*1000 + jitter ))
      echo "anti-1003: backoff ${sleep_ms}ms (attempt #$attempt) ..." >&2
      python3 - <<PY
import time
time.sleep(${sleep_ms}/1000.0)
PY
      (( backoff < max_backoff )) && backoff=$(( backoff*2 ))
      continue
    fi

    # אם קיבלנו 429/418 בלי טקסט מפורש, נטפל אותו דבר
    if [[ "$code_part" == "429" || "$code_part" == "418" ]]; then
      jitter=$(( (RANDOM % 300) + 100 ))
      sleep_ms=$(( backoff*1000 + jitter ))
      echo "rate-limit http ${code_part}: backoff ${sleep_ms}ms (attempt #$attempt) ..." >&2
      python3 - <<PY
import time
time.sleep(${sleep_ms}/1000.0)
PY
      (( backoff < max_backoff )) && backoff=$(( backoff*2 ))
      continue
    fi

    # שגיאה אחרת — החזר כפי שהוא
    echo "$body_part"
    return 1
  done
}

usage() {
  cat <<EOF
safe_ops.sh — שומר על קצב פקודות OPS כדי לא להדליק ‎-1003
שימוש:
  SYMBOL=BTCUSDT ./safe_ops.sh manage-once
  SYMBOL=BTCUSDT QTY=0.25 PRICE=12345 ./safe_ops.sh tp-one
משתנים:
  PUBLIC_HOST, API_BEARER_TOKEN — חובה
  WEIGHT (ברירת מחדל 1), BUCKET_CAP (ברירת מחדל 30/דקה)
פקודות:
  manage-once   — יקרא POST /manage-once {"symbol":SYMBOL,"force":true}
  tp-cancel     — POST /position-ops/tp/cancel {"symbol":SYMBOL}
  tp-one        — POST /position-ops/tp/one {"symbol":SYMBOL,"price":PRICE,"qty":QTY,"side":"SELL","reduceOnly":true}
  trail         — POST /position-ops/trail {"symbol":SYMBOL,"enable":true}
EOF
}

cmd="${1:-}"
case "$cmd" in
  manage-once)
    : "${SYMBOL:?need SYMBOL}"
    do_post_json "/manage-once" "$(printf '{"symbol":"%s","force":true}' "$SYMBOL")"
    ;;
  tp-cancel)
    : "${SYMBOL:?need SYMBOL}"
    do_post_json "/position-ops/tp/cancel" "$(printf '{"symbol":"%s"}' "$SYMBOL")"
    ;;
  tp-one)
    : "${SYMBOL:?need SYMBOL}"
    : "${PRICE:?need PRICE}"; : "${QTY:?need QTY}"
    do_post_json "/position-ops/tp/one" "$(printf '{"symbol":"%s","price":%s,"qty":%s,"side":"SELL","reduceOnly":true}' "$SYMBOL" "$PRICE" "$QTY")"
    ;;
  trail)
    : "${SYMBOL:?need SYMBOL}"
    do_post_json "/position-ops/trail" "$(printf '{"symbol":"%s","enable":true}' "$SYMBOL")"
    ;;
  ""|-h|--help|help)
    usage;;
  *)
    echo "Unknown command: $cmd" ; usage ; exit 2;;
esac
