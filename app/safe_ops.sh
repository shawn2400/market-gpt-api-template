cat >/app/safe_ops.sh <<'BASH'
#!/usr/bin/env bash
set -euo pipefail

: "${PUBLIC_HOST:?need PUBLIC_HOST}"
: "${API_BEARER_TOKEN:?need API_BEARER_TOKEN}"
SIGN_SECRET="${OPS_SIGN_SECRET:-${API_SIGNING_SECRET:-}}"
: "${SIGN_SECRET:?need OPS_SIGN_SECRET or API_SIGNING_SECRET}"

auth_hdr=("Authorization: Bearer ${API_BEARER_TOKEN}")
json_hdr=("Content-Type: application/json")

canon_json() {
  python3 - "$@" <<'PY'
import sys, json
s = sys.stdin.read()
if not s.strip():
    print("", end=""); raise SystemExit
try:
    o = json.loads(s)
    print(json.dumps(o, separators=(",",":"), sort_keys=True, ensure_ascii=False), end="")
except Exception:
    print(s, end="")
PY
}

sha256_hex(){ printf "%s" "$1" | openssl dgst -sha256 -r | awk '{print $1}'; }

sign_headers() {
  local route="$1"; local body="${2-}"
  local ts nonce canon hash base sig
  ts="$(date +%s)"                              # שניות!
  nonce="$(cat /proc/sys/kernel/random/uuid)"
  canon="$(printf "%s" "${body}" | canon_json)"
  hash="$(sha256_hex "${canon}")"
  base="${ts}.${nonce}.${route}.${hash}"
  sig="$(printf "%s" "${base}" | openssl dgst -sha256 -hmac "${SIGN_SECRET}" -r | awk '{print $1}')"
  printf "X-Timestamp: %s\n" "${ts}"
  printf "X-Nonce: %s\n" "${nonce}"
  printf "X-Signature: %s\n" "${sig}"
}

post_signed() {
  local route="$1"; shift
  local body="${1-}"; shift || true
  mapfile -t sig < <(sign_headers "${route}" "${body}")
  curl -sS -X POST "${PUBLIC_HOST}${route}" \
    -H "${auth_hdr[0]}" -H "${json_hdr[0]}" \
    $(printf ' -H %q' "${sig[@]}") \
    --data-binary "${body}"
}

get_signed() {
  local route="$1"; shift
  local query="${1-}"; shift || true
  local body="${1-}"; shift || true
  mapfile -t sig < <(sign_headers "${route}" "${body}")
  curl -sS -X GET "${PUBLIC_HOST}${route}${query}" \
    -H "${auth_hdr[0]}" \
    $(printf ' -H %q' "${sig[@]}")
}

usage(){
cat <<'U'
usage:
  manage-once SYMBOL
  be SYMBOL [OFFSET_BPS]
  trail SYMBOL [CALLBACK_RATE|auto] [ATR_MULT]
  tp-one SYMBOL (--price PX | --pct PCT)
  tp-ladder SYMBOL [PCTS_CSV] [SPLITS_CSV]
  tp-cancel SYMBOL
  sl-move SYMBOL PRICE
  close SYMBOL [FRACTION 0..1]
  status SYMBOL
  auto-start ["SYM1,SYM2"] [EVERY_SEC]
  auto-stop
  open SYMBOL (long|short) NOTIONAL_USDT LEV
  trail-off SYMBOL
U
}

cmd="${1-}"; shift || true

