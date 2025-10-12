curl -sS "$HOST/ops/manager/health" -H "Authorization: Bearer $TOKEN"
# ואז:
sm() {
  BODY="$1"; TS="$(date +%s)"; NONCE="$(openssl rand -hex 8)"
  SIG="$(printf "%s.%s.%s" "$TS" "$NONCE" "$BODY" | openssl dgst -sha256 -mac HMAC -macopt hexkey:$SECRET_HEX | awk '{print $2}')"
  curl -sS -X POST "$HOST/manage-once" \
    -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    -H "X-Timestamp: $TS" -H "X-Nonce: $NONCE" -H "X-Signature: $SIG" \
    --data "$BODY"
}
sm '{"symbol":"BTCUSDT","offset_bps":6,"pcts":[3,6,12],"splits":[0.25,0.25,0.50],"atr_mult":2.3}'
