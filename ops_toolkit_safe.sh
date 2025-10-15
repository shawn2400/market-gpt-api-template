cat >/app/ops_toolkit_safe.sh <<'BASH'
# אל תשנה flags גלובליים. אל תשתמש ב-:${VAR:?}.
_need(){ [ -n "$1" ] || { echo "missing required env: $2" >&2; return 1; }; }

_ok_env(){
  _need "$PUBLIC_HOST" "PUBLIC_HOST"   || return 1
  _need "$API_BEARER_TOKEN" "API_BEARER_TOKEN" || return 1
  _need "$OPS_SIGN_SECRET" "OPS_SIGN_SECRET"   || return 1
  command -v curl >/dev/null 2>&1 || { echo "curl not found" >&2; return 1; }
  command -v openssl >/dev/null 2>&1 || { echo "openssl not found" >&2; return 1; }
  return 0
}

_normpath(){ case "$1" in /*) printf '%s' "$1";; *) printf '/%s' "$1";; esac; }

_hmac_hex(){
  # stdin -> sha256 hmac hex
  openssl dgst -sha256 -hmac "$OPS_SIGN_SECRET" -r 2>/dev/null | awk '{print $1}'
}

sign_post(){ # usage: sign_post /path '{"json":"body"}'
  _ok_env || return 1
  local path="$(_normpath "${1:?}")"; shift
  local body="${1:-{}}"
  local ts nonce payload sig
  ts="$(date +%s)" || return 1
  nonce="$(cat /proc/sys/kernel/random/uuid 2>/dev/null || uuidgen 2>/dev/null || echo $$.$RANDOM)"
  payload="POST
$path
$body
$ts
$nonce"
  sig="$(printf '%s' "$payload" | _hmac_hex)" || return 1
  curl -fsS -X POST "$PUBLIC_HOST$path" \
    -H "Authorization: Bearer $API_BEARER_TOKEN" \
    -H "Content-Type: application/json" \
    -H "X-Timestamp: $ts" -H "X-Nonce: $nonce" -H "X-Signature: $sig" \
    --data-binary "$body"
}

sign_get(){ # usage: sign_get "/path?query=1"
  _ok_env || return 1
  local path="$(_normpath "${1:?}")"
  local ts nonce payload sig
  ts="$(date +%s)" || return 1
  nonce="$(cat /proc/sys/kernel/random/uuid 2>/dev/null || uuidgen 2>/dev/null || echo $$.$RANDOM)"
  payload="GET
$path

$ts
$nonce"
  sig="$(printf '%s' "$payload" | _hmac_hex)" || return 1
  curl -fsS "$PUBLIC_HOST$path" \
    -H "Authorization: Bearer $API_BEARER_TOKEN" \
    -H "X-Timestamp: $ts" -H "X-Nonce: $nonce" -H "X-Signature: $sig"
}

alias sp='sign_post'
alias sg='sign_get'
BASH
chmod 755 /app/ops_toolkit_safe.sh
. /app/ops_toolkit_safe.sh
