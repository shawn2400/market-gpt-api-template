cat >/app/ops_toolkit.sh <<'BASH'
#!/usr/bin/env bash
set -euo pipefail

need() { test -n "${!1:-}" || { echo "missing env: $1" >&2; exit 2; }; }
need PUBLIC_HOST; need API_BEARER_TOKEN; need OPS_SIGN_SECRET

_hmac() { openssl dgst -sha256 -hmac "$OPS_SIGN_SECRET" -r | awk '{print $1}'; }
_norm() { case "$1" in /*) printf '%s' "$1";; *) printf '/%s' "$1";; esac; }

# POST חתום
sign_post() {
  local path="$(_norm "${1:?path}")"
  local body="${2:-{}}"
  local ts nonce payload sig
  ts="$(date +%s)"
  nonce="$(cat /proc/sys/kernel/random/uuid)"
  payload="POST
$path
$body
$ts
$nonce"
  sig="$(printf '%s' "$payload" | _hmac)"
  curl -fsS -X POST "$PUBLIC_HOST$path" \
    -H "Authorization: Bearer $API_BEARER_TOKEN" \
    -H "Content-Type: application/json" \
    -H "X-Timestamp: $ts" \
    -H "X-Nonce: $nonce" \
    -H "X-Signature: $sig" \
    --data-binary "$body"
}

# GET חתום (BODY ריק)
sign_get() {
  local path="$(_norm "${1:?path}")"
  local ts nonce payload sig
  ts="$(date +%s)"
  nonce="$(cat /proc/sys/kernel/random/uuid)"
  payload="GET
$path

$ts
$nonce"
  sig="$(printf '%s' "$payload" | _hmac)"
  curl -fsS "$PUBLIC_HOST$path" \
    -H "Authorization: Bearer $API_BEARER_TOKEN" \
    -H "X-Timestamp: $ts" \
    -H "X-Nonce: $nonce" \
    -H "X-Signature: $sig"
}

alias sp='sign_post'
alias sg='sign_get'
BASH
