install -m 755 /dev/stdin /app/safe_ops.sh <<'BASH'
#!/usr/bin/env bash
# safe_ops.sh — מינימלי: GET עם Bearer; POST חתום (ts.nonce.body)

_need(){ [ -n "$1" ] || { echo "missing env: $2" >&2; return 1; }; }
_ok(){
  _need "$PUBLIC_HOST"      PUBLIC_HOST      || return 1
  _need "$API_BEARER_TOKEN" API_BEARER_TOKEN || return 1
  _need "$OPS_SIGN_SECRET"  OPS_SIGN_SECRET  || return 1
  command -v curl >/dev/null    || { echo "curl not found" >&2; return 1; }
  command -v openssl >/dev/null || { echo "openssl not found" >&2; return 1; }
}

_sig(){ printf '%s' "$1" | openssl dgst -sha256 -hmac "$OPS_SIGN_SECRET" -r | awk '{print $1}'; }
_uuid(){ command -v uuidgen >/dev/null && uuidgen || echo $$.$RANDOM; }

# --- Signed POST (MODE=3: "ts.nonce.body") ---
_sp3(){ _ok || return 1; local p="$1" b="${2:-{}}"; local ts n sg
  ts=$(date +%s); n=$(_uuid); sg=$(_sig "$ts.$n.$b")
  curl -fsS -X POST "$PUBLIC_HOST$p" \
    -H "Authorization: Bearer $API_BEARER_TOKEN" \
    -H "Content-Type: application/json" \
    -H "X-Timestamp: $ts" -H "X-Nonce: $n" -H "X-Signature: $sg" \
    --data-binary "$b"
}

# --- Unsigned GET (Bearer בלבד) ---
_sg(){ _ok || return 1; local p="$1"
  curl -fsS "$PUBLIC_HOST$p" -H "Authorization: Bearer $API_BEARER_TOKEN"
}

# ממשק ציבורי
sp(){ _sp3 "$@"; }
sg(){ _sg "$@"; }

# ===== בסיס =====
healthz(){ sg "/readyz" && echo OK; sg "/health"; }
pending(){  sg "/ops/ui/pending"; }
digest(){   sg "/ops/digest/expired?hours=${1:-6}"; }

# ===== פוזיציה (קיימים בשרת: status / be / trail) =====
status(){   sg "/position-ops/status?symbol=${1:?SYMBOL}"; }

be(){       # offset_bps=8 => 0.08%
  local s="${1:?SYMBOL}" bps="${2:-8}"
  sp "/position-ops/be" "{\"symbol\":\"${s}\",\"offset_bps\":${bps}}"
}

trail(){    # ATR*mult או אפשר לתת callback_rate ידני (בשרת: callback_rate)
  local s="${1:?SYMBOL}" mult="${2:-1.6}"
  sp "/position-ops/trail" "{\"symbol\":\"${s}\",\"atr_mult\":${mult}}"
}

# ===== ניהול מלא דרך /manage-once (TP ladder + BE + Trail) =====
# usage: manage_once SYMBOL [BE_BPS] [ATR_MULT] [PCTS_CSV] [SPLITS_CSV]
manage_once(){
  _ok || return 1
  local s="${1:?SYMBOL}" be="${2:-5}" atr="${3:-0}" pcts="${4:-}" splits="${5:-}"
  local body="{\"symbol\":\"${s}\",\"offset_bps\":${be}"
  [ "${atr}" != "0" ]   && body="${body},\"atr_mult\":${atr}"
  [ -n "${pcts}" ]      && body="${body},\"pcts\":[${pcts}]"
  [ -n "${splits}" ]    && body="${body},\"splits\":[${splits}]"
  body="${body}}"
  sp "/manage-once" "${body}"
}

# ===== כלי דיבוג נוחים (מראים קוד סטטוס) =====
spd(){ _ok || return 1; local p="$1" b="${2:-{}}"; local ts n sg
  ts=$(date +%s); n=$(_uuid); sg=$(_sig "$ts.$n.$b")
  curl -sS -w "\nHTTP:%{http_code}\n" -X POST "$PUBLIC_HOST$p" \
    -H "Authorization: Bearer $API_BEARER_TOKEN" -H "Content-Type: application/json" \
    -H "X-Timestamp: $ts" -H "X-Nonce: $n" -H "X-Signature: $sg" \
    --data-binary "$b"
}
sgd(){ _ok || return 1; local p="$1"
  curl -sS -w "\nHTTP:%{http_code}\n" "$PUBLIC_HOST$p" -H "Authorization: Bearer $API_BEARER_TOKEN"
}
BASH

# לוודא שאין CRLF ולטעון
sed -i 's/\r$//' /app/safe_ops.sh
. /app/safe_ops.sh
echo "safe_ops.sh loaded"










