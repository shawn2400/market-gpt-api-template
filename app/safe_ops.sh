#!/usr/bin/env bash
# tiny ops helper (Bearer + חתימה תקינה ts.nonce.body)

_need(){ [ -n "$1" ] || { echo "missing env: $2" >&2; return 1; }; }
_ok(){
  _need "$PUBLIC_HOST" PUBLIC_HOST   || return 1
  _need "$API_BEARER_TOKEN" API_BEARER_TOKEN || return 1
  _need "$OPS_SIGN_SECRET" OPS_SIGN_SECRET   || return 1
  command -v curl >/dev/null || { echo "curl not found" >&2; return 1; }
  command -v openssl >/dev/null || { echo "openssl not found" >&2; return 1; }
}

_sig(){ printf '%s' "$1" | openssl dgst -sha256 -hmac "$OPS_SIGN_SECRET" -r | awk '{print $1}'; }

sp(){ # Signed POST: sp "/path" '{"k":"v"}'
  _ok || return 1
  local p="$1" b="${2:-{}}"
  local ts n payload sig
  ts="$(date +%s)"
  n="$(cat /proc/sys/kernel/random/uuid 2>/dev/null || echo $$.$RANDOM)"
  payload="$ts.$n.$b"
  sig="$(_sig "$payload")"
  curl -fsS -X POST "$PUBLIC_HOST$p" \
    -H "Authorization: Bearer $API_BEARER_TOKEN" \
    -H "Content-Type: application/json" \
    -H "X-Timestamp: $ts" \
    -H "X-Nonce: $n" \
    -H "X-Signature: $sig" \
    --data-binary "$b"
}

sg(){ # GET (לא דורש חתימה ב-/status, אבל נשאיר Bearer)
  _ok || return 1
  local p="$1"
  curl -fsS -X GET "$PUBLIC_HOST$p" \
    -H "Authorization: Bearer $API_BEARER_TOKEN"
}







