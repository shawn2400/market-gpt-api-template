cat >/app/safe_ops.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

: "${PUBLIC_HOST:?need PUBLIC_HOST}"
: "${API_BEARER_TOKEN:?need API_BEARER_TOKEN}"
: "${API_SIGNING_SECRET:?need API_SIGNING_SECRET}"

# ===== Anti-1003: token-bucket עדין =====
BUCKET_FILE="/tmp/anti1003.bucket"
BUCKET_CAP=${BUCKET_CAP:-6}      # burst
REFILL_RPS=${REFILL_RPS:-3}      # tokens/sec
_now_ms(){ date +%s%3N; }
_bucket_take(){
  local now cap tokens last tdelta add
  now=$(_now_ms); cap=$BUCKET_CAP
  mkdir -p "$(dirname "$BUCKET_FILE")" || true
  if [[ -f "$BUCKET_FILE" ]]; then
    read -r last tokens < "$BUCKET_FILE" || { last=$now; tokens=$cap; }
  else last=$now; tokens=$cap; fi
  tdelta=$(( now - last ))
  add=$(( (tdelta * REFILL_RPS) / 1000 ))
  if (( add > 0 )); then
    tokens=$(( tokens + add )); (( tokens > cap )) && tokens=$cap; last=$now
  fi
  if (( tokens <= 0 )); then sleep 0.35; _bucket_take; return; fi
  tokens=$(( tokens - 1 ))
  printf "%s %s\n" "$last" "$tokens" > "$BUCKET_FILE"
}

# ===== nonce / hmac עם fallback =====
_nonce(){
  if command -v uuidgen >/dev/null 2>&1; then uuidgen
  elif [[ -r /proc/sys/kernel/random/uuid ]]; then cat /proc/sys/kernel/random/uuid
  else echo "nonce-$RANDOM-$(_now_ms)"; fi
}
_hmac_sha256_hex(){
  if command -v xxd >/dev/null 2>&1; then
    openssl dgst -sha256 -hmac "$API_SIGNING_SECRET" -binary | xxd -p -c 256
  else
    openssl dgst -sha256 -hmac "$API_SIGNING_SECRET" -binary | od -An -tx1 | tr -d ' \n'
  fi
}
_sign(){
  local method="$1" path="$2" body="$3" ts="$4" nonce="$5"
  printf "%s\n%s\n%s\n%s\n%s" "$method" "$path" "$body" "$ts" "$nonce" | _hmac_sha256_hex
}

_do_signed(){
  local method="$1" path="$2" body="${3:-}"
  _bucket_take
  local ts nonce sig
  ts=$(_now_ms); nonce=$(_nonce)
  sig=$(_sign "$method" "$path" "$body" "$ts" "$nonce")
  curl -sS -X "$method" "${PUBLIC_HOST}${path}" \
    -H "Authorization: Bearer ${API_BEARER_TOKEN}" \
    -H "Content-Type: application/json" \
    -H "X-TS: ${ts}" \
    -H "X-Nonce: ${nonce}" \
    -H "X-Signature: ${sig}" \
    ${body:+ -d "$body"}
}
_do_plain(){
  local method="$1" path="$2" body="${3:-}"
  _bucket_take
  curl -sS -X "$method" "${PUBLIC_HOST}${path}" \
    -H "Authorization: Bearer ${API_BEARER_TOKEN}" \
    -H "Content-Type: application/json" \
    ${body:+ -d "$body"}
}

