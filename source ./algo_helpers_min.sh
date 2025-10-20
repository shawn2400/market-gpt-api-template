# === בסיס: כתובות וטוקנים ===
export API_BASE="${API_BASE:-http://127.0.0.1:${PORT:-10000}}"

API_BEARER_TOKEN_ACTION="${API_BEARER_TOKEN_ACTION:-${API_BEARER_TOKEN:-}}"
API_BEARER_TOKEN_RO="${API_BEARER_TOKEN_RO:-${API_BEARER_TOKEN:-}}"

auth_action=()
auth_ro=()
[ -n "$API_BEARER_TOKEN_ACTION" ] && auth_action=(-H "Authorization: Bearer $API_BEARER_TOKEN_ACTION")
[ -n "$API_BEARER_TOKEN_RO" ]      && auth_ro=(-H "Authorization: Bearer $API_BEARER_TOKEN_RO")

ready() { curl -fsS "$API_BASE/readyz" >/dev/null && echo "ready" || { echo "NOT READY"; return 1; }; }

approve_selftest() {
  code="$(curl -sS -o /dev/null -w '%{http_code}' -X POST "${auth_action[@]}" "$API_BASE/ops/approve?id=0")"
  case "$code" in
    422) echo "approve route OK (POST + Authorization תקינים, id חסר/שגוי כצפוי)";;
    401) echo "❌ 401 – בדוק API_BEARER_TOKEN_ACTION"; return 1;;
    404) echo "❌ 404 – הנתיב לא קיים בסרוויס"; return 1;;
    405) echo "❌ 405 – נשלח לא ב-POST"; return 1;;
    *)   echo "⚠️ קיבלתי $code";;
  esac
}

approve_id() {
  id="$1"; [ -z "$id" ] && { echo "צריך id"; return 2; }
  curl -sS -X POST "${auth_action[@]}" "$API_BASE/ops/approve?id=$id" | sed -e 's/^[[:space:]]\+//'
}

trade1() {
  sym="${1:-ETHUSDT}"
  curl -fsS "${auth_action[@]}" \
    "$API_BASE/manager/auto?symbol=$sym&mode=hybrid&market=futures" \
    || echo "⚠️ manager/auto נכשל – ודא שהנתיב קיים וה-token נכון"
}

tops() {
  curl -fsS "${auth_ro[@]}" "$API_BASE/scan/public-topk?limit=3" \
    | tr '{},' '\n' | sed -n 's/.*"symbol":"\([^"]\+\)".*/\1/p' | head -n3
}

batch3() { tops | while read -r s; do [ -n "$s" ] && trade1 "$s"; sleep 1; done; }

bias() {
  url='https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=1m&limit=61'
  d="$(curl -fsS "$url" 2>/dev/null)" || { echo BUY; return; }
  last="$(printf '%s\n' "$d" | tr -d '[]' | awk -F',' 'END{print $(NF-2)}')"
  first="$(printf '%s\n' "$d" | tr -d '[]' | awk -F',' 'NR==1{print $(NF-2)}')"
  awk -v f="$first" -v l="$last" 'BEGIN{print (l>=f)?"BUY":"SELL"}'
}
