# ops_toolkit.sh — פונקציות GET/POST חתומות (Anti-Replay)
cat >/app/ops_toolkit.sh <<'BASH'
#!/usr/bin/env bash
set -euo pipefail

# דרישות:
: "${PUBLIC_HOST:?need PUBLIC_HOST}"
: "${API_BEARER_TOKEN:?need API_BEARER_TOKEN}"
: "${OPS_SIGN_SECRET:?need OPS_SIGN_SECRET}"

_hmac(){ openssl dgst -sha256 -hmac "$OPS_SIGN_SECRET" -r | awk '{print $1}'; }
_norm(){ case "$1" in /*) printf '%s' "$1";; *) printf '/%s' "$1";; esac; }

sign_post(){ # usage: sign_post /path '{"json":"body"}'
  local path="$(_norm "${1:?}")" body="${2:-{}}"
  local ts nonce payload sig
  ts="$(date +%s)"; nonce="$(cat /proc/sys/kernel/random/uuid)"
  payload="POST
$path
$body
$ts
$nonce"
  sig="$(printf '%s' "$payload" | _hmac)"
  curl -fsS -X POST "$PUBLIC_HOST$path" \
    -H "Authorization: Bearer $API_BEARER_TOKEN" \
    -H "Content-Type: application/json" \
    -H "X-Timestamp: $ts" -H "X-Nonce: $nonce" -H "X-Signature: $sig" \
    --data-binary "$body"
}

sign_get(){ # usage: sign_get /path?query
  local path="$(_norm "${1:?}")"
  local ts nonce payload sig
  ts="$(date +%s)"; nonce="$(cat /proc/sys/kernel/random/uuid)"
  payload="GET
$path

$ts
$nonce"
  sig="$(printf '%s' "$payload" | _hmac)"
  curl -fsS "$PUBLIC_HOST$path" \
    -H "Authorization: Bearer $API_BEARER_TOKEN" \
    -H "X-Timestamp: $ts" -H "X-Nonce: $nonce" -H "X-Signature: $sig"
}

alias sp='sign_post'
alias sg='sign_get'
BASH
chmod 755 /app/ops_toolkit.sh

# status.sh — בדיקות חיים מהירות
cat >/app/status.sh <<'BASH'
#!/usr/bin/env bash
set -euo pipefail
BASE="${PUBLIC_HOST:-http://localhost:10000}"
echo "# /readyz";               curl -fsS "$BASE/readyz"; echo; echo
echo "# /health";               curl -fsS "$BASE/health"; echo; echo
echo "# /ops/manager/health";   curl -fsS "$BASE/ops/manager/health"; echo; echo
echo "# /ops/ui/pending (HTML)"; curl -fsS -H "Authorization: Bearer ${API_BEARER_TOKEN:-}" "$BASE/ops/ui/pending" || true; echo
BASH
chmod 755 /app/status.sh
