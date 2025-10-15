cat >/app/status.sh <<'BASH'
#!/usr/bin/env bash
set -euo pipefail
: "${PUBLIC_HOST:?need PUBLIC_HOST}"
: "${API_BEARER_TOKEN:?need API_BEARER_TOKEN}"
: "${OPS_SIGN_SECRET:?need OPS_SIGN_SECRET}"
SYMBOL="${1:?usage: status.sh SYMBOL}"

ts=$(date +%s)
nonce=$(cat /proc/sys/kernel/random/uuid)
route="/position-ops/status?symbol=$SYMBOL"
# אין גוף -> canon של מחרוזת ריקה
canon=""
hsh=$(printf "%s" "$canon" | openssl dgst -sha256 -r | awk '{print $1}')
base="$ts.$nonce.$route.$hsh"
sig=$(printf "%s" "$base" | openssl dgst -sha256 -hmac "$OPS_SIGN_SECRET" -r | awk '{print $1}')

curl -sS -X GET "$PUBLIC_HOST$route" \
  -H "Authorization: Bearer $API_BEARER_TOKEN" \
  -H "X-Timestamp: $ts" -H "X-Nonce: $nonce" -H "X-Signature: $sig"
BASH
chmod +x /app/status.sh