usage(){
cat <<'USAGE'
safe_ops.sh — כלי בטוח ל-/position-ops/* עם חתימה + anti-1003

ENV חובה:
  PUBLIC_HOST, API_BEARER_TOKEN, API_SIGNING_SECRET

פקודות:
  manage-once [SYMBOL]              — POST /manage-once (ללא חתימה)
  tp-one SYMBOL PRICE QTY           — POST /position-ops/tp/one (reduceOnly)
  tp-ladder SYMBOL P1 P2 P3 Q1 Q2 Q3 — POST /position-ops/tp/ladder (עד 3 רמות)
  be SYMBOL [OFFSET_BPS=12]         — POST /position-ops/be/set
  move-sl SYMBOL PRICE              — POST /position-ops/sl/move
  trail-off SYMBOL                  — POST /position-ops/trail/off
  tp-cancel SYMBOL                  — POST /position-ops/tp/cancel
  help                              — עזרה

דוגמאות:
  SYMBOL=BTCUSDT ./safe_ops.sh manage-once
  ./safe_ops.sh tp-one BTCUSDT 117663.3 0.01
  ./safe_ops.sh be BTCUSDT 12
  ./safe_ops.sh move-sl BTCUSDT 112519.8
USAGE
}

cmd="${1:-}"; shift || true
case "$cmd" in
  manage-once)
    sym="${SYMBOL:-${1:-}}"; [[ -n "$sym" ]] || { echo "need SYMBOL"; exit 2; }
    body=$(printf '{"symbol":"%s","force":true}' "$sym")
    _do_plain "POST" "/manage-once" "$body"
    ;;
  tp-one)
    sym="${1:-}"; price="${2:-}"; qty="${3:-}"
    [[ -n "$sym" && -n "$price" && -n "$qty" ]] || { echo "usage: tp-one SYMBOL PRICE QTY"; exit 2; }
    body=$(printf '{"symbol":"%s","price":%s,"qty":%s,"side":"SELL","reduceOnly":true}' "$sym" "$price" "$qty")
    _do_signed "POST" "/position-ops/tp/one" "$body"
    ;;
  tp-ladder)
    sym="${1:-}"; p1="${2:-}"; p2="${3:-}"; p3="${4:-}"; q1="${5:-}"; q2="${6:-}"; q3="${7:-}"
    [[ -n "$sym" ]] || { echo "usage: tp-ladder SYMBOL [P1 P2 P3 Q1 Q2 Q3]"; exit 2; }
    build_ladder(){ local acc="[" first=1; for i in 1 2 3; do eval "pp=\$p$i" "qq=\$q$i"
      if [[ -n "${pp:-}" && -n "${qq:-}" ]]; then [[ $first -eq 0 ]] && acc+=", "; acc+=$(printf '{"price":%s,"qty":%s}' "$pp" "$qq"); first=0; fi
    done; acc+="]"; printf "%s" "$acc"; }
    ladder="$(build_ladder)"
    body=$(printf '{"symbol":"%s","items":%s,"side":"SELL","reduceOnly":true}' "$sym" "$ladder")
    _do_signed "POST" "/position-ops/tp/ladder" "$body"
    ;;
  be)
    sym="${1:-}"; off="${2:-12}"
    [[ -n "$sym" ]] || { echo "usage: be SYMBOL [OFFSET_BPS]"; exit 2; }
    body=$(printf '{"symbol":"%s","offset_bps":%s}' "$sym" "$off")
    _do_signed "POST" "/position-ops/be/set" "$body"
    ;;
  move-sl)
    sym="${1:-}"; price="${2:-}"
    [[ -n "$sym" && -n "$price" ]] || { echo "usage: move-sl SYMBOL PRICE"; exit 2; }
    body=$(printf '{"symbol":"%s","price":%s}' "$sym" "$price")
    _do_signed "POST" "/position-ops/sl/move" "$body"
    ;;
  trail-off)
    sym="${1:-}"; [[ -n "$sym" ]] || { echo "usage: trail-off SYMBOL"; exit 2; }
    body=$(printf '{"symbol":"%s"}' "$sym")
    _do_signed "POST" "/position-ops/trail/off" "$body"
    ;;
  tp-cancel)
    sym="${1:-}"; [[ -n "$sym" ]] || { echo "usage: tp-cancel SYMBOL"; exit 2; }
    body=$(printf '{"symbol":"%s"}' "$sym")
    _do_signed "POST" "/position-ops/tp/cancel" "$body"
    ;;
  ""|-h|--help|help) usage ;;
  *) echo "Unknown command: $cmd"; usage; exit 2 ;;
esac
EOF

chmod +x /app/safe_ops.sh

