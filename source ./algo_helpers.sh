#!/usr/bin/env sh
# Utility helpers for interacting with the service from inside the container.
# No jq dependency.

set -eu

API="${API_BASE:-http://127.0.0.1:${PORT:-10000}}"
AUTH=""
[ -n "${API_BEARER_TOKEN:-}" ] && AUTH="Authorization: Bearer ${API_BEARER_TOKEN}"

_red() { printf "\033[31m%s\033[0m\n" "$*" >&2; }
_grn() { printf "\033[32m%s\033[0m\n" "$*"; }
_ylw() { printf "\033[33m%s\033[0m\n" "$*"; }

algoinfo() {
  echo "API: $API"
  echo "PORT: ${PORT:-10000}"
  echo "TZ: ${TZ:-}"
  echo "APP_VERSION: ${ALGOGPT_VERSION:-}"
  echo "HAS_TOKEN: $( [ -n "${API_BEARER_TOKEN:-}" ] && echo yes || echo no )"
  echo "READYZ: $(curl -fsS "$API/readyz" 2>/dev/null || echo fail)"
}

healthz() {
  curl -fsS "$API/readyz" && echo "OK" || { _red "not ready"; return 1; }
}

version() {
  curl -fsS "$API/meta/version" || true
}

# mk_ticket SYMBOL SIDE QTY LEV [NOTE]
# example: mk_ticket BTCUSDT BUY 0.05 20 "[mode: HYBRID] test"
mk_ticket() {
  sym="${1:-}"; side="${2:-}"; qty="${3:-}"; lev="${4:-}"; note="${5:-}"
  [ -z "$sym" ]  && { _red "missing symbol"; return 2; }
  [ -z "$side" ] && { _red "missing side"; return 2; }
  [ -z "$qty" ]  && { _red "missing qty"; return 2; }
  [ -z "$lev" ]  && { _red "missing leverage"; return 2; }

  # build minimal JSON safely (no jq)
  esc() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }
  note_esc="$(esc "${note:-}")"
  json=$(printf '{"symbol":"%s","side":"%s","qty":%s,"leverage":%s,"note":"%s"}' \
        "$sym" "$side" "$qty" "$lev" "$note_esc")

  _ylw "POST /ops/ticket  $json"
  curl -fsS -H "Content-Type: application/json" -d "$json" "$API/ops/ticket" || {
    _red "ticket create failed"; return 1;
  }
  echo
}

# approve/reject unsigned (protected by bearer if enabled)
approve_ticket() {
  tid="${1:-}"; [ -z "$tid" ] && { _red "usage: approve_ticket <ticket_id>"; return 2; }
  curl -fsS -H "$AUTH" "$API/ops/approve?ticket_id=$tid" || { _red "approve failed"; return 1; }
  echo
}
reject_ticket() {
  tid="${1:-}"; [ -z "$tid" ] && { _red "usage: reject_ticket <ticket_id>"; return 2; }
  curl -fsS -H "$AUTH" "$API/ops/reject?ticket_id=$tid" || { _red "reject failed"; return 1; }
  echo
}

# manage-once SYMBOL [offset_bps] [pcts_csv] [splits_csv]
manage_once() {
  sym="${1:-}"; [ -z "$sym" ] && { _red "usage: manage_once <SYMBOL> [offset_bps] [pcts_csv] [splits_csv]"; return 2; }
  off="${2:-}"; pcts="${3:-}"; splits="${4:-}"
  body='{"symbol":"'"$sym"'"}'
  [ -n "$off" ]   && body=$(printf '%s,"offset_bps":%s'  "${body%}"; printf '}' ) && body=${body%}} || true
  [ -n "$pcts" ]  && body=$(printf '%s,"pcts":[%s]'     "${body%}"; printf '}' ) && body=${body%}} || true
  [ -n "$splits" ]&& body=$(printf '%s,"splits":[%s]'   "${body%}"; printf '}' ) && body=${body%}} || true
  # ensure closing brace in case no optionals
  case "$body" in
    *\}) : ;;
    *) body="$body}" ;;
  esac
  _ylw "POST /manage-once  $body"
  curl -fsS -H "$AUTH" -H "Content-Type: application/json" -d "$body" "$API/manage-once" || { _red "manage failed"; return 1; }
  echo
}

# tiny curl wrapper with bearer if exists
hc() {
  curl -fsS -H "$AUTH" "$@"
}
