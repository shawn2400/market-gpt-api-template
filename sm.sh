cat > /app/sm.sh <<'SH'
sm() {
  BODY="$1"
  TS="$(date +%s)"
  NONCE="$(openssl rand -hex 8)"
  SIG="$(printf "%s.%s.%s" "$TS" "$NONCE" "$BODY" | \
        openssl dgst -sha256 -mac HMAC -macopt hexkey:$SECRET_HEX | awk '{print $2}')"
  curl -sS -X POST "$HOST/manage-once" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -H "X-Timestamp: $TS" -H "X-Nonce: $NONCE" -H "X-Signature: $SIG" \
    --data "$BODY"
}
SH
. /app/sm.sh

