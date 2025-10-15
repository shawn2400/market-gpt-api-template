#!/usr/bin/env bash
# ------------------------------------------------------------
# Approve/Reject Ticket via signed ops endpoint
# שימוש:
#   bash scripts/approve_via_telegram.sh "<BASE_URL>" "<TICKET_ID>" "<approve|reject>" "<WEBHOOK_HMAC_SECRET>" "<reason (optional)>"
# דוגמא:
#   bash scripts/approve_via_telegram.sh "https://algogpt-docker.onrender.com" "TCKT-abc123" "approve" "MY_WEBHOOK_HMAC" "go go go"
# הערות:
#   - הסקריפט פונה ל־/ops/approve/signed כפי שמוגדר ב־SECURITY_PUBLIC_PATHS.
#   - חתימה לפי WEBHOOK_HMAC_SECRET (אותו מפתח שמופיע ב־env: WEBHOOK_HMAC_SECRET).
# ------------------------------------------------------------
set -Eeuo pipefail

BASE_URL="${1:-}"
TICKET_ID="${2:-}"
ACTION="${3:-approve}"   # approve | reject
WEBHOOK_SECRET="${4:-${WEBHOOK_HMAC_SECRET:-}}"
REASON="${5:-Approved via script}"

[[ -z "$BASE_URL" || -z "$TICKET_ID" || -z "$WEBHOOK_SECRET" ]] && {
  echo "Usage: $0 <BASE_URL> <TICKET_ID> <approve|reject> <WEBHOOK_HMAC_SECRET> [reason]"
  exit 2
}

# Colors
if [[ -t 1 ]]; then G='\033[0;32m'; R='\033[0;31m'; Y='\033[1;33m'; N='\033[0m'; else G=''; R=''; Y=''; N=''; fi
ok(){ echo -e "${G}OK${N}   - $1"; }
warn(){ echo -e "${Y}WARN${N} - $1"; }
fail(){ echo -e "${R}FAIL${N} - $1"; exit 1; }

PY=python3; command -v python3 >/dev/null 2>&1 || { command -v python >/dev/null 2>&1 && PY=python; }

BODY="$(jq -nc --arg id "$TICKET_ID" --arg act "$ACTION" --arg rsn "$REASON" '{ticket_id:$id, action:$act, reason:$rsn}')" || {
  # fallback בלי jq
  BODY="{\"ticket_id\":\"${TICKET_ID}\",\"action\":\"${ACTION}\",\"reason\":\"${REASON}\"}"
}

TS="$(date +%s)"
SIG="$("$PY" - <<'PY' 2>/dev/null
import os,hmac,hashlib,sys
sec=os.environ.get("WEBHOOK_SECRET",""); ts=os.environ.get("TS",""); body=os.environ.get("BODY","").encode()
if not sec or not ts: sys.exit(1)
print(hmac.new(sec.encode(), ts.encode()+b"."+body, hashlib.sha256).hexdigest())
PY
)" WEBHOOK_SECRET="$WEBHOOK_SECRET" TS="$TS" BODY="$BODY"

[[ -z "$SIG" ]] && fail "signature failed"

URL="${BASE_URL%/}/ops/approve/signed"
resp="$(curl -fsS -X POST "$URL" -H "Content-Type: application/json" -H "X-Timestamp: ${TS}" -H "X-Signature: ${SIG}" -d "$BODY" || true)"
code="$(curl -fsS -o /dev/null -w "%{http_code}" -X POST "$URL" -H "Content-Type: application/json" -H "X-Timestamp: ${TS}" -H "X-Signature: ${SIG}" -d "$BODY" || true)"

if [[ "$code" == "200" || "$code" == "202" ]]; then
  ok "approve API ($ACTION) sent for ticket $TICKET_ID"
  echo "$resp"
  exit 0
else
  warn "approve API returned $code"
  echo "$resp"
  exit 1
fi
