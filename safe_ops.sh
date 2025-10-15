
set +e; set +u 2>/dev/null || true; set +o pipefail 2>/dev/null || true

# כתיבה והרשאות
install -m 755 /dev/stdin /app/safe_ops.sh <<'BASH'
#!/usr/bin/env bash
# tiny ops helper (Bearer בלבד; בלי set -e)

_need(){ [ -n "$1" ] || { echo "missing env: $2" >&2; return 1; }; }
_ok(){
  _need "$PUBLIC_HOST"      PUBLIC_HOST      || return 1
  _need "$API_BEARER_TOKEN" API_BEARER_TOKEN || return 1
  command -v curl >/dev/null || { echo "curl not found" >&2; return 1; }
}

_post(){ _ok || return 1; local p="$1" b="${2:-{}}";
  curl -fsS -H "Authorization: Bearer $API_BEARER_TOKEN" -H "Content-Type: application/json" \
       -X POST "$PUBLIC_HOST$p" --data-binary "$b"; }

_get(){ _ok || return 1; local p="$1";
  curl -fsS -H "Authorization: Bearer $API_BEARER_TOKEN" "$PUBLIC_HOST$p"; }

# ===== בסיס =====
healthz(){ _get "/readyz" && echo OK; _get "/health"; }
pending(){  _get "/ops/ui/pending"; }
digest(){   _get "/ops/digest/expired?hours=${1:-6}"; }

# ===== ניהול פוזיציה =====
status(){   _get "/position-ops/status?symbol=${1:?SYMBOL}"; }
be(){       _post "/position-ops/be"    "{\"symbol\":\"${1:?SYMBOL}\",\"offset_bps\":${2:-8}}"; }

# הערה: TRAILING אצל Binance דורש quantity; ייתכן ויכשל בצד השרת אם לא מספקים כמות.
trail(){    _post "/position-ops/trail" "{\"symbol\":\"${1:?SYMBOL}\",\"atr_mult\":${2:-1.6}}"; }

# ניהול מלא דרך /manage-once (BE + TP ladder [+ Trail אם atr_mult>0])
# usage: manage_once SYMBOL [BE_BPS] [ATR_MULT] [PCTS_CSV] [SPLITS_CSV]
manage_once(){
  _ok || return 1
  local s="${1:?SYMBOL}" be="${2:-5}" atr="${3:-0}" pcts="${4:-}" splits="${5:-}"
  local body="{\"symbol\":\"$s\",\"offset_bps\":$be"
  [ "$atr" != "0" ] && body="$body,\"atr_mult\":$atr"
  [ -n "$pcts" ]  && body="$body,\"pcts\":[$pcts]"
  [ -n "$splits" ]&& body="$body,\"splits\":[$splits]"
  body="$body}"
  _post "/manage-once" "$body"
}

usage(){ cat <<USAGE
usage:
  healthz | pending | digest [H]
  status SYMBOL
  be SYMBOL [OFFSET_BPS]
  trail SYMBOL [ATR_MULT]
  manage_once SYMBOL [BE_BPS] [ATR_MULT] [PCTS_CSV] [SPLITS_CSV]
USAGE
}
[ $# -eq 0 ] && usage
BASH

# טעינת ENV אם עוד לא טעון
. /app/ops_env.sh 2>/dev/null || true

# בדיקה מהירה
/app/safe_ops.sh healthz










