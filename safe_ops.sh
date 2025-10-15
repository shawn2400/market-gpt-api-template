#!/usr/bin/env bash
# safe_ops.sh — tiny helper for AlgoGPT ops
# Usage examples at bottom.

set -euo pipefail

# ===== Config via env =====
HOST="${HOST:-http://127.0.0.1:10000}"
TOKEN="${API_BEARER_TOKEN:-}"
SIGN_SECRET="${API_SIGNING_SECRET:-}"   # optional (for /manage-once when anti-replay enabled)

# ===== Internals =====
hdrs() {
  local extra=()
  [[ -n "$TOKEN" ]] && extra+=(-H "Authorization: Bearer $TOKEN")
  extra+=(-H "Content-Type: application/json")
  printf '%s\0' "${extra[@]}" | xargs -0 echo
}
sign_headers() {
  # Creates X-Timestamp / X-Nonce / X-Signature headers for anti-replay.
  # Signature = HMAC-SHA256(secret, f"{ts}.{nonce}.{body}")
  local body="${1:-""}"
  if [[ -z "$SIGN_SECRET" ]]; then
    echo ""
    return 0
  fi
  local ts nonce sig
  ts="$(date +%s)"
  nonce="$(openssl rand -hex 8)"
  sig="$(printf '%s.%s.%s' "$ts" "$nonce" "$body" | openssl dgst -sha256 -mac HMAC -macopt "hexkey:${SIGN_SECRET}" -r | awk '{print $1}')"
  echo -H "X-Timestamp: ${ts}" -H "X-Nonce: ${nonce}" -H "X-Signature: ${sig}"
}

# ===== Commands =====
ticket() {
  # ticket SYMBOL SIDE [QTY] [LEV] [NOTE]
  local sym="${1:?SYMBOL}"; shift
  local side="${1:?SIDE}"; shift
  local qty="${1:-0}"; shift || true
  local lev="${1:-0}"; shift || true
  local note="${1:-"[mode: HYBRID]"}"

  local body
  body=$(cat <<JSON
{"symbol":"${sym^^}","side":"${side^^}","qty":${qty},"leverage":${lev},"note":"${note}"}
JSON
)
  curl -sS -X POST "$HOST/ops/ticket" $(hdrs) --data-raw "$body" | jq -r .
}

approve() { # approve TICKET_ID
  local tid="${1:?ticket_id}"
  curl -sS "$HOST/ops/approve?ticket_id=$tid" $(hdrs)
}

reject() { # reject TICKET_ID
  local tid="${1:?ticket_id}"
  curl -sS "$HOST/ops/reject?ticket_id=$tid" $(hdrs)
}

pending() {
  curl -sS "$HOST/ops/ui/pending" $(hdrs)
}

manage_once() { # manage_once SYMBOL [offset_bps]  (auto profile if none)
  local sym="${1:?SYMBOL}"
  local offset="${2:-}"
  local body
  if [[ -n "$offset" ]]; then
    body='{"symbol":"'"${sym^^}"'","offset_bps":'"$offset"'}'
  else
    body='{"symbol":"'"${sym^^}"'"}'
  fi
  curl -sS -X POST "$HOST/manage-once" $(hdrs) $(sign_headers "$body") --data-raw "$body" | jq -r .
}

smoke() { # smoke [CSV_SYMBOLS]
  local syms="${1:-}"
  local body
  if [[ -n "$syms" ]]; then
    body='"'"$syms"'"'
  else
    body='null'
  fi
  curl -sS -X POST "$HOST/guard/smoke/run" $(hdrs) --data-raw "$body" | jq -r .
}

digest() { # digest [HOURS]
  local hrs="${1:-6}"
  curl -sS "$HOST/ops/digest/expired?hours=$hrs" $(hdrs) | jq -r .
}

trade_event() { # trade_event SYMBOL EVENT [SIDE] [PRICE] [QTY] [LEV]
  local sym="${1:?SYMBOL}"; shift
  local ev="${1:?EVENT}"; shift
  local side="${1:-}"; shift || true
  local price="${1:-}"; shift || true
  local qty="${1:-}"; shift || true
  local lev="${1:-}"
  local body='{"symbol":"'"${sym^^}"'","event":"'"${ev^^}"'"}'
  [[ -n "$side"  ]] && body=$(jq -cn --argjson b "$body" --arg s "${side^^}"  '$b|fromjson|.side=$s|tojson')
  [[ -n "$price" ]] && body=$(jq -cn --argjson b "$body" --arg p "$price"   '$b|fromjson|.price=($p|tonumber)|tojson')
  [[ -n "$qty"   ]] && body=$(jq -cn --argjson b "$body" --arg q "$qty"     '$b|fromjson|.qty=($q|tonumber)|tojson')
  [[ -n "$lev"   ]] && body=$(jq -cn --argjson b "$body" --arg l "$lev"     '$b|fromjson|.lev=($l|tonumber)|tojson')
  body=$(echo "$body" | jq -r .)
  curl -sS -X POST "$HOST/ops/trade-event" $(hdrs) --data-raw "$body" | jq -r .
}

help() {
  cat <<'H'
safe_ops.sh commands:

  ticket SYMBOL SIDE [QTY] [LEV] [NOTE]   Create approval ticket
  approve TICKET_ID                        Approve ticket (server will execute)
  reject TICKET_ID                         Reject ticket
  pending                                  List pending tickets (HTML)
  manage_once SYMBOL [offset_bps]          Place BE SL + TP ladder for open pos
  smoke [CSV_SYMBOLS]                      Run protective SL smoke-check
  digest [HOURS]                           Send expired approvals digest
  trade_event SYMBOL EVENT [SIDE] [PRICE] [QTY] [LEV]  Push a trade event

ENV:
  HOST (default http://127.0.0.1:10000)
  API_BEARER_TOKEN (recommended)
  API_SIGNING_SECRET (hex; optional, for anti-replay on /manage-once)

Examples:
  HOST=https://api.example.com API_BEARER_TOKEN=xxx ./safe_ops.sh ticket BTCUSDT BUY 0 20
  ./safe_ops.sh pending
  ./safe_ops.sh approve T_ab12cd34
  ./safe_ops.sh manage_once ETHUSDT 5
  ./safe_ops.sh smoke "BTCUSDT,ETHUSDT,SOLUSDT"
  ./safe_ops.sh digest 12
H
}

cmd="${1:-help}"; shift || true
case "$cmd" in
  ticket) ticket "$@" ;;
  approve) approve "$@" ;;
  reject) reject "$@" ;;
  pending) pending "$@" ;;
  manage_once) manage_once "$@" ;;
  smoke) smoke "$@" ;;
  digest) digest "$@" ;;
  trade_event) trade_event "$@" ;;
  help|--help|-h) help ;;
  *) echo "unknown command: $cmd"; help; exit 1 ;;
esac








