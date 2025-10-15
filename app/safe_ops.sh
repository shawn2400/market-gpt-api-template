# === יצירה/דריסה של /app/safe_ops.sh (גרסה מעודכנת עם manage-once-lite, tp-ladder, trail-off, status, open-top) ===
cat > /app/safe_ops.sh <<'BASH'
#!/usr/bin/env bash
set -euo pipefail

: "${PUBLIC_HOST:?need PUBLIC_HOST}"
: "${API_BEARER_TOKEN:?need API_BEARER_TOKEN}"
: "${OPS_SIGN_SECRET:?need OPS_SIGN_SECRET}"

CURL_BIN="${CURL_BIN:-curl}"
OPENSSL_BIN="${OPENSSL_BIN:-openssl}"
MAX_TIME="${MAX_TIME:-10}"
UA="safe_ops.sh/1.2"

BUCKET="${BUCKET_FILE:-/tmp/anti1003_bucket.ops}"
CAP=${BUCKET_CAP:-30}
WINDOW=${BUCKET_WIN_SEC:-60}
WEIGHT=${BUCKET_WEIGHT:-1}

now_s(){ date +%s; }
uuid(){ cat /proc/sys/kernel/random/uuid 2>/dev/null || ${OPENSSL_BIN} rand -hex 16; }

bucket_refill(){
  local cut=$(( $(now_s) - WINDOW ))
  if [[ -f "$BUCKET" ]]; then
    awk -v c="$cut" '$1>=c{print $1}' "$BUCKET" > "${BUCKET}.tmp" || true
    mv "${BUCKET}.tmp" "$BUCKET" 2>/dev/null || true
  fi
}
bucket_take(){
  bucket_refill
  local cnt=0
  [[ -f "$BUCKET" ]] && cnt=$(wc -l < "$BUCKET" || echo 0)
  if (( cnt + WEIGHT > CAP )); then
    echo "rate_limited: too many ops ($cnt/$CAP)" >&2
    return 1
  fi
  for _ in $(seq 1 "$WEIGHT"); do echo "$(now_s)"; done >> "$BUCKET"
}

hmac_sha256(){
  ${OPENSSL_BIN} dgst -sha256 -hmac "$OPS_SIGN_SECRET" -r | awk '{print $1}'
}

signed_curl(){
  local method="$1" path="$2" body="${3:-}"
  local ts nonce payload sig url auth
  ts="$(now_s)"
  nonce="$(uuid)"
  payload="${method}"$'\n'"${path}"$'\n'"${body}"$'\n'"${ts}"$'\n'"${nonce}"
  sig="$(printf '%s' "$payload" | hmac_sha256)"
  url="${PUBLIC_HOST}${path}"
  auth="Authorization: Bearer ${API_BEARER_TOKEN}"

  if [[ "$method" == "GET" ]]; then
    ${CURL_BIN} -sS -m "${MAX_TIME}" -A "$UA" \
      -H "$auth" -H "X-Timestamp: ${ts}" -H "X-TS: ${ts}" \
      -H "X-Nonce: ${nonce}" -H "X-Signature: ${sig}" \
      "${url}"
  else
    ${CURL_BIN} -sS -m "${MAX_TIME}" -A "$UA" -X "$method" \
      -H "$auth" -H "Content-Type: application/json" \
      -H "X-Timestamp: ${ts}" -H "X-TS: ${ts}" \
      -H "X-Nonce: ${nonce}" -H "X-Signature: ${sig}" \
      --data-binary "${body}" \
      "${url}"
  fi
}

usage(){
  cat <<'U'
Usage:
  safe_ops.sh manage-once SYMBOL
  safe_ops.sh manage-once-lite SYMBOL               # רק BE + TP ladder
  safe_ops.sh be SYMBOL [OFFSET_BPS]
  safe_ops.sh trail SYMBOL [CALLBACK_PCT|'auto'] [ATR_MULT]
  safe_ops.sh trail-off SYMBOL                      # מבטל רק Trailing STOP (ראוט ייעודי)
  safe_ops.sh tp-one SYMBOL PRICE|pct:PCT
  safe_ops.sh tp-ladder SYMBOL "p1,p2,..." "s1,s2,..."
  safe_ops.sh tp-cancel SYMBOL
  safe_ops.sh sl-move SYMBOL PRICE
  safe_ops.sh close SYMBOL FRACTION(0..1)
  safe_ops.sh close-pct SYMBOL PCT(0..100)
  safe_ops.sh status SYMBOL                         # GET חתום (גוף {"symbol":"..."})
  safe_ops.sh open-top NOTIONAL LEV [long|short|auto_up|auto_down] [BUY|SELL]
U
}

