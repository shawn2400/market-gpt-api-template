cat > /app/ops_aliases.sh <<'EOF'
# -- ops_aliases.sh --
# דורש: PUBLIC_HOST, API_BEARER_TOKEN, API_SIGNING_SECRET
set -euo pipefail

_need(){ : "${PUBLIC_HOST:?need PUBLIC_HOST}"; : "${API_BEARER_TOKEN:?need API_BEARER_TOKEN}"; : "${API_SIGNING_SECRET:?need API_SIGNING_SECRET}"; }

_now_ms(){ date +%s%3N; }
_nonce(){
  if command -v uuidgen >/dev/null 2>&1; then uuidgen
  elif [[ -r /proc/sys/kernel/random/uuid ]]; then cat /proc/sys/kernel/random/uuid
  else echo "nonce-$RANDOM-$(_now_ms)"; fi
}
_hmac_sha256_hex(){
  if command -v xxd >/dev/null 2>&1; then
    openssl dgst -sha256 -hmac "$API_SIGNING_SECRET" -binary | xxd -p -c 256
  else
    openssl dgst -sha256 -hmac "$API_SIGNING_SECRET" -binary | od -An -tx1 | tr -d ' \n'
  fi
}
_sign(){ # METHOD PATH BODY TS NONCE
  printf "%s\n%s\n%s\n%s\n%s" "$1" "$2" "$3" "$4" "$5" | _hmac_sha256_hex
}

# ----- Signed POST to /position-ops/* -----
sc(){ # sc METHOD PATH BODY
  _need
  local method="$1" path="$2" body="${3:-}" ts nonce sig
  ts=$(_now_ms); nonce=$(_nonce); sig=$(_sign "$method" "$path" "$body" "$ts" "$nonce")
  curl -sS -X "$method" "${PUBLIC_HOST}${path}" \
    -H "Authorization: Bearer ${API_BEARER_TOKEN}" \
    -H "Content-Type: application/json" \
    -H "X-TS: ${ts}" -H "X-Nonce: ${nonce}" -H "X-Signature: ${sig}" \
    ${body:+ --data-binary "$body"}
}

# ----- Plain (Bearer only) -----
pc(){ # pc METHOD PATH BODY
  _need
  curl -sS -X "$1" "${PUBLIC_HOST}${2}" \
    -H "Authorization: Bearer ${API_BEARER_TOKEN}" \
    -H "Content-Type: application/json" \
    ${3:+ --data-binary "$3"}
}

# ===== Shortcuts =====
tp1(){      # tp1 SYMBOL PRICE QTY
  sc POST /position-ops/tp/one "$(printf '{"symbol":"%s","price":%s,"qty":%s,"side":"SELL","reduceOnly":true}' "$1" "$2" "$3")"
}
tpladder(){ # tpladder SYMBOL P1 P2 P3 Q1 Q2 Q3 (השאר ריקים אם צריך)
  local sym="$1"; shift || true
  local p1="${1:-}" p2="${2:-}" p3="${3:-}" q1="${4:-}" q2="${5:-}" q3="${6:-}"
  local items="[" first=1
  for i in 1 2 3; do eval "pp=\$p$i" "qq=\$q$i"
    if [[ -n "${pp:-}" && -n "${qq:-}" ]]; then
      [[ $first -eq 0 ]] && items+=", "
      items+=$(printf '{"price":%s,"qty":%s}' "$pp" "$qq"); first=0
    fi
  done; items+="]"
  sc POST /position-ops/tp/ladder "$(printf '{"symbol":"%s","items":%s,"side":"SELL","reduceOnly":true}' "$sym" "$items")"
}
be(){       # be SYMBOL [OFFSET_BPS=12]
  local off="${2:-12}"
  sc POST /position-ops/be/set "$(printf '{"symbol":"%s","offset_bps":%s}' "$1" "$off")"
}
msl(){      # msl SYMBOL PRICE
  sc POST /position-ops/sl/move "$(printf '{"symbol":"%s","price":%s}' "$1" "$2")"
}
tpc(){      # tpc SYMBOL  (tp-cancel)
  sc POST /position-ops/tp/cancel "$(printf '{"symbol":"%s"}' "$1")"
}
tr_on(){    # tr_on SYMBOL [ATR_MULT=1.6]
  local atr="${2:-1.6}"
  sc POST /position-ops/trail/on "$(printf '{"symbol":"%s","atr_mult":%s,"enable":true}' "$1" "$atr")"
}
tr_off(){   # tr_off SYMBOL
  sc POST /position-ops/trail/off "$(printf '{"symbol":"%s"}' "$1")"
}
tpr(){      # tpr SYMBOL (tp-refresh)
  sc POST /position-ops/tp/refresh "$(printf '{"symbol":"%s"}' "$1")"
}
sn(){       # sn SYMBOL (smart-now)
  sc POST /position-ops/smart/manage-now "$(printf '{"symbol":"%s"}' "$1")"
}
mo(){       # mo SYMBOL (manage-once, בלי חתימה)
  pc POST /manage-once "$(printf '{"symbol":"%s","force":true}' "$1")"
}

# Nice: הדפסה יפה אם יש python
pp(){ python3 - <<'PY' 2>/dev/null || cat
import sys,json
try: print(json.dumps(json.load(sys.stdin), indent=2, ensure_ascii=False))
except Exception as e: sys.stderr.write(f"pp error: {e}\n"); sys.stdout.write(sys.stdin.read())
PY
}
EOF
