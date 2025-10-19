#!/usr/bin/env bash
set -euo pipefail

# פרמטרים נדרשים מהסביבה:
# SECRET_HEX – המפתח ב-HEX (64 תווים)
# NS         – בדיוק מהאפליקציה (למשל ops-supervisor-web)
# PATH_TO_SIGN – הנתיב המדויק: /ops/approve/signed | /ops/reject/signed | /ops/ui/ticket/signed
# TID        – ticket_id
# EXP        – זמן תפוגה (epoch seconds)

: "${SECRET_HEX:?need SECRET_HEX}"
: "${NS:?need NS}"
: "${PATH_TO_SIGN:?need PATH_TO_SIGN}"
: "${TID:?need TID}"
: "${EXP:?need EXP}"

PAYLOAD="${PATH_TO_SIGN}|${TID}|${EXP}|${NS}"

# הפלט של openssl נראה כך: "(stdin)= abcd1234..."
# נקלף את החלק שלפני ה-"= "
SIG="$(printf "%s" "$PAYLOAD" \
  | openssl dgst -sha256 -mac HMAC -macopt hexkey:"$SECRET_HEX" -hex \
  | sed 's/^.*= //')"

echo "$SIG"
