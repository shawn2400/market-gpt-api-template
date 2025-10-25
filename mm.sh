cat > mm.sh <<'SH'
#!/usr/bin/env bash
: "${BASE_URL:?}"; : "${API_BEARER_TOKEN:?}"; : "${SYMBOL:?}"
curl -fsS -X POST "$BASE_URL/manage-once" \
  -H "Authorization: Bearer $API_BEARER_TOKEN" -H "Content-Type: application/json" \
  -d "{\"symbol\":\"$SYMBOL\",\"be_bps\":${BE_BPS:-5},\"trail_offset_bps\":${TRAIL_BPS:-30},\"place_tps\":${PLACE_TPS:-true},\"tp_pcts\":[3,6,10,16],\"tp_splits\":[0.25,0.25,0.25,0.25],\"working_trigger\":\"mark\"}"
echo
SH
chmod +x mm.sh
