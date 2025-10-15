#!/usr/bin/env bash
# /app/status.sh — סטטוס פוזיציה + ה־TP/SL/TRAIL הפתוחים
set -euo pipefail
: "${PUBLIC_HOST:?need PUBLIC_HOST}"
: "${API_BEARER_TOKEN:?need API_BEARER_TOKEN}"
: "${OPS_SIGN_SECRET:?or set API_SIGNING_SECRET}"
SIGN_SECRET="${OPS_SIGN_SECRET:-${API_SIGNING_SECRET:-}}"

sym="${1:?usage: status.sh SYMBOL}"

# חתימה זהה לשרת: base = ts.nonce.route.sha256(canon_json), route בלי query
ts="$(date +%s)"
nonce="$(cat /proc/sys/kernel/random/uuid)"
canon='{"symbol":"'"${sym}"'"}'
hash=$(printf "%s" "${canon}" | python3 -c 'import sys,json,hashlib; s=sys.stdin.read(); 
import json as j
try: o=j.loads(s); s=j.dumps(o, separators=(",",":"), sort_keys=True, ensure_ascii=False)
except: pass
print(hashlib.sha256(s.encode()).hexdigest())')
base="${ts}.${nonce}./position-ops/status.${hash}"
sig=$(printf "%s" "${base}" | openssl dgst -sha256 -hmac "${SIGN_SECRET}" -r | awk '{print $1}')

curl -sS -X GET "${PUBLIC_HOST}/position-ops/status?symbol=${sym}" \
  -H "Authorization: Bearer ${API_BEARER_TOKEN}" \
  -H "X-Timestamp: ${ts}" \
  -H "X-Nonce: ${nonce}" \
  -H "X-Signature: ${sig}"


