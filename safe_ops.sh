#!/usr/bin/env bash
# /app/safe_ops.sh — חתימה בלי jq, תומך בכל פעולות ה-OPS
set -euo pipefail

: "${PUBLIC_HOST:?need PUBLIC_HOST}"
: "${API_BEARER_TOKEN:?need API_BEARER_TOKEN}"
# נשתמש ב-OPS_SIGN_SECRET אם קיים, אחרת API_SIGNING_SECRET
SIGN_SECRET="${OPS_SIGN_SECRET:-${API_SIGNING_SECRET:-}}"
: "${SIGN_SECRET:?need OPS_SIGN_SECRET or API_SIGNING_SECRET}"

hdr_auth=("Authorization: Bearer ${API_BEARER_TOKEN}")
hdr_json=("Content-Type: application/json")

# --- JSON קנוני (ממויין, בלי רווחים) בעזרת python, בלי jq ---
canon_json() {
  # stdin -> stdout
  python3 - "$@" <<'PY'
import sys, json
src = sys.stdin.read()
if not src.strip():
    print("", end=""); sys.exit(0)
try:
    obj = json.loads(src)
    print(json.dumps(obj, separators=(",", ":"), sort_keys=True, ensure_ascii=False), end="")
except Exception:
    # אם לא JSON — נחזיר raw (כמו בסרוור)
    print(src, end="")
PY
}

# sha256 (hex) על מחרוזת
sha256_hex() {
  printf "%s" "$1" | openssl dgst -sha256 -r | awk '{print $1}'
}

# חישוב חתימה והחזרת כותרות החתימה
# usage: sign_headers <route> <body_json_or_empty>
sign_headers() {
  local route="$1"; local body="${2-}"
  local ts nonce canon hash base sig
  ts="$(date +%s)"                               # שניות (כמו בשרת)
  nonce="$(cat /proc/sys/kernel/random/uuid)"    # uuid
  canon="$(printf "%s" "${body}" | canon_json)"  # קנוניזציה
  hash="$(sha256_hex "${canon}")"
  base="${ts}.${nonce}.${route}.${hash}"
  sig="$(printf "%s" "${base}" | openssl dgst -sha256 -hmac "${SIGN_SECRET}" -r | awk '{print $1}')"
  printf "%s\n" "X-Timestamp: ${ts}"
  printf "%s\n" "X-Nonce: ${nonce}"
  printf "%s\n" "X-Signature: ${sig}"
}

# curl POST חתום
post_signed() {
  local route="$1"; shift
  local body="$1"; shift || true
  mapfile -t sig_hdrs < <(sign_headers "${route}" "${body}")
  curl -sS -X POST "${PUBLIC_HOST}${route}" \
    -H "${hdr_auth[0]}" -H "${hdr_json[0]}" \
    $(printf -- ' -H %q' "${sig_hdrs[@]}") \
    --data-binary "${body}"
}

# curl GET חתום (שימי לב: השרת מחשב חתימה מול BODY לוגי — נחתום עם JSON תואם למרות שזה GET)
get_signed() {
  local route="$1"; shift
  local query="$1"; shift || true     # למשל "?symbol=BTCUSDT"
  local body="$1"; shift || true      # למשל '{"symbol":"BTCUSDT"}'
  mapfile -t sig_hdrs < <(sign_headers "${route}" "${body}")
  curl -sS -X GET "${PUBLIC_HOST}${route}${query}" \
    -H "${hdr_auth[0]}" \
    $(printf -- ' -H %q' "${sig_hdrs[@]}")
}

usage() {
  cat <<'U'
safe_ops.sh usage:
  manage-once SYMBOL                      # BE + TRAIL + TP ladder
  be SYMBOL [OFFSET_BPS]                  # ברירת מחדל מהסביבה TP_BE_OFFSET_BPS או 8
  trail SYMBOL [CALLBACK_RATE|auto] [ATR_MULT]
  tp-one SYMBOL (--price PX | --pct PCT)
  tp-ladder SYMBOL [pcts CSV] [splits CSV]
  tp-cancel SYMBOL
  sl-move SYMBOL PRICE
  close SYMBOL [FRACTION 0..1]
  status SYMBOL                           # GET חתום עם body לוגי
  auto-start [SYMBOLS CSV] [EVERY_SEC]
  auto-stop
U
}

