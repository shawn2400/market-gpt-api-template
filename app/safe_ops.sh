. /app/ops_env.sh
install -m 755 /dev/stdin /app/safe_ops.sh <<'BASH'
#!/usr/bin/env bash
_need(){ [ -n "$1" ] || { echo "missing env: $2" >&2; return 1; }; }
_ok(){ _need "$PUBLIC_HOST" PUBLIC_HOST && _need "$API_BEARER_TOKEN" API_BEARER_TOKEN && _need "$OPS_SIGN_SECRET" OPS_SIGN_SECRET && command -v curl >/dev/null && command -v openssl >/dev/null; }
_sig(){ printf '%s' "$1" | openssl dgst -sha256 -hmac "$OPS_SIGN_SECRET" -r | awk '{print $1}'; }
sp(){ _ok||return 1; local p="$1" b="${2:-{}}"; local ts n pl sg; ts=$(date +%s); n=$(cat /proc/sys/kernel/random/uuid 2>/dev/null||echo $$.$RANDOM); pl=$(printf '%s\n%s\n%s\n%s\n%s' POST "$p" "$b" "$ts" "$n"); sg=$(_sig "$pl"); curl -fsS -X POST "$PUBLIC_HOST$p" -H "Authorization: Bearer $API_BEARER_TOKEN" -H "Content-Type: application/json" -H "X-Timestamp: $ts" -H "X-Nonce: $n" -H "X-Signature: $sg" --data-binary "$b"; }
sg(){ _ok||return 1; local p="$1" ts n pl sg; ts=$(date +%s); n=$(cat /proc/sys/kernel/random/uuid 2>/dev/null||echo $$.$RANDOM); pl=$(printf '%s\n%s\n%s\n%s\n%s' GET "$p" "" "$ts" "$n"); sg=$(_sig "$pl"); curl -fsS "$PUBLIC_HOST$p" -H "Authorization: Bearer $API_BEARER_TOKEN" -H "X-Timestamp: $ts" -H "X-Nonce: $n" -H "X-Signature: $sg"; }
manage_once(){ _ok||return 1; local s="$1" beb="$2" atr="$3" p="$4" spx="$5" body="{\"symbol\":\"$s\"}"; [ -n "$beb" ]&&body="$body,\"offset_bps\":$beb"; [ -n "$atr" ]&&body="$body,\"atr_mult\":$atr"; [ -n "$p" ]&&body="$body,\"pcts\":[${p}]"; [ -n "$spx" ]&&body="$body,\"splits\":[${spx}]"; body="$body}"; curl -fsS -X POST "$PUBLIC_HOST/manage-once" -H "Authorization: Bearer $API_BEARER_TOKEN" -H "Content-Type: application/json" --data-binary "$body"; }
healthz(){ curl -fsS "$PUBLIC_HOST/readyz" && echo OK; curl -fsS "$PUBLIC_HOST/health"; }
pending(){ curl -fsS -H "Authorization: Bearer $API_BEARER_TOKEN" "$PUBLIC_HOST/ops/ui/pending"; }
digest(){  curl -fsS -H "Authorization: Bearer $API_BEARER_TOKEN" "$PUBLIC_HOST/ops/digest/expired?hours=${1:-6}"; }
BASH
. /app/safe_ops.sh

# בדיקות מהירות
healthz
digest 6
pending

# ניהול פוזיציה (אם /position-ops לא עלה, זה הולך דרך /manage-once שב־main.py)
manage_once BTCUSDT                # פרופיל בסיס
manage_once BTCUSDT 8 1.2 "3,6,12" "0.25,0.35,0.40"   # מותאם





