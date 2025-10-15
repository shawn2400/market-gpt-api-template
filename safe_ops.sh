cat >/app/safe_ops.sh <<'BASH'
#!/usr/bin/env bash
set -euo pipefail

: "${PUBLIC_HOST:?need PUBLIC_HOST}"
: "${API_BEARER_TOKEN:?need API_BEARER_TOKEN}"
SIGN_SECRET="${OPS_SIGN_SECRET:-${API_SIGNING_SECRET:-}}"

# ===== anti-1003 mini bucket =====
bucket="/tmp/anti1003_bucket.ops"
cap=${BUCKET_CAP:-30}; int=60; w=${WEIGHT:-1}
now(){ date +%s; }
refill(){
  local n; n=$(now)
  if [[ -f "$bucket" ]]; then
    awk -v c=$((n-int)) '$1>=c{print $1}' "$bucket" > "$bucket.tmp" || true
    mv "$bucket.tmp" "$bucket" 2>/dev/null || :
  else
    : > "$bucket"
  fi
}
take(){
  local used=0
  [[ -f "$bucket" ]] && used=$(wc -l < "$bucket" || echo 0)
  if (( used + w > cap )); then sleep 1; fi
  echo "$(now)" >> "$bucket"
}

# ===== signing helper (server expects "{ts}.{nonce}.{route}.{sha256(canon_json)}") =====
sign_and_post(){ # method route body_json_minified_sorted
  local m="$1" p="$2" b="$3" ts nonce hsh base sig
  ts=$(date +%s)                              # seconds (NOT ms)
  nonce=$(cat /proc/sys/kernel/random/uuid)
  hsh=$(printf "%s" "$b" | openssl dgst -sha256 -r | awk '{print $1}')
  base="$ts.$nonce.$p.$hsh"
  sig=$(printf "%s" "$base" | openssl dgst -sha256 -hmac "$SIGN_SECRET" -r | awk '{print $1}')
  curl -sS -X "$m" "$PUBLIC_HOST$p" \
    -H "Authorization: Bearer $API_BEARER_TOKEN" \
    -H "Content-Type: application/json" \
    -H "X-Timestamp: $ts" -H "X-Nonce: $nonce" -H "X-Signature: $sig" \
    --data-binary "$b"
}

need_sym(){ local s="${SYMBOL:-${1:-}}"; [[ -z "$s" ]] && { echo "SYMBOL: need SYMBOL" >&2; exit 2; }; echo "$s"; }

cmd="${1:-}"; shift || true
refill; take

case "$cmd" in
  manage-once)
    s=$(need_sym "${1:-}")
    curl -sS -X POST "$PUBLIC_HOST/manage-once" \
      -H "Authorization: Bearer $API_BEARER_TOKEN" \
      -H "Content-Type: application/json" \
      --data-binary '{"symbol":"'"$s"'","force":true}'
    ;;
  tp-one)
    # Usage: tp-one [SYMBOL] [PRICE] [QTY]
    [[ -n "${1:-}" ]] && SYMBOL="$1" && shift || true
    [[ -n "${1:-}" ]] && PRICE="$1" && shift || true
    [[ -n "${1:-}" ]] && QTY="$1" && shift || true
    s=$(need_sym); : "${PRICE:?need PRICE}"; : "${QTY:?need QTY}"
    # keys alpha-sorted to match server canon:
    sign_and_post POST "/position-ops/tp/one" \
      '{"price":'"$PRICE"',"qty":'"$QTY"',"reduceOnly":true,"side":"SELL","symbol":"'"$s"'"}'
    ;;
  tp-cancel)
    s=$(need_sym "${1:-}")
    sign_and_post POST "/position-ops/tp/cancel" '{"symbol":"'"$s"'"}'
    ;;
  trail)
    s=$(need_sym "${1:-}")
    # enable=true must come before symbol for canon sort
    sign_and_post POST "/position-ops/trail" '{"enable":true,"symbol":"'"$s"'"}'
    ;;
  *)
    echo "Unknown command: ${cmd:-<empty>} (use: manage-once|tp-one|tp-cancel|trail)" >&2
    exit 1;;
esac
BASH
chmod +x /app/safe_ops.sh





