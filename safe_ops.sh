install -m 755 /dev/stdin /app/safe_ops.sh <<'BASH'
#!/usr/bin/env bash
# ultra-mini ops (no jq). Requires: curl, openssl

_need(){ [ -n "$1" ] || { echo "missing env: $2" >&2; return 1; }; }
_ok(){
  _need "$PUBLIC_HOST" PUBLIC_HOST || return 1
  _need "$API_BEARER_TOKEN" API_BEARER_TOKEN || return 1
  _need "$OPS_SIGN_SECRET" OPS_SIGN_SECRET || return 1
  command -v curl >/dev/null || { echo "curl not found" >&2; return 1; }
  command -v openssl >/dev/null || { echo "openssl not found" >&2; return 1; }
}
_sig(){ printf '%s' "$1" | openssl dgst -sha256 -hmac "$OPS_SIGN_SECRET" -r | awk '{print $1}'; }
_uuid(){ command -v uuidgen >/dev/null && uuidgen || echo $$.$RANDOM; }

# MODE=3: payload = "ts.nonce.body"
sp3(){ _ok||return 1; local p="$1" b="${2:-{}}"
  local ts n sg; ts=$(date +%s); n=$(_uuid); sg=$(_sig "$ts.$n.$b")
  curl -fsS -X POST "$PUBLIC_HOST$p" \
    -H "Authorization: Bearer $API_BEARER_TOKEN" \
    -H "Content-Type: application/json" \
    -H "X-Timestamp: $ts" -H "X-Nonce: $n" -H "X-Signature: $sg" \
    --data-binary "$b"
}
sg3(){ _ok||return 1; local p="$1" b=""
  local ts n sg; ts=$(date +%s); n=$(_uuid); sg=$(_sig "$ts.$n.$b")
  curl -fsS "$PUBLIC_HOST$p" \
    -H "Authorization: Bearer $API_BEARER_TOKEN" \
    -H "X-Timestamp: $ts" -H "X-Nonce: $n" -H "X-Signature: $sg"
}

# MODE=5: payload = "METHOD\nPATH\nBODY\nTS\nNONCE"
sp5(){ _ok||return 1; local p="$1" b="${2:-{}}"
  local ts n pl sg; ts=$(date +%s); n=$(_uuid); pl=$(printf '%s\n%s\n%s\n%s\n%s' POST "$p" "$b" "$ts" "$n"); sg=$(_sig "$pl")
  curl -fsS -X POST "$PUBLIC_HOST$p" \
    -H "Authorization: Bearer $API_BEARER_TOKEN" \
    -H "Content-Type: application/json" \
    -H "X-Timestamp: $ts" -H "X-Nonce: $n" -H "X-Signature: $sg" \
    --data-binary "$b"
}
sg5(){ _ok||return 1; local p="$1" b=""
  local ts n pl sg; ts=$(date +%s); n=$(_uuid); pl=$(printf '%s\n%s\n%s\n%s\n%s' GET "$p" "$b" "$ts" "$n"); sg=$(_sig "$pl")
  curl -fsS "$PUBLIC_HOST$p" \
    -H "Authorization: Bearer $API_BEARER_TOKEN" \
    -H "X-Timestamp: $ts" -H "X-Nonce: $n" -H "X-Signature: $sg"
}

# Default wrappers (MODE=3 is default)
sp(){ if [ "${SIG_MODE:-3}" = "5" ]; then sp5 "$@"; else sp3 "$@"; fi; }
sg(){ if [ "${SIG_MODE:-3}" = "5" ]; then sg5 "$@"; else sg3 "$@"; fi; }

# Convenience
healthz(){ curl -fsS "$PUBLIC_HOST/readyz" && echo OK; curl -fsS "$PUBLIC_HOST/health"; }
pending(){ curl -fsS -H "Authorization: Bearer $API_BEARER_TOKEN" "$PUBLIC_HOST/ops/ui/pending"; }
digest(){ local H="${1:-6}"; curl -fsS -H "Authorization: Bearer $API_BEARER_TOKEN" "$PUBLIC_HOST/ops/digest/expired?hours=$H"; }

# Position-ops helpers
status(){ sg "/position-ops/status?symbol=${1:-BTCUSDT}"; }
be(){ local s="${1:-BTCUSDT}" bps="${2:-12}"; sp "/position-ops/be" "{\"symbol\":\"$s\",\"offset_bps\":$bps}"; }
trail(){ local s="${1:-BTCUSDT}" mult="${2:-1.6}"; sp "/position-ops/trail" "{\"symbol\":\"$s\",\"atr_mult\":$mult}"; }

# One-shot manager (יעבוד רק אם הצד שרץ תומך ב-/manage-once)
manage_once(){ 
  _ok||return 1
  local s="$1" be_bps="${2:-}"; local atr="${3:-}" pcts="${4:-}" splits="${5:-}"
  [ -n "$s" ] || { echo "usage: manage_once SYM [BE_BPS] [ATR_MULT] [PCTS_CSV] [SPLITS_CSV]" >&2; return 1; }
  local body='{"symbol":"'"$s"'"}'
  [ -n "$be_bps" ] && body=${body%} && body=${body/}/',"offset_bps":'"$be_bps"'} && body=${body//}}/}
  [ -n "$atr" ] && body=${body%} && body=${body/}/',"atr_mult":'"$atr"',"callback_rate":null}' && body=${body//}}/}
  if [ -n "$pcts" ]; then
    local arr="["
    IFS=',' read -r -a A <<< "$pcts"
    for i in "${!A[@]}"; do [ $i -gt 0 ] && arr="$arr,"; arr="$arr${A[$i]}"; done
    arr="$arr]"
    body=${body%} && body=${body/}/',"pcts":'"$arr"'} && body=${body//}}/}
  fi
  if [ -n "$splits" ]; then
    local arr="["
    IFS=',' read -r -a A <<< "$splits"
    for i in "${!A[@]}"; do [ $i -gt 0 ] && arr="$arr,"; arr="$arr${A[$i]}"; done
    arr="$arr]"
    body=${body%} && body=${body/}/',"splits":'"$arr"'} && body=${body//}}/}
  fi
  sp "/manage-once" "$body"
}

_usage(){
  cat <<TXT
usage:
  # חתימה MODE=3 (ברירת מחדל) או MODE=5:
  export SIG_MODE=3|5

  # GET/POST חתומים:
  sg PATH
  sp PATH JSON

  # קיצורי position-ops:
  status SYMBOL
  be SYMBOL [BPS]
  trail SYMBOL [ATR_MULT]

  # one-shot ניהול:
  manage_once SYMBOL [BE_BPS] [ATR_MULT] [PCTS_CSV] [SPLITS_CSV]

  # בריאות/תקציר:
  healthz
  pending
  digest [HOURS]
TXT
}
[ "$1" = "-h" ] && { _usage; exit 0; }
BASH

# לוודא CRLF -> LF במקרה שהודבק מטקסט
sed -i 's/\r$//' /app/ops_env.sh /app/safe_ops.sh
. /app/ops_env.sh
. /app/safe_ops.sh










