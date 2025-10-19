# ==== algo_min.sh (ללא jq) ====
# שימוש:
#   export API_BEARER_TOKEN=...           # חובה למסלולי approve
#   export API_BEARER_TOKEN_RO=...        # רשות; לקריאות public אם מוגנות
#   source ./algo_min.sh
#   trade1 ETHUSDT
#   batch3

# ---- בסיס / טוקנים ----
API_BASE="${API_BASE:-http://127.0.0.1:${PORT:-10000}}"

ACTION_TOKEN="${API_BEARER_TOKEN:-${API_BEARER_TOKEN_ACTION:-}}"
RO_TOKEN="${API_BEARER_TOKEN_RO:-${ACTION_TOKEN:-}}"

auth_action=(); [ -n "$ACTION_TOKEN" ] && auth_action=(-H "Authorization: Bearer $ACTION_TOKEN")
auth_ro=();     [ -n "$RO_TOKEN" ]     && auth_ro=(-H "Authorization: Bearer $RO_TOKEN")

# ---- בדיקות בריאות ----
ready() { curl -fsS "$API_BASE/readyz/strict" >/dev/null; }
ready || { echo "[!] service not ready"; return 1 2>/dev/null || exit 1; }

# ---- עוגן BTC → BUY/SELL גס (אם נכשל: BUY) ----
bias() {
  d="$(curl -fsS 'https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=1m&limit=61' 2>/dev/null || true)"
  first="$(printf '%s' "$d" | sed 's/\[\[/\n\[\[/g' | head -n1 | grep -o '\[[^]]*\]' | head -n1 | tr -d '[]' | awk -F',' '{print $5}')"
  last="$( printf '%s' "$d" | sed 's/\],\[/\n/g'       | tail -n1 | tr -d '[]' | awk -F',' '{print $5}')"
  [ -n "$first" ] && [ -n "$last" ] && awk -v a="$first" -v b="$last" 'BEGIN{print (b>=a)?"BUY":"SELL"}' || echo BUY
}

# ---- שליפת מועמדים (TOPK) – תומך גם אם public דורש Bearer ----
tops() {
  curl -fsS "${auth_ro[@]}" "$API_BASE/scan/public-topk?k=10" \
   | grep -o '"symbol":"[^"]*"' | cut -d'"' -f4 \
   | grep -E 'USDT$' | grep -v '^BTCUSDT$' | head -n 3
}

# ---- יצירת טיקט והחזרת ה-id ----
ticket() {
  body="$1"
  resp="$(curl -fsS -H 'Content-Type: application/json' -d "$body" "$API_BASE/ops/ticket" 2>/dev/null || true)"
  printf '%s' "$resp" | grep -o '"ticket_id":"[^"]*"' | head -n1 | cut -d'"' -f4
}

# ---- אישור טיקט (תמיד עם ?id= כדי לא לקבל 422) ----
approve() {
  tid="$1"; [ -z "$tid" ] && return 2
  curl -fsS "${auth_action[@]}" "$API_BASE/ops/approve?id=$tid" >/dev/null
}

# ---- טרייד יחיד (ניהול HYBRID אוטומטי אחרי אישור) ----
trade1() {
  s="$1"; [ -z "$s" ] && { echo "usage: trade1 SYMBOL"; return 2; }
  sd="$(bias)"
  note="[mode: HYBRID] anchor=BTC"
  body=$(printf '{"symbol":"%s","side":"%s","note":"%s"}' "$s" "$sd" "$note")

  tid="$(ticket "$body")"
  if [ -z "$tid" ]; then
    echo "❌ ticket_id not returned"; return 1
  fi

  if approve "$tid"; then
    echo "✅ approved $s ($sd) [tid=$tid]"
  else
    echo "❌ approve failed (בדוק API_BEARER_TOKEN / הרשאות)"; return 1
  fi
}

# ---- עד 3 מועמדים חמים ----
batch3() { tops | while read -r s; do [ -n "$s" ] && trade1 "$s"; sleep 1; done; }

# ---- בדיקות מהירות ----
echo "[ok] readyz/strict ok"
[ -n "$ACTION_TOKEN" ] || echo "[i] אין ACTION token בסביבה — approve ייכשל (401)"
