cat >/app/status.sh <<'BASH'
#!/usr/bin/env bash
set -euo pipefail
: "${PUBLIC_HOST:?need PUBLIC_HOST}"
: "${API_BEARER_TOKEN:?need API_BEARER_TOKEN}"
SIGN_SECRET="${OPS_SIGN_SECRET:-${API_SIGNING_SECRET:-}}"
: "${SIGN_SECRET:?need OPS_SIGN_SECRET or API_SIGNING_SECRET}"

sym="${1:?usage: status.sh SYMBOL}"

ts="$(date +%s)"
nonce="$(cat /proc/sys/kernel/random/uuid)"
body='{"symbol":"'"${sym}"'"}'

canon=$(python3 - <<PY
import json
s=${body!r}
o=json.loads(s)
print(json.dumps(o, separators=(",",":"), sort_keys=True, ensure_ascii=False))
PY
)
hash=$(printf "%s" "${canon}" | openssl dgst -sha256 -r | awk '{print $1}')
base="${ts}.${nonce}./position-ops/status.${hash}"
sig=$(printf "%s" "${base}" | openssl dgst -sha256 -hmac "${SIGN_SECRET}" -r | awk '{print $1}')

curl -sS -X GET "${PUBLIC_HOST}/position-ops/status?symbol=${sym}" \
  -H "Authorization: Bearer ${API_BEARER_TOKEN}" \
  -H "X-Timestamp: ${ts}" \
  -H "X-Nonce: ${nonce}" \
  -H "X-Signature: ${sig}" | python3 -m json.tool
BASH
chmod +x /app/status.sh




