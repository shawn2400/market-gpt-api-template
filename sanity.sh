#!/usr/bin/env bash
set -euo pipefail

# טען .env אם קיים
[ -f .env ] && source .env

BASE="${BASE_URL:-http://127.0.0.1:10000}"
TOKEN="${API_BEARER_TOKEN:-}"
SIGN="${OPS_SIGN_SECRET:-}"
CHAT="${TELEGRAM_CHAT_ID:-}"
SYMBOL="${TEST_SYMBOL:-BTCUSDT}"
SIDE="${TEST_SIDE:-BUY}"
LEV="${TEST_LEVERAGE:-5}"
QTY="${TEST_QTY:-0}"   # ב-AUTO_QTY לא חובה

red()   { printf "\033[31m%s\033[0m\n" "$*"; }
green() { printf "\033[32m%s\033[0m\n" "$*"; }
blue()  { printf "\033[34m%s\033[0m\n" "$*"; }
bold()  { printf "\033[1m%s\033[0m\n" "$*"; }

need() {
  local name="$1" val="${!1:-}"
  if [ -z "$val" ]; then red "חסר משתנה סביבה: $name"; exit 1; fi
}
need BASE_URL
need API_BEARER_TOKEN
need OPS_SIGN_SECRET
need TELEGRAM_CHAT_ID

ts() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }

step() { echo; blue "==> $*"; }

json() { jq -r "$1"; }

sign_hmac() {
  # חותם HEX של SHA256 על payload גולמי
  payload="$1"
  # אם המפתח הוא HEX (64 תווים) אפשר ישירות; openssl מקבל מחרוזת
  printf "%s" "$payload" \
    | openssl dgst -sha256 -hmac "$SIGN" -binary \
    | xxd -p -c 256
}

ok_or_die() {
  local code="$1" msg="$2"
  if [[ "$code" -ge 200 && "$code" -lt 300 ]]; then
    green "$msg"
  else
    red "$msg (HTTP $code)"
    exit 1
  fi
}

step "1) בריאות שרת: $BASE/health"
code=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/health")
ok_or_die "$code" "שרת חי"

# אופציונלי—לא בכל דיפלוימנט קיים הנתיב הזה
if curl -s "$BASE/telegram/ping" >/dev/null 2>&1; then
  step "2) פינג לטלגרם: $BASE/telegram/ping"
  code=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/telegram/ping")
  ok_or_die "$code" "בוט טלגרם מגיב"
else
  blue "2) דילוג על telegram/ping (נתיב לא קיים—זה תקין)"
fi

TICKET_ID="T_$(date +%s)_$RANDOM"
step "3) יצירת כרטיס מועמד -> /ops/ticket   (TICKET_ID=$TICKET_ID)"
PAYLOAD_CREATE=$(jq -nc \
  --arg tid "$TICKET_ID" \
  --arg sym "$SYMBOL" \
  --arg side "$SIDE" \
  --arg lev "$LEV" \
  --arg qty "$QTY" \
  --arg note "[mode: HYBRID] sanity-run $(ts)" \
  '{ticket_id:$tid,symbol:$sym,side:$side,leverage:($lev|tonumber),qty:($qty|tonumber),note:$note,"tp1":null,"tp2":null,"tp3":null,"sl":null}')
RESP_CREATE=$(curl -sS -X POST "$BASE/ops/ticket" -H "content-type: application/json" -d "$PAYLOAD_CREATE")
echo "$RESP_CREATE" | jq .
if [[ "$(echo "$RESP_CREATE" | jq -r '.ok')" != "true" ]]; then
  red "יצירת כרטיס נכשלה"; exit 1
fi
APPROVE_URL=$(echo "$RESP_CREATE" | jq -r '.approve_url')

step "4) אישור חתום (HMAC) -> /ops/approve/signed"
# אותו טיקט, אבל אחרי sizing אוטומטי השרת יחשב QTY/LV אם צריך
PAYLOAD_APPROVE=$(jq -nc \
  --arg tid "$TICKET_ID" \
  --arg sym "$SYMBOL" \
  --arg side "$SIDE" \
  --arg lev "$LEV" \
  --arg qty "$QTY" \
  --arg note "[mode: HYBRID] sanity-approve $(ts)" \
  '{ticket_id:$tid,symbol:$sym,side:$side,leverage:($lev|tonumber),qty:($qty|tonumber),note:$note}')
SIG=$(sign_hmac "$PAYLOAD_APPROVE")
RESP_APPROVE=$(curl -sS -w "\n%{http_code}" -X POST "$BASE/ops/approve/signed" \
  -H "content-type: application/json" \
  -H "X-Signature: $SIG" \
  -d "$PAYLOAD_APPROVE")
BODY="$(echo "$RESP_APPROVE" | head -n -1)"
CODE="$(echo "$RESP_APPROVE" | tail -n1)"
echo "$BODY" | jq .
ok_or_die "$CODE" "אושר בהצלחה (flow=$(echo "$BODY" | jq -r '.flow'))"

step "5) ניהול דינמי -> /position-ops/manage-once  (סובלני ל-204/409)"
MANAGE_PAY='{"symbol":"'"$SYMBOL"'"}'
RESP_MANAGE=$(curl -sS -w "\n%{http_code}" -X POST "$BASE/position-ops/manage-once" \
  -H "authorization: Bearer $TOKEN" \
  -H "content-type: application/json" \
  -d "$MANAGE_PAY")
MBODY="$(echo "$RESP_MANAGE" | head -n -1)"
MCODE="$(echo "$RESP_MANAGE" | tail -n1)"
case "$MCODE" in
  200|201|202|204)
    green "ניהול בוצע (HTTP $MCODE)";;
  304|409)
    blue  "אין מה לנהל/כבר מנוהל (HTTP $MCODE) – זה תקין";;
  *)
    echo "$MBODY"
    red "קריאת ניהול נכשלה (HTTP $MCODE)"; exit 1;;
esac

echo
bold "✓ סיום: הכול תקין. תראה הודעות בטלגרם עבור הכרטיס והאישור."
echo "   אם לא הופיעו בלייב, בדוק:"
echo "   - TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID"
echo "   - REQUIRE_TELEGRAM_APPROVAL=1, SCAN_CRON_ENABLE=1 (לסורק אוטומטי)"
echo "   - חותמת HMAC: OPS_SIGN_SECRET (בדיוק כמו בשרת)"
