# ========= בסיס: בדיקות ואיתחול =========
set -euo pipefail

echo "# readyz";  curl -fsS "$PUBLIC_HOST/readyz" && echo OK
echo "# health";  curl -fsS "$PUBLIC_HOST/health"
echo "# mgr   ";  curl -fsS "$PUBLIC_HOST/ops/manager/health"

# ===== יצירת /app/status.sh =====
cat >/app/status.sh <<'BASH'
#!/usr/bin/env bash
set -euo pipefail
BASE="${PUBLIC_HOST:-http://localhost:10000}"
hdr(){ printf "\n# %s\n" "$1"; }
hdr "/readyz";             curl -fsS "$BASE/readyz"; echo
hdr "/health";             curl -fsS "$BASE/health"; echo
hdr "/ops/manager/health"; curl -fsS "$BASE/ops/manager/health"; echo
hdr "/ops/ui/pending";     curl -fsS -H "Authorization: Bearer ${API_BEARER_TOKEN:-}" "$BASE/ops/ui/pending" || true; echo
BASH
sed -i 's/\r$//' /app/status.sh 2>/dev/null || true
chmod 755 /app/status.sh

# ראוטים זמינים (לא חובה, עוזר לוודא):
echo "# routes:"; curl -fsS "$PUBLIC_HOST/openapi.json" | grep -o '"/position-ops/[^"]*' | sort || true

# ===== פונקציית חתימה כללית =====
sign_call() {
  # שימוש: sign_call "/path" '{"json":"compact"}' [METHOD]
  local path="$1"
  local body="${2:-{}}"
  local method="${3:-POST}"   # POST / GET
  : "${PUBLIC_HOST:?need PUBLIC_HOST}"
  : "${API_BEARER_TOKEN:?need API_BEARER_TOKEN}"
  : "${OPS_SIGN_SECRET:?need OPS_SIGN_SECRET}"
  local ts nonce payload sig
  ts="$(date +%s)"
  nonce="$(cat /proc/sys/kernel/random/uuid)"
  payload="$(printf '%s\n%s\n%s\n%s\n%s' "$method" "$path" "$body" "$ts" "$nonce")"
  sig="$(printf '%s' "$payload" | openssl dgst -sha256 -hmac "$OPS_SIGN_SECRET" -r | awk '{print $1}')"
  if [ "$method" = "GET" ]; then
    curl -fsS -X GET "$PUBLIC_HOST$path" \
      -H "Authorization: Bearer $API_BEARER_TOKEN" \
      -H "X-Timestamp: $ts" -H "X-Nonce: $nonce" -H "X-Signature: $sig"
  else
    curl -fsS -X "$method" "$PUBLIC_HOST$path" \
      -H "Authorization: Bearer $API_BEARER_TOKEN" \
      -H "Content-Type: application/json" \
      -H "X-Timestamp: $ts" -H "X-Nonce: $nonce" -H "X-Signature: $sig" \
      --data-binary "$body"
  fi
}

# ========= ריצות לדוגמה =========

# סטטוס כללי
bash /app/status.sh

# Status (GET חתום; שים לב שהחתימה כוללת body זהה)
sign_call "/position-ops/status?symbol=BTCUSDT" '{"symbol":"BTCUSDT"}' GET; echo

# BE (ברירת מחדל 8 bps)
sign_call "/position-ops/be" '{"symbol":"BTCUSDT","offset_bps":8}'; echo

# Trailing: ATR או קבוע
sign_call "/position-ops/trail" '{"symbol":"BTCUSDT","atr_mult":1.2}'; echo
sign_call "/position-ops/trail" '{"symbol":"BTCUSDT","callbackRate":1.0}'; echo

# ביטול Trailing בלבד
sign_call "/position-ops/trail/cancel" '{"symbol":"BTCUSDT"}'; echo

# TP אחד: אחוז או מחיר
sign_call "/position-ops/tp/one" '{"symbol":"BTCUSDT","pct":2.5}'; echo
# sign_call "/position-ops/tp/one" '{"symbol":"BTCUSDT","price":117663.3}'; echo

# TP Ladder
sign_call "/position-ops/tp/ladder" '{"symbol":"BTCUSDT","pcts":[3,6,12],"splits":[0.25,0.25,0.5]}'; echo

# ביטול כל ה-TPs
sign_call "/position-ops/tp/cancel" '{"symbol":"BTCUSDT"}'; echo

# SL למחיר קבוע
sign_call "/position-ops/sl/move" '{"symbol":"BTCUSDT","price":12345.6}'; echo

# סגירת חלק מהפוזיציה (למשל 25%)
sign_call "/position-ops/close" '{"symbol":"BTCUSDT","fraction":0.25}'; echo

# One-shot: BE + TRAIL + TP-ladder
sign_call "/position-ops/manage-once" '{"symbol":"BTCUSDT","do":["be","trail","tp_ladder"],"offset_bps":8,"atr_mult":1.2,"pcts":[3,6,12],"splits":[0.25,0.25,0.5]}'; echo

# Auto loop (דורש AUTO_MOVE_ENABLE=1)
sign_call "/position-ops/auto/start" '{"symbols":["BTCUSDT"],"every_sec":20,"steps":["be","trail","tp_ladder"],"offset_bps":8,"atr_mult":1.2}'; echo
sign_call "/position-ops/auto/stop" '{}'; echo

# UI Pending (Bearer בלבד)
curl -fsS -H "Authorization: Bearer $API_BEARER_TOKEN" "$PUBLIC_HOST/ops/ui/pending" && echo









