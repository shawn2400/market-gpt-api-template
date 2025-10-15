install -m 755 /dev/stdin /app/safe_ops.sh <<'BASH'
#!/usr/bin/env bash
# safe_ops.sh — מינימלי, בלי jq. דורש: curl + openssl

_need(){ [ -n "$1" ] || { echo "missing env: $2" >&2; return 1; }; }
_ok(){
  _need "$PUBLIC_HOST" PUBLIC_HOST      || return 1
  _need "$API_BEARER_TOKEN" API_BEARER_TOKEN || return 1
  _need "$OPS_SIGN_SECRET" OPS_SIGN_SECRET   || return 1
  command -v curl >/dev/null    || { echo "curl not found" >&2; return 1; }
  command -v openssl >/dev/null || { echo "openssl not found" >&2; return 1; }
}
_sig(){ printf '%s' "$1" | openssl dgst -sha256 -hmac "$OPS_SIGN_SECRET" -r | awk '{print $1}'; }
_uuid(){ command -v uuidgen >/dev/null && uuidgen || echo $$.$RANDOM; }

# MODE=5 — חתימה על: "METHOD\nPATH\nBODY\nTS\nNONCE"
_sp5(){ local p="$1" b="${2:-{}}"; local ts n pl sg
  ts=$(date +%s); n=$(_uuid)
  pl=$(printf '%s\n%s\n%s\n%s\n%s' POST "$p" "$b" "$ts" "$n")
  sg=$(_sig "$pl")
  curl -fsS -X POST "$PUBLIC_HOST$p" \
    -H "Authorization: Bearer $API_BEARER_TOKEN" \
    -H "Content-Type: application/json" \
    -H "X-Timestamp: $ts" -H "X-Nonce: $n" -H "X-Signature: $sg" \
    --data-binary "$b"
}
_sg5(){ local p="$1"; local ts n pl sg
  ts=$(date +%s); n=$(_uuid)
  pl=$(printf '%s\n%s\n%s\n%s\n%s' GET "$p" "" "$ts" "$n")
  sg=$(_sig "$pl")
  curl -fsS "$PUBLIC_HOST$p" \
    -H "Authorization: Bearer $API_BEARER_TOKEN" \
    -H "X-Timestamp: $ts" -H "X-Nonce: $n" -H "X-Signature: $sg"
}

# MODE=3 — חתימה על: "TS.NONCE.BODY"
_sp3(){ local p="$1" b="${2:-{}}"; local ts n sg
  ts=$(date +%s); n=$(_uuid)
  sg=$(_sig "$ts.$n.$b")
  curl -fsS -X POST "$PUBLIC_HOST$p" \
    -H "Authorization: Bearer $API_BEARER_TOKEN" \
    -H "Content-Type: application/json" \
    -H "X-Timestamp: $ts" -H "X-Nonce: $n" -H "X-Signature: $sg" \
    --data-binary "$b"
}
_sg3(){ local p="$1"; local ts n sg
  ts=$(date +%s); n=$(_uuid)
  sg=$(_sig "$ts.$n.")
  curl -fsS "$PUBLIC_HOST$p" \
    -H "Authorization: Bearer $API_BEARER_TOKEN" \
    -H "X-Timestamp: $ts" -H "X-Nonce: $n" -H "X-Signature: $sg"
}

# Dispatcher לפי SIG_MODE (ברירת מחדל 5; אם מקבל 401 נסה 3)
sp(){ _ok || return 1; if [ "${SIG_MODE:-5}" = "3" ]; then _sp3 "$@"; else _sp5 "$@"; fi; }
sg(){ _ok || return 1; if [ "${SIG_MODE:-5}" = "3" ]; then _sg3 "$@"; else _sg5 "$@"; fi; }

# ===== פקודות נוחות =====
healthz(){ curl -fsS "$PUBLIC_HOST/readyz" && echo OK; curl -fsS "$PUBLIC_HOST/health"; }
status(){ local s="${1:-BTCUSDT}"; sg "/position-ops/status?symbol=$s"; }

be(){      # be SYMBOL [BPS]
  local s="${1:-BTCUSDT}" bps="${2:-12}"
  sp "/position-ops/be" "{\"symbol\":\"$s\",\"offset_bps\":$bps}"
}

trail(){   # trail SYMBOL [ATR_MULT]
  local s="${1:-BTCUSDT}" mult="${2:-1.6}"
  sp "/position-ops/trail" "{\"symbol\":\"$s\",\"atr_mult\":$mult}"
}

tp_ladder(){   # tp_ladder SYMBOL "p1,p2,p3" "w1,w2,w3"
  local s="${1:-BTCUSDT}" pcsv="${2:-3,6,12}" scsv="${3:-0.30,0.30,0.40}"
  sp "/position-ops/tp/ladder" "{\"symbol\":\"$s\",\"pcts\":[${pcsv}],\"splits\":[${scsv}]}"
}

tp_cancel(){   # tp_cancel SYMBOL
  local s="${1:-BTCUSDT}"
  sp "/position-ops/tp/cancel" "{\"symbol\":\"$s\"}"
}

trail_cancel(){   # trail_cancel SYMBOL
  local s="${1:-BTCUSDT}"
  sp "/position-ops/trail/cancel" "{\"symbol\":\"$s\"}"
}
BASH

