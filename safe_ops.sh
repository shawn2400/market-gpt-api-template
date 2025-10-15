# בטיחות:
set +e; set +u 2>/dev/null || true; set +o pipefail 2>/dev/null || true

# 1) vars לסשן (Bearer + סוד חתימה)
install -m 600 /dev/stdin /app/ops_env.sh <<'BASH'
export PUBLIC_HOST="https://algogpt-docker.onrender.com"
export API_BEARER_TOKEN="rnd_XVyANQbo1mk8Q8nny3kTNDEzKoF7"
export OPS_SIGN_SECRET="51d4ad23aebf0ce08fc7d80fc265e02406a9075a7b5876cfe49296adc0c1821f"
# שומרים תאימות: חלק מהראוטים משתמשים בזה כשם אחר
export API_SIGNING_SECRET="$OPS_SIGN_SECRET"
BASH
sed -i 's/\r$//' /app/ops_env.sh
. /app/ops_env.sh

# 2) כלי ops מינימלי — POST חתום (ts.nonce.body) ל-/position-ops/* ו-POST רגיל ל-/manage-once
install -m 755 /dev/stdin /app/safe_ops.sh <<'BASH'
#!/usr/bin/env bash
# safe_ops.sh — מינימלי, בלי set -e

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

# --- Signed POST (ts.nonce.body) ל-/position-ops/*
_sp3(){ _ok || return 1; local path="$1" body="${2:-{}}"
  local ts n sig; ts="$(date +%s)"; n="$(_uuid)"; sig="$(_sig "$ts.$n.$body")"
  curl -fsS -X POST "$PUBLIC_HOST$path" \
    -H "Authorization: Bearer $API_BEARER_TOKEN" \
    -H "Content-Type: application/json" \
    -H "X-Timestamp: $ts" -H "X-Nonce: $n" -H "X-Signature: $sig" \
    --data-binary "$body"
}

# --- GET רגיל עם Bearer
_get(){ _ok || return 1; local path="$1"
  curl -fsS "$PUBLIC_HOST$path" -H "Authorization: Bearer $API_BEARER_TOKEN"
}

# --- POST רגיל ל-/manage-once (השרת לא דורש חתימה שם)
_post_plain(){ _ok || return 1; local path="$1" body="${2:-{}}"
  curl -fsS -X POST "$PUBLIC_HOST$path" \
    -H "Authorization: Bearer $API_BEARER_TOKEN" \
    -H "Content-Type: application/json" \
    --data-binary "$body"
}

# ===== פקודות נוחות =====
healthz(){ _get "/readyz" && echo OK; _get "/health"; }

status(){ _get "/position-ops/status?symbol=${1:?SYMBOL}"; }

be(){      local s="${1:?SYMBOL}" bps="${2:-8}";
           _sp3 "/position-ops/be" "{\"symbol\":\"$s\",\"offset_bps\":$bps}"; }

trail(){   local s="${1:?SYMBOL}" mult="${2:-1.6}";
           _sp3 "/position-ops/trail" "{\"symbol\":\"$s\",\"atr_mult\":$mult}"; }

# ניהול מלא: BE + TP ladder (+Trailing אם atr_mult>0)
# usage: manage_once SYMBOL [BE_BPS] [ATR_MULT] [PCTS_CSV] [SPLITS_CSV]
manage_once(){
  local s="${1:?SYMBOL}" be="${2:-8}" atr="${3:-1.6}" pcts="${4:-3,6,12}" splits="${5:-0.278,0.333,0.389}"
  local body="{\"symbol\":\"$s\",\"offset_bps\":$be"
  [ -n "$atr" ] && body="$body,\"atr_mult\":$atr"
  [ -n "$pcts" ] && body="$body,\"pcts\":[${pcts}]"
  [ -n "$splits" ] && body="$body,\"splits\":[${splits}]"
  body="$body}"
  _post_plain "/manage-once" "$body"
}

# debug (אופציונלי): מחזיר גם קוד סטטוס
spd(){ _ok||return 1; local p="$1" b="${2:-{}}"; local ts n sig; ts=$(date +%s); n="$(_uuid)"; sig="$(_sig "$ts.$n.$b")"
  curl -sS -w "\nHTTP:%{http_code}\n" -X POST "$PUBLIC_HOST$p" \
    -H "Authorization: Bearer $API_BEARER_TOKEN" -H "Content-Type: application/json" \
    -H "X-Timestamp: $ts" -H "X-Nonce: $n" -H "X-Signature: $sig" \
    --data-binary "$b"
}
BASH
sed -i 's/\r$//' /app/safe_ops.sh
. /app/safe_ops.sh

# smoke
healthz
type status be trail manage_once >/dev/null && echo "safe_ops.sh: OK"
# טעינה (אם פתחת סשן חדש)
. /app/ops_env.sh
. /app/safe_ops.sh

# 1) סטטוס לראות qty/entry
status BTCUSDT

# 2) ניהול מלא (BE=8bps, TP 3/6/12 עם חלוקות שמתכנסות ל-0.018, Trailing ATR*1.6)
manage_once BTCUSDT 8 1.6 "3,6,12" "0.278,0.333,0.389"

# 3) להצמיד BE שוב אחרי ההגדרות (מונע טריגר מיידי אם המחיר נדחף)
be BTCUSDT 8

# 4) להדליק טריילינג (השרת מחשב callbackRate לפי ATR ויזמין reduceOnly)
trail BTCUSDT 1.6

# 5) אימות
status BTCUSDT










