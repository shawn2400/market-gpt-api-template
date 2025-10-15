#!/usr/bin/env bash
# safe_ops.sh — לקוח CLI חתום ל־position-ops
# דרישות ENV: PUBLIC_HOST, API_BEARER_TOKEN, OPS_SIGN_SECRET
set -euo pipefail

need() { : "${!1:?need $1}"; }
need PUBLIC_HOST
need API_BEARER_TOKEN
need OPS_SIGN_SECRET

# ---------- חתימה כללית ----------
sign_call() {
  # שימוש: sign_call "/path" '{"json":"compact"}' [METHOD]
  local path="$1"
  local body="${2:-{}}"
  local method="${3:-POST}"
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

# ---------- עזרה ----------
usage() {
  cat <<'USAGE'
usage:
  manage-once-lite SYMBOL
  be SYMBOL [OFFSET_BPS]
  trail SYMBOL [callbackRate|auto [ATR_MULT]]
  trail-off SYMBOL
  tp-one SYMBOL (pct:PCT | price:PX)
  tp-ladder SYMBOL [PCTS_CSV] [SPLITS_CSV]
  tp-cancel SYMBOL
  sl-move SYMBOL PRICE
  close SYMBOL [FRACTION 0..1]
  status SYMBOL
  auto-start ["SYM1,SYM2"] [EVERY_SEC]
  auto-stop
  open-top SYMBOL NOTIONAL_USDT LEVERAGE GATE(top|long|short|auto_up|auto_down) [--tp "1.8,3.2,5.5"] [--splits "0.4,0.35,0.25"] [--trail-atr 1.2|--trail-cb 1.0]

דוגמאות:
  ./safe_ops.sh manage-once-lite BTCUSDT
  ./safe_ops.sh be BTCUSDT 8
  ./safe_ops.sh trail BTCUSDT auto 1.2
  ./safe_ops.sh tp-one BTCUSDT pct:2.5
  ./safe_ops.sh tp-ladder BTCUSDT "3,6,12" "0.25,0.25,0.5"
  ./safe_ops.sh sl-move BTCUSDT 12345.6
  ./safe_ops.sh close BTCUSDT 0.25
  ./safe_ops.sh status BTCUSDT
  ./safe_ops.sh auto-start '["BTCUSDT","ETHUSDT"]' 20
  ./safe_ops.sh open-top BTCUSDT 250 10 long --tp "2,4,7" --splits "0.4,0.35,0.25" --trail-atr 1.2
USAGE
}

# ---------- פקודות ----------
cmd="${1:-help}"; shift || true

case "$cmd" in
  help|-h|--help) usage ;;

  manage-once-lite)
    sym="${1:?need SYMBOL}"
    body=$(printf '{"symbol":"%s","do":["be","tp_ladder"]}' "$sym")
    sign_call "/position-ops/manage-once" "$body" ; echo
    ;;

  be)
    sym="${1:?need SYMBOL}"; off="${2:-8}"
    body=$(printf '{"symbol":"%s","offset_bps":%d}' "$sym" "$off")
    sign_call "/position-ops/be" "$body" ; echo
    ;;

  trail)
    sym="${1:?need SYMBOL}"; mode="${2:-auto}"; arg="${3:-}"
    if [ "$mode" = "auto" ]; then
      if [ -n "$arg" ]; then
        body=$(printf '{"symbol":"%s","atr_mult":%s}' "$sym" "$arg")
      else
        body=$(printf '{"symbol":"%s","atr_mult":1.0}' "$sym")
      fi
    else
      body=$(printf '{"symbol":"%s","callbackRate":%s}' "$sym" "$mode")
    fi
    sign_call "/position-ops/trail" "$body" ; echo
    ;;

  trail-off)
    sym="${1:?need SYMBOL}"
    body=$(printf '{"symbol":"%s"}' "$sym")
    sign_call "/position-ops/trail/cancel" "$body" ; echo
    ;;

  tp-one)
    sym="${1:?need SYMBOL}"; p="${2:?need pct:PCT or price:PX}"
    case "$p" in
      pct:*)   val="${p#pct:}"; body=$(printf '{"symbol":"%s","pct":%s}'   "$sym" "$val") ;;
      price:*) val="${p#price:}"; body=$(printf '{"symbol":"%s","price":%s}' "$sym" "$val") ;;
      *) echo "need pct:PCT or price:PX"; exit 2 ;;
    esac
    sign_call "/position-ops/tp/one" "$body" ; echo
    ;;

  tp-ladder)
    sym="${1:?need SYMBOL}"; pcts="${2:-}"; splits="${3:-}"
    if [ -n "${pcts:-}" ] && [ -n "${splits:-}" ]; then
      body=$(printf '{"symbol":"%s","pcts":[%s],"splits":[%s]}' "$sym" "$pcts" "$splits")
    else
      body=$(printf '{"symbol":"%s"}' "$sym")
    fi
    sign_call "/position-ops/tp/ladder" "$body" ; echo
    ;;

  tp-cancel)
    sym="${1:?need SYMBOL}"
    body=$(printf '{"symbol":"%s"}' "$sym")
    sign_call "/position-ops/tp/cancel" "$body" ; echo
    ;;

  sl-move)
    sym="${1:?need SYMBOL}"; px="${2:?need PRICE}"
    body=$(printf '{"symbol":"%s","price":%s}' "$sym" "$px")
    sign_call "/position-ops/sl/move" "$body" ; echo
    ;;

  close)
    sym="${1:?need SYMBOL}"; frac="${2:-1}"
    body=$(printf '{"symbol":"%s","fraction":%s}' "$sym" "$frac")
    sign_call "/position-ops/close" "$body" ; echo
    ;;

  status)
    sym="${1:?need SYMBOL}"
    # חתימה ל-GET: הגוף חייב להיות זהה בין הצדדים
    body=$(printf '{"symbol":"%s"}' "$sym")
    path=$(printf '/position-ops/status?symbol=%s' "$sym")
    sign_call "$path" "$body" GET ; echo
    ;;

  auto-start)
    # auto-start '["BTCUSDT","ETHUSDT"]' [EVERY_SEC] [STEPS] [ATR_MULT]
    syms_json="${1:?need JSON array of symbols, e.g. [\"BTCUSDT\"]}"; shift || true
    every="${1:-20}"; shift || true
    steps="${1:-be,trail,tp_ladder}"; shift || true
    atr="${1:-}" || true
    if [ -n "$atr" ]; then
      body=$(printf '{"symbols":%s,"every_sec":%s,"steps":["%s"],"atr_mult":%s}' "$syms_json" "$every" "${steps//,/\",\"}" "$atr")
    else
      body=$(printf '{"symbols":%s,"every_sec":%s,"steps":["%s"]}' "$syms_json" "$every" "${steps//,/\",\"}")
    fi
    sign_call "/position-ops/auto/start" "$body" ; echo
    ;;

  auto-stop)
    sign_call "/position-ops/auto/stop" '{}' ; echo
    ;;

  open-top)
    # יעבוד כשיתווסף ראוט השרת: /position-ops/auto/open-top
    # שימוש: open-top SYMBOL NOTIONAL_USDT LEVERAGE GATE [--tp "..."] [--splits "..."] [--trail-atr X|--trail-cb Y]
    sym="${1:?need SYMBOL}"; nto="${2:?need NOTIONAL_USDT}"; lev="${3:?need LEVERAGE}"; gate="${4:?need GATE}"; shift 4 || true
    tp_csv=""; splits_csv=""; trail_atr=""; trail_cb=""
    while [ $# -gt 0 ]; do
      case "$1" in
        --tp)        tp_csv="$2"; shift 2 ;;
        --splits)    splits_csv="$2"; shift 2 ;;
        --trail-atr) trail_atr="$2"; shift 2 ;;
        --trail-cb)  trail_cb="$2"; shift 2 ;;
        *) echo "unknown flag: $1" >&2; exit 2 ;;
      esac
    done
    body=$(printf '{"symbol":"%s","notional":%s,"leverage":%s,"gate":"%s"' "$sym" "$nto" "$lev" "$gate")
    if [ -n "$tp_csv" ];     then body="$body$(printf ',"pcts":[%s]' "$tp_csv")"; fi
    if [ -n "$splits_csv" ]; then body="$body$(printf ',"splits":[%s]' "$splits_csv")"; fi
    if [ -n "$trail_atr" ];  then body="$body$(printf ',"trail":{"mode":"atr","atr_mult":%s}' "$trail_atr")"; fi
    if [ -n "$trail_cb" ];   then body="$body$(printf ',"trail":{"mode":"cb","callbackRate":%s}' "$trail_cb")"; fi
    body="$body}"
    # ניסיון ראשון לראוט החדש:
    if ! out="$(sign_call "/position-ops/auto/open-top" "$body" 2>/dev/null)"; then
      # נפילה אחורה לנתיב חלופי אם השרת מימש אחרת:
      out="$(sign_call "/auto/open-top" "$body" 2>/dev/null || true)"
    fi
    printf '%s\n' "${out:-}"; echo
    ;;

  *)
    usage; exit 2 ;;
esac