cmd="${1:-}"; shift || true

case "$cmd" in
  manage-once)
    [[ $# -ge 1 ]] || { usage; exit 1; }
    symbol="${1^^}"
    bucket_take || exit 2
    signed_curl POST "/position-ops/manage-once" "$(printf '{"symbol":"%s"}' "$symbol")"
    ;;
  manage-once-lite)
    [[ $# -ge 1 ]] || { usage; exit 1; }
    symbol="${1^^}"
    bucket_take || exit 2
    signed_curl POST "/position-ops/manage-once" "$(printf '{"symbol":"%s","do":["be","tp_ladder"]}' "$symbol")"
    ;;
  be)
    [[ $# -ge 1 ]] || { usage; exit 1; }
    symbol="${1^^}"; offset="${2:-${TP_BE_OFFSET_BPS:-8}}"
    bucket_take || exit 2
    signed_curl POST "/position-ops/be" "$(printf '{"symbol":"%s","offset_bps":%d}' "$symbol" "$offset")"
    ;;
  trail)
    [[ $# -ge 1 ]] || { usage; exit 1; }
    symbol="${1^^}"; cb="${2:-auto}"; atr="${3:-}"
    bucket_take || exit 2
    if [[ "$cb" == "auto" ]]; then
      body=$(printf '{"symbol":"%s","atr_mult":%s}' "$symbol" "${atr:-"1.0"}")
    else
      body=$(printf '{"symbol":"%s","callbackRate":%s}' "$symbol" "$cb")
    fi
    signed_curl POST "/position-ops/trail" "$body"
    ;;
  trail-off)
    [[ $# -ge 1 ]] || { usage; exit 1; }
    symbol="${1^^}"
    bucket_take || exit 2
    signed_curl POST "/position-ops/trail/cancel" "$(printf '{"symbol":"%s"}' "$symbol")"
    ;;
  tp-one)
    [[ $# -ge 2 ]] || { usage; exit 1; }
    symbol="${1^^}"; val="$2"
    bucket_take || exit 2
    if [[ "$val" == pct:* ]]; then
      pct="${val#pct:}"
      body=$(printf '{"symbol":"%s","pct":%s}' "$symbol" "$pct")
    else
      body=$(printf '{"symbol":"%s","price":%s}' "$symbol" "$val")
    fi
    signed_curl POST "/position-ops/tp/one" "$body"
    ;;
  tp-ladder)
    [[ $# -ge 3 ]] || { usage; exit 1; }
    symbol="${1^^}"; pcts="$2"; splits="$3"
    bucket_take || exit 2
    body=$(printf '{"symbol":"%s","pcts":[%s],"splits":[%s]}' "$symbol" "$pcts" "$splits")
    signed_curl POST "/position-ops/tp/ladder" "$body"
    ;;
  tp-cancel)
    [[ $# -ge 1 ]] || { usage; exit 1; }
    symbol="${1^^}"
    bucket_take || exit 2
    signed_curl POST "/position-ops/tp/cancel" "$(printf '{"symbol":"%s"}' "$symbol")"
    ;;
  sl-move)
    [[ $# -ge 2 ]] || { usage; exit 1; }
    symbol="${1^^}"; price="$2"
    bucket_take || exit 2
    signed_curl POST "/position-ops/sl/move" "$(printf '{"symbol":"%s","price":%s}' "$symbol" "$price")"
    ;;
  close)
    [[ $# -ge 2 ]] || { usage; exit 1; }
    symbol="${1^^}"; frac="$2"
    bucket_take || exit 2
    signed_curl POST "/position-ops/close" "$(printf '{"symbol":"%s","fraction":%s}' "$symbol" "$frac")"
    ;;
  close-pct)
    [[ $# -ge 2 ]] || { usage; exit 1; }
    symbol="${1^^}"; pct="$2"
    bucket_take || exit 2
    signed_curl POST "/position-ops/close-percent" "$(printf '{"symbol":"%s","pct":%s}' "$symbol" "$pct")"
    ;;
  status)
    [[ $# -ge 1 ]] || { usage; exit 1; }
    symbol="${1^^}"
    bucket_take || true
    signed_curl GET "/position-ops/status?symbol=${symbol}" "$(printf '{"symbol":"%s"}' "$symbol")"
    ;;
  open-top)
    [[ $# -ge 2 ]] || { usage; exit 1; }
    notional="$1"; lev="$2"; gate="${3:-long}"; side="${4:-}"
    bucket_take || exit 2
    if [[ -n "$side" ]]; then
      body=$(printf '{"notional":%s,"leverage":%s,"gate":"%s","side":"%s"}' "$notional" "$lev" "$gate" "$side")
    else
      body=$(printf '{"notional":%s,"leverage":%s,"gate":"%s"}' "$notional" "$lev" "$gate")
    fi
    signed_curl POST "/position-ops/auto/open-top" "$body"
    ;;
  *) usage; exit 1;;
esac
BASH

# === יצירה/דריסה של /app/status.sh (פורמט טבלאי) ===
cat > /app/status.sh <<'BASH'
#!/usr/bin/env bash
set -euo pipefail
: "${PUBLIC_HOST:?need PUBLIC_HOST}"
: "${API_BEARER_TOKEN:?need API_BEARER_TOKEN}"
: "${OPS_SIGN_SECRET:?need OPS_SIGN_SECRET}"
PY="${PYTHON_BIN:-python3}"

symbol="${1:-}"
[[ -n "$symbol" ]] || { echo "Usage: /app/status.sh SYMBOL" >&2; exit 1; }

out="$(bash /app/safe_ops.sh status "$symbol" 2>/dev/null || true)"

"$PY" - "$symbol" <<'PY'
import sys, json
sym = sys.argv[1]
try:
    data = json.loads(sys.stdin.read() or "{}")
except Exception as e:
    print(f"[{sym}] invalid JSON: {e}"); sys.exit(0)

if not isinstance(data, dict):
    print(f"[{sym}] unexpected response"); sys.exit(0)

if not data.get("ok", False):
    print(f"[{sym}] ERROR: {data.get('reason','?')} {data.get('detail','')}")
    sys.exit(0)

def f(v):
    if isinstance(v, float): return f"{v:.8g}"
    return str(v)

print("="*68)
print(f" Symbol: {sym}")
print("-"*68)
print(f" Has Position : {data.get('has_position')}")
if data.get("has_position"):
    print(f" Side        : {data.get('side')}")
    print(f" Qty         : {f(data.get('qty'))}")
    print(f" Entry       : {f(data.get('entry'))}")
    print(f" Last        : {f(data.get('last'))}")
print("-"*68)
orders = data.get("orders") or []
if not orders:
    print(" Open Conditional Orders: (none)")
else:
    print(" Open Conditional Orders:")
    print("  #  type                      side   qty         stop/trigger   reduceOnly id")
    for i,o in enumerate(orders,1):
        typ = (o.get("type") or "")[:24].ljust(24)
        side = (o.get("side") or "")[:5].ljust(5)
        qty = f(float(o.get("origQty") or o.get("quantity") or 0)).ljust(10)
        stop = f(float(o.get("stopPrice") or o.get("price") or 0)).ljust(13)
        ro = str(o.get("reduceOnly", False)).ljust(10)
        oid = str(o.get("orderId") or o.get("clientOrderId") or "")
        print(f"  {str(i).rjust(2)}  {typ}  {side}  {qty}  {stop}  {ro} {oid}")
print("="*68)
PY
BASH

# הרשאות + ניקוי CRLF
chmod +x /app/safe_ops.sh /app/status.sh || true
sed -i 's/\r$//' /app/safe_ops.sh /app/status.sh 2>/dev/null || true

# אם במקרה המונט noexec — נריץ תמיד דרך bash:
alias safeops='bash /app/safe_ops.sh'
alias status='bash /app/status.sh'

# וידוא:
ls -l /app/safe_ops.sh /app/status.sh
file -b /app/safe_ops.sh /app/status.sh



