# === בסיס: כתובות וטוקנים ===
export API_BASE="${API_BASE:-http://127.0.0.1:${PORT:-10000}}"

# ברנדר יש לך שלושה סודות; לאן לפנות עבור approve זה ACTION:
# API_BEARER_TOKEN_ACTION (לפעולות), API_BEARER_TOKEN_RO (לקריאה), API_BEARER_TOKEN (כללי)
# בחר אוטומטית מהזמין:
API_BEARER_TOKEN_ACTION="${API_BEARER_TOKEN_ACTION:-${API_BEARER_TOKEN:-}}"
API_BEARER_TOKEN_RO="${API_BEARER_TOKEN_RO:-${API_BEARER_TOKEN:-}}"

# בנה מערכי כותרות (ללא jq)
auth_action=()
auth_ro=()
[ -n "$API_BEARER_TOKEN_ACTION" ] && auth_action=(-H "Authorization: Bearer $API_BEARER_TOKEN_ACTION")
[ -n "$API_BEARER_TOKEN_RO" ]      && auth_ro=(-H "Authorization: Bearer $API_BEARER_TOKEN_RO")

# ===== בדיקת מוכנות =====
ready() {
  curl -fsS "$API_BASE/readyz" >/dev/null && echo "ready" || { echo "NOT READY"; return 1; }
}

# ===== בדיקת הרשאת approve: חייב POST, ו故 נצפה ל-422 עם id=0 =====
approve_selftest() {
  code="$(curl -sS -o /dev/null -w '%{http_code}' -X POST "${auth_action[@]}" "$API_BASE/ops/approve?id=0")"
  case "$code" in
    422) echo "approve route OK (POST + Authorization תקינים, id חסר/שגוי כצפוי)";;
    401) echo "❌ 401 – בדוק API_BEARER_TOKEN_ACTION"; return 1;;
    404) echo "❌ 404 – בדוק את הנתיב (האם /ops/approve קיים אצלך?)"; return 1;;
    405) echo "❌ 405 – אתה שולח לא ב-POST"; return 1;;
    *)   echo "⚠️ קיבלתי $code";;
  esac
}

# ===== אישור ידני לפי מזהה טיקט שקיבלת בטלגרם =====
# דוגמה: approve_id 123456
approve_id() {
  id="$1"
  [ -z "$id" ] && { echo "צריך id"; return 2; }
  curl -sS -X POST "${auth_action[@]}" "$API_BASE/ops/approve?id=$id" | sed -e 's/^[[:space:]]\+//'
}

# ===== דוגמת טרייד אחרי אישור (HYBRID) =====
# מניח שיש לך ראוט ציבורי לפתיחה/ניהול אחרי אישור (אצלך MODE=hybrid)
# אם הראוט שלך שונה – החלף את הנתיב.
trade1() {
  sym="${1:-ETHUSDT}"
  # קריאת ניהול היברידי (דוגמה נפוצה; אם אצלך הנתיב שונה, עדכן):
  curl -fsS "${auth_action[@]}" \
    "$API_BASE/manager/auto?symbol=$sym&mode=hybrid&market=futures" \
    || echo "⚠️ manager/auto נכשל – ודא שהנתיב קיים ושה־token נכון"
}

# ===== מועמדים – בלי jq (TOP מהסריקה הציבורית) =====
# מחזיר עד 3 סמלים עם נפח/סיכוי גבוה לפי ה־API הציבורי שלך
tops() {
  # אם אין לך את המסלול הזה – החלף ל-/scan/public-now?limit=... (מה שמוגדר אצלך כ-public)
  curl -fsS "${auth_ro[@]}" "$API_BASE/scan/public-topk?limit=3" \
    | tr '{},' '\n' | sed -n 's/.*"symbol":"\([^"]\+\)".*/\1/p' | head -n3
}

batch3() { tops | while read -r s; do [ -n "$s" ] && trade1 "$s"; sleep 1; done; }

# ===== BTC bias פשוט (לעוגן כיוון) – אם נופל, ברירת־מחדל BUY =====
bias() {
  url='https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=1m&limit=61'
  d="$(curl -fsS "$url" 2>/dev/null)" || { echo BUY; return; }
  # לקט את מחיר הסגירה של הנר ה-1 וה-60 (בלי jq)
  last="$(printf '%s\n' "$d" | tr -d '[]' | awk -F',' 'END{print $(NF-2)}')"       # close אחרון
  first="$(printf '%s\n' "$d" | tr -d '[]' | awk -F',' 'NR==1{print $(NF-2)}')"    # close ראשון
  # אם עלה ⇒ BUY, אחרת SELL
  awk -v f="$first" -v l="$last" 'BEGIN{print (l>=f)?"BUY":"SELL"}'
}