case "${cmd}" in
  manage-once)
    sym="${1:?need SYMBOL}"; post_signed "/position-ops/manage-once" "$(printf '{"symbol":"%s"}' "${sym}")";;

  be)
    sym="${1:?need SYMBOL}"; off="${2-}"; off="${off:-${TP_BE_OFFSET_BPS:-8}}"
    post_signed "/position-ops/be" "$(printf '{"symbol":"%s","offset_bps":%s}' "${sym}" "${off}")";;

  trail)
    sym="${1:?need SYMBOL}"; cb="${2-}"; atr="${3-}"
    if [[ -n "${cb:-}" && "${cb}" != "auto" ]]; then
      post_signed "/position-ops/trail" "$(printf '{"symbol":"%s","callbackRate":%s}' "${sym}" "${cb}")"
    elif [[ -n "${atr:-}" ]]; then
      post_signed "/position-ops/trail" "$(printf '{"symbol":"%s","atr_mult":%s}' "${sym}" "${atr}")"
    else
      post_signed "/position-ops/trail" "$(printf '{"symbol":"%s"}' "${sym}")"
    fi;;

  tp-one)
    sym="${1:?need SYMBOL}"; flag="${2:?--price PX | --pct PCT}"; val="${3:?need value}"
    if [[ "${flag}" == "--price" ]]; then
      post_signed "/position-ops/tp/one" "$(printf '{"symbol":"%s","price":%s}' "${sym}" "${val}")"
    elif [[ "${flag}" == "--pct" ]]; then
      post_signed "/position-ops/tp/one" "$(printf '{"symbol":"%s","pct":%s}' "${sym}" "${val}")"
    else echo "use: tp-one SYMBOL (--price PX | --pct PCT)" >&2; exit 2; fi;;

  tp-ladder)
    sym="${1:?need SYMBOL}"; pcts="${2-}"; splits="${3-}"
    if [[ -n "${pcts:-}" && -n "${splits:-}" ]]; then
      post_signed "/position-ops/tp/ladder" "$(printf '{"symbol":"%s","pcts":[%s],"splits":[%s]}' "${sym}" "${pcts}" "${splits}")"
    else
      post_signed "/position-ops/tp/ladder" "$(printf '{"symbol":"%s"}' "${sym}")"
    fi;;

  tp-cancel)
    sym="${1:?need SYMBOL}"; post_signed "/position-ops/tp/cancel" "$(printf '{"symbol":"%s"}' "${sym}")";;

  sl-move)
    sym="${1:?need SYMBOL}"; px="${2:?need PRICE}"
    post_signed "/position-ops/sl/move" "$(printf '{"symbol":"%s","price":%s}' "${sym}" "${px}")";;

  close)
    sym="${1:?need SYMBOL}"; frac="${2-1}"
    post_signed "/position-ops/close" "$(printf '{"symbol":"%s","fraction":%s}' "${sym}" "${frac}")";;

  status)
    sym="${1:?need SYMBOL}"
    get_signed "/position-ops/status" "?symbol=${sym}" "$(printf '{"symbol":"%s"}' "${sym}")";;

  auto-start)
    syms_csv="${1-}"; every="${2-}"
    body='{}'
    if [[ -n "${syms_csv:-}" ]]; then syms_json=$(printf '%s' "${syms_csv}" | sed 's/[^,][^,]*/"&"/g'); body=$(printf '{"symbols":[%s]}' "${syms_json}"); fi
    if [[ -n "${every:-}" ]]; then
      if [[ "${body}" == "{}" ]]; then body=$(printf '{"every_sec":%s}' "${every}");
      else body=$(printf '%s' "${body}" | sed 's/}$/,"every_sec":'"${every}"'}/'); fi
    fi
    post_signed "/position-ops/auto/start" "${body}";;

  auto-stop)
    post_signed "/position-ops/auto/stop" "{}";;

  # נדרש שרת: /position-ops/open (מצורף בקוד בהמשך)
  open)
    sym="${1:?need SYMBOL}"; side="${2:?long|short}"; notional="${3:?USDT}"; lev="${4:?LEV}"
    side_up=$(printf "%s" "${side}" | tr a-z A-Z); [[ "${side_up}" == "LONG" ]] && s="BUY" || s="SELL"
    post_signed "/position-ops/open" "$(printf '{"symbol":"%s","side":"%s","notional":%s,"leverage":%s,"margin":"ISOLATED"}' "${sym}" "${s}" "${notional}" "${lev}")";;

  # נדרש שרת: /position-ops/trail/cancel (מצורף בקוד בהמשך)
  trail-off)
    sym="${1:?need SYMBOL}"
    post_signed "/position-ops/trail/cancel" "$(printf '{"symbol":"%s"}' "${sym}")";;

  *) usage; exit 2;;
esac
BASH
chmod +x /app/safe_ops.sh

