#!/usr/bin/env bash
set -euo pipefail

# === קונפיג קצר להרצה מקומית בתוך הקונטיינר/שירות ===
BASE="${BASE:-http://127.0.0.1:${PORT:-10000}}"
TOKEN="${API_BEARER_TOKEN:-}"   # אם הוגדר – נשלב Authorization

_auth_hdr() {
  if [ -n "$TOKEN" ]; then
    printf "Authorization: Bearer %s" "$TOKEN"
  fi
}

say() { printf "\n==> %s\n" "$*"; }

# 1) Trigger בלבד – יצירת מועמד (תגיע הודעה לטלגרם עם כפתורי אישור)
trigger_only() {
  say "Trigger candidate (BTCUSDT BUY 5x)..."
  curl -sS -X POST "$BASE/debug/trigger-candidate" \
    -H "Content-Type: application/json" \
    -H "$(_auth_hdr)" \
    --data '{"symbol":"BTCUSDT","side":"BUY","leverage":5,"budget":50,"tp1":null,"tp2":null,"tp3":null,"sl":null,"note":"[mode: HYBRID] sanity trigger","score":7.5,"prob_overall_pct":60}'
  echo
}

# 2) Trigger+Approve – יוצר ומאשר חתום מיד (בודק את כל הזרימה)
trigger_and_approve() {
  say "Trigger AND Signed-Approve (BTCUSDT BUY 5x)..."
  curl -sS -X POST "$BASE/debug/trigger-and-approve" \
    -H "Content-Type: application/json" \
    -H "$(_auth_hdr)" \
    --data '{"symbol":"BTCUSDT","side":"BUY","leverage":5,"budget":50,"note":"[mode: HYBRID] sanity auto-approve","reduce_only":false}'
  echo
}

# 3) קריאת ניהול ידנית פעם אחת (צפוי 204/409)
manage_once() {
  SYM="${1:-BTCUSDT}"
  say "Manual manage-once for $SYM ..."
  curl -sS -X POST "$BASE/debug/manage-once" \
    -H "Content-Type: application/json" \
    -H "$(_auth_hdr)" \
    --data "{\"symbol\":\"$SYM\"}"
  echo
}

case "${1:-}" in
  trigger) trigger_only ;;
  approve) trigger_and_approve ;;
  manage)  manage_once "${2:-BTCUSDT}" ;;
  *)
    echo "Usage: $0 {trigger|approve|manage [SYMBOL]}"
    exit 1
  ;;
esac
