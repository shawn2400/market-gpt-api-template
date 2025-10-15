cat >/app/safe_ops.sh <<'BASH'
#!/usr/bin/env bash
# minimal + safe, no 'set -e' to avoid hard exits.

_need(){ [ -n "$1" ] || { echo "missing env: $2" >&2; return 1; }; }

_ok_env(){
  _need "$PUBLIC_HOST" "PUBLIC_HOST" || return 1
  _need "$API_BEARER_TOKEN" "API_BEARER_TOKEN" || return 1
  _need "$OPS_SIGN_SECRET" "OPS_SIGN_SECRET" || return 1
  command -v curl >/dev/null || { echo "curl not found" >&2; return 1; }
  command -v openssl >/dev/null || { echo "openssl not found" >&2; return 1; }
  return 0
}

# Build HMAC (hex) over "METHOD\nPATH\nBODY\nTS\nNONCE"
_sig_hex(){ # $1=payload
  printf '%s' "$1" | openssl dgst -sha256 -hmac "$OPS_SIGN_SECRET" -r | awk '{print $1}'
}

# Signed POST
sp(){ # $1=path  $2=json_body
  _ok_env || return 1
  local path="$1" body="${2:-{}}"
  local ts nonce payload sig
  ts="$(date +%s)"
  nonce="$(cat /proc/sys/kernel/random/uuid 2>/dev/null || echo $$.$RANDOM)"
  payload="$(printf '%s\n%s\n%s\n%s\n%s' 'POST' "$path" "$body" "$ts" "$nonce")"
  sig="$(_sig_hex "$payload")"
  curl -fsS -X POST "$PUBLIC_HOST$path" \
    -H "Authorization: Bearer $API_BEARER_TOKEN" \
    -H "Content-Type: application/json" \
    -H "X-Timestamp: $ts" -H "X-Nonce: $nonce" -H "X-Signature: $sig" \
    --data-binary "$body"
}

# Signed GET (body is empty in signature)
sg(){ # $1=path (may include ?query)
  _ok_env || return 1
  local path="$1"
  local ts nonce payload sig
  ts="$(date +%s)"
  nonce="$(cat /proc/sys/kernel/random/uuid 2>/dev/null || echo $$.$RANDOM)"
  payload="$(printf '%s\n%s\n%s\n%s\n%s' 'GET' "$path" "" "$ts" "$nonce")"
  sig="$(_sig_hex "$payload")"
  curl -fsS "$PUBLIC_HOST$path" \
    -H "Authorization: Bearer $API_BEARER_TOKEN" \
    -H "X-Timestamp: $ts" -H "X-Nonce: $nonce" -H "X-Signature: $sig"
}

# ===== Convenience wrappers (לא נופלים על 404) =====
be(){        sp "/position-ops/be"           "{\"symbol\":\"$1\",\"offset_bps\":${2:-8}}" || true; }
trail_on(){  sp "/position-ops/trail"        "{\"symbol\":\"$1\",\"atr_mult\":${2:-1.2}}" || true; }
trail_off(){ sp "/position-ops/trail/cancel" "{\"symbol\":\"$1\"}" || true; }
tp_one(){    sp "/position-ops/tp/one"       "{\"symbol\":\"$1\",\"pct\":${2:-2.5}}" || true; }
tp_ladder(){ sp "/position-ops/tp/ladder"    "{\"symbol\":\"$1\",\"pcts\":[${2:-3,6,12}],\"splits\":[${3:-0.25,0.25,0.5}]}" || true; }
tp_cancel(){ sp "/position-ops/tp/cancel"    "{\"symbol\":\"$1\"}" || true; }
sl_move(){   sp "/position-ops/sl/move"      "{\"symbol\":\"$1\",\"price\":$2}" || true; }
close_p(){   sp "/position-ops/close"        "{\"symbol\":\"$1\",\"fraction\":${2:-0.25}}" || true; }
pos_status(){ sg "/position-ops/status?symbol=$1" || true; }

# manage-once (הנתיב קיים ב-main.py)
manage_once(){ # $1=symbol [be_bps] [atr_mult] [pcts_csv] [splits_csv]
  local sym="$1" bebps="${2:-}" atr="${3:-}" pcts="${4:-}" splits="${5:-}"
  local body="{\"symbol\":\"$sym\""
  [ -n "$bebps" ] && body="$body,\"offset_bps\":$bebps"
  [ -n "$atr" ]   && body="$body,\"atr_mult\":$atr"
  [ -n "$pcts" ]  && body="$body,\"pcts\":[${pcts}]"
  [ -n "$splits" ]&& body="$body,\"splits\":[${splits}]"
  body="$body}"
  curl -fsS -X POST "$PUBLIC_HOST/manage-once" \
    -H "Authorization: Bearer $API_BEARER_TOKEN" \
    -H "Content-Type: application/json" \
    --data-binary "$body"
}

# guard smoke (עם/בלי רשימת סמלים)
guard_smoke(){ # guard_smoke ["SYM1,SYM2"]
  if [ -n "$1" ]; then
    curl -fsS -X POST "$PUBLIC_HOST/guard/smoke/run" \
      -H "Authorization: Bearer $API_BEARER_TOKEN" \
      -H "Content-Type: application/json" \
      --data-binary "\"$1\""
  else
    curl -fsS -X POST "$PUBLIC_HOST/guard/smoke/run" \
      -H "Authorization: Bearer $API_BEARER_TOKEN" \
      -H "Content-Type: application/json" \
      --data-binary null
  fi
}

# create + approve ticket (בלי jq)
ticket_buy_now(){ # $1=symbol $2=side(BUY/SELL) $3=lev $4=qty
  local sym="$1" side="$2" lev="${3:-20}" qty="${4:-0}"
  local resp tid
  resp="$(curl -fsS -X POST "$PUBLIC_HOST/ops/ticket" \
      -H "Authorization: Bearer $API_BEARER_TOKEN" \
      -H "Content-Type: application/json" \
      --data-binary "{\"symbol\":\"$sym\",\"side\":\"$side\",\"qty\":$qty,\"leverage\":$lev}")" || { echo "ticket failed"; return 1; }
  tid="$(printf '%s' "$resp" | sed -n 's/.*"ticket_id":"\([^"]*\)".*/\1/p')"
  [ -n "$tid" ] || { echo "no ticket_id in response"; printf '%s\n' "$resp"; return 1; }
  curl -fsS "$PUBLIC_HOST/ops/approve?ticket_id=$tid" -H "Authorization: Bearer $API_BEARER_TOKEN"
}

# health / UI / digest
healthz(){ curl -fsS "$PUBLIC_HOST/readyz" && echo OK; curl -fsS "$PUBLIC_HOST/health"; }
pending(){ curl -fsS -H "Authorization: Bearer $API_BEARER_TOKEN" "$PUBLIC_HOST/ops/ui/pending"; }
digest(){  curl -fsS -H "Authorization: Bearer $API_BEARER_TOKEN" "$PUBLIC_HOST/ops/digest/expired?hours=${1:-6}"; }
BASH
chmod 755 /app/safe_ops.sh









