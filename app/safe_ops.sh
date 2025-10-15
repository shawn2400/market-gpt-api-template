cat >/app/safe_ops.sh <<'BASH'
#!/usr/bin/env bash
set -euo pipefail

BASE="${PUBLIC_HOST:-http://localhost:10000}"
AUTH="Authorization: Bearer ${API_BEARER_TOKEN:-}"
SIGN_SECRET="${API_SIGNING_SECRET:-}"

red()   { printf "\033[31m%s\033[0m\n" "$*"; }
green() { printf "\033[32m%s\033[0m\n" "$*"; }
die()   { red "ERR: $*"; exit 1; }

need_auth() {
  if [ -z "${API_BEARER_TOKEN:-}" ]; then
    die "API_BEARER_TOKEN is not set"
  fi
}

need_sign() {
  if [ -z "${SIGN_SECRET:-}" ]; then
    die "API_SIGNING_SECRET/OPS_SIGN_SECRET is not set"
  fi
}

# returns: TS NONCE SIG
sign_body() {
  local body="$1"
  python3 - <<PY
import os,sys,time,secrets,hashlib,hmac
secret = os.environ.get("SIGN_SECRET","").strip()
if not secret:
    print("")
    sys.exit(0)
ts = str(int(time.time()))
nonce = secrets.token_hex(8)
payload = f"{ts}.{nonce}.{body}".encode("utf-8")
key = bytes.fromhex(secret) if len(secret)==64 else secret.encode("utf-8")
sig = hmac.new(key, payload, hashlib.sha256).hexdigest()
print(ts, nonce, sig)
PY
}

post_signed() {
  need_auth
  need_sign
  local path="$1"; shift
  local body_json="$1"; shift
  read TS NONCE SIG < <(SIGN_SECRET="$SIGN_SECRET" sign_body "$body_json")
  [ -z "${TS:-}" ] && die "signing failed"
  curl -sS -X POST "${BASE}${path}" \
    -H "Content-Type: application/json" \
    -H "${AUTH}" \
    -H "X-Timestamp: ${TS}" \
    -H "X-Nonce: ${NONCE}" \
    -H "X-Signature: ${SIG}" \
    --data-binary "${body_json}"
  echo
}

post_plain() {
  local path="$1"; shift
  local body_json="$1"; shift
  local args=(-sS -X POST "${BASE}${path}" -H "Content-Type: application/json" --data-binary "${body_json}")
  if [ -n "${API_BEARER_TOKEN:-}" ]; then
    args+=(-H "${AUTH}")
  fi
  curl "${args[@]}"
  echo
}

usage() {
  cat <<'US'
safe_ops.sh – helper for AlgoGPT (no jq)

Examples:
  safe_ops.sh manage-once-lite BTCUSDT

  safe_ops.sh manage-once   BTCUSDT
  safe_ops.sh be            BTCUSDT 12
  safe_ops.sh trail         BTCUSDT 1.6
  safe_ops.sh tp-one        BTCUSDT 3.2 1.0
  safe_ops.sh tp-ladder     BTCUSDT "3,6,12" "0.25,0.25,0.5"
  safe_ops.sh tp-cancel     BTCUSDT
  safe_ops.sh sl-move       BTCUSDT 0.8
  safe_ops.sh close         BTCUSDT
  safe_ops.sh status        BTCUSDT
  safe_ops.sh auto-start    BTCUSDT
  safe_ops.sh auto-stop     BTCUSDT
US
}

cmd="${1:-}"; shift || true
case "${cmd}" in
  help|-h|--help|"") usage; exit 0 ;;
  manage-once-lite)
    sym="${1:-}"; [ -z "$sym" ] && die "missing symbol"
    post_plain "/manage-once-lite" "{\"symbol\":\"${sym}\"}"
    ;;
  manage-once)
    sym="${1:-}"; [ -z "$sym" ] && die "missing symbol"
    post_signed "/manage-once" "{\"symbol\":\"${sym}\"}"
    ;;
  be)
    sym="${1:-}"; bps="${2:-12}"
    [ -z "$sym" ] && die "missing symbol"; [ -z "$bps" ] && die "missing offset_bps"
    post_signed "/position-ops/be" "{\"symbol\":\"${sym}\",\"offset_bps\":${bps}}"
    ;;
  trail)
    sym="${1:-}"; atr="${2:-1.6}"
    [ -z "$sym" ] && die "missing symbol"
    post_signed "/position-ops/trail" "{\"symbol\":\"${sym}\",\"atr_mult\":${atr}}"
    ;;
  tp-one)
    sym="${1:-}"; pct="${2:-3.0}"; split="${3:-1.0}"
    [ -z "$sym" ] && die "missing symbol"
    post_signed "/position-ops/tp/one" "{\"symbol\":\"${sym}\",\"pcts\":[${pct}],\"splits\":[${split}]}"
    ;;
  tp-ladder)
    sym="${1:-}"; pcts="${2:-3,6,12}"; splits="${3:-0.25,0.25,0.5}"
    [ -z "$sym" ] && die "missing symbol"
    pjson=$(printf '%s' "$pcts" | awk -F, '{printf("[" ); for(i=1;i<=NF;i++){ if(i>1) printf(","); printf("%s",$i)}; print "]"}')
    sjson=$(printf '%s' "$splits"| awk -F, '{printf("[" ); for(i=1;i<=NF;i++){ if(i>1) printf(","); printf("%s",$i)}; print "]"}')
    post_signed "/position-ops/tp/ladder" "{\"symbol\":\"${sym}\",\"pcts\":${pjson},\"splits\":${sjson}}"
    ;;
  tp-cancel)
    sym="${1:-}"; [ -z "$sym" ] && die "missing symbol"
    post_signed "/position-ops/tp/cancel" "{\"symbol\":\"${sym}\"}"
    ;;
  sl-move)
    sym="${1:-}"; pct="${2:-0.8}"
    [ -z "$sym" ] && die "missing symbol"
    post_signed "/position-ops/sl/move" "{\"symbol\":\"${sym}\",\"atr_mult\":${pct}}"
    ;;
  close)
    sym="${1:-}"; [ -z "$sym" ] && die "missing symbol"
    post_signed "/position-ops/close" "{\"symbol\":\"${sym}\"}"
    ;;
  status)
    sym="${1:-}"; [ -z "$sym" ] && die "missing symbol"
    post_signed "/position-ops/status" "{\"symbol\":\"${sym}\"}"
    ;;
  auto-start)
    sym="${1:-}"; [ -z "$sym" ] && die "missing symbol"
    post_signed "/position-ops/auto/start" "{\"symbol\":\"${sym}\"}"
    ;;
  auto-stop)
    sym="${1:-}"; [ -z "$sym" ] && die "missing symbol"
    post_signed "/position-ops/auto/stop" "{\"symbol\":\"${sym}\"}"
    ;;
  *)
    usage; die "unknown command: ${cmd}"
    ;;
esac
BASH

chmod +x /app/safe_ops.sh