cmd="${1-}"; shift || true
case "${cmd}" in
  manage-once)
    sym="${1:?need SYMBOL}"; shift
    body=$(printf '{"symbol":"%s"}' "${sym}")
    post_signed "/position-ops/manage-once" "${body}"
    ;;

  be)
    sym="${1:?need SYMBOL}"; shift
    off="${1-}"; off="${off:-${TP_BE_OFFSET_BPS:-8}}"
    body=$(printf '{"symbol":"%s","offset_bps":%s}' "${sym}" "${off}")
    post_signed "/position-ops/be" "${body}"
    ;;

  trail)
    sym="${1:?need SYMBOL}"; shift
    cb="${1-}"; shift || true
    atr="${1-}"; shift || true
    if [[ -n "${cb:-}" && "${cb}" != "auto" ]]; then
      body=$(printf '{"symbol":"%s","callbackRate":%s}' "${sym}" "${cb}")
    else
      if [[ -n "${atr:-}" ]]; then
        body=$(printf '{"symbol":"%s","atr_mult":%s}' "${sym}" "${atr}")
      else
        body=$(printf '{"symbol":"%s"}' "${sym}")
      fi
    fi
    post_signed "/position-ops/trail" "${body}"
    ;;

  tp-one)
    sym="${1:?need SYMBOL}"; shift
    flag="${1:?--price PX | --pct PCT}"; shift
    val="${1:?need value}"; shift
    if [[ "${flag}" == "--price" ]]; then
      body=$(printf '{"symbol":"%s","price":%s}' "${sym}" "${val}")
    elif [[ "${flag}" == "--pct" ]]; then
      body=$(printf '{"symbol":"%s","pct":%s}' "${sym}" "${val}")
    else
      echo "use: tp-one SYMBOL (--price PX | --pct PCT)" >&2; exit 2
    fi
    post_signed "/position-ops/tp/one" "${body}"
    ;;

  tp-ladder)
    sym="${1:?need SYMBOL}"; shift
    pcts="${1-}"; shift || true
    splits="${1-}"; shift || true
    if [[ -n "${pcts:-}" && -n "${splits:-}" ]]; then
      body=$(printf '{"symbol":"%s","pcts":[%s],"splits":[%s]}' "${sym}" "${pcts}" "${splits}")
    else
      body=$(printf '{"symbol":"%s"}' "${sym}")
    fi
    post_signed "/position-ops/tp/ladder" "${body}"
    ;;

  tp-cancel)
    sym="${1:?need SYMBOL}"; shift
    body=$(printf '{"symbol":"%s"}' "${sym}")
    post_signed "/position-ops/tp/cancel" "${body}"
    ;;

  sl-move)
    sym="${1:?need SYMBOL}"; shift
    px="${1:?need PRICE}"; shift
    body=$(printf '{"symbol":"%s","price":%s}' "${sym}" "${px}")
    post_signed "/position-ops/sl/move" "${body}"
    ;;

  close)
    sym="${1:?need SYMBOL}"; shift
    frac="${1-1}"; shift || true
    body=$(printf '{"symbol":"%s","fraction":%s}' "${sym}" "${frac}")
    post_signed "/position-ops/close" "${body}"
    ;;

  status)
    sym="${1:?need SYMBOL}"; shift
    # השרת חותם על route="/position-ops/status" עם body={"symbol":...}
    get_signed "/position-ops/status" "?symbol=${sym}" "$(printf '{"symbol":"%s"}' "${sym}")"
    ;;

  auto-start)
    syms_csv="${1-}"; shift || true
    every="${1-}"; shift || true
    body='{}'
    [[ -n "${syms_csv:-}" ]] && body=$(printf '{"symbols":[%s]}' "$(printf '%s' "${syms_csv}" | sed 's/[^,][^,]*/"&"/g')")
    if [[ -n "${every:-}" ]]; then
      # הזרקה של every_sec לתוך ה-JSON (פשוטה)
      if [[ "${body}" == "{}" ]]; then body=$(printf '{"every_sec":%s}' "${every}");
      else body=$(printf '%s' "${body}" | sed 's/}$/,"every_sec":'"${every}"'}/'); fi
    fi
    post_signed "/position-ops/auto/start" "${body}"
    ;;

  auto-stop)
    # גוף ריק לוגית
    post_signed "/position-ops/auto/stop" "{}"
    ;;

  *)
    usage; exit 2;;
esac






