# /app/safe_ops.sh
#!/usr/bin/env bash
# ultra-mini ops helper (בלי set -e; תמיד עם Bearer Token)
_need(){ [ -n "$1" ] || { echo "missing env: $2" >&2; return 1; }; }
_ok(){ _need "$PUBLIC_HOST" PUBLIC_HOST && _need "$API_BEARER_TOKEN" API_BEARER_TOKEN && _need "$OPS_SIGN_SECRET" OPS_SIGN_SECRET && command -v curl >/dev/null && command -v openssl >/dev/null; }
_h(){ echo "usage:
  sp PATH JSON        # Signed POST
  sg PATH             # Signed GET
  manage_once SYM [BE_BPS] [ATR_MULT] [PCTS_CSV] [SPLITS_CSV]
  healthz | pending | digest [H]"; }
_sig(){ printf '%s' "$1" | openssl dgst -sha256 -hmac "$OPS_SIGN_SECRET" -r | awk '{print $1}'; }

sp(){ _ok || return 1; local p="$1" b="${2:-{}}"; local ts n pl sg;
  ts=$(date +%s); n=$(cat /proc/sys/kernel/random/uuid 2>/dev/null || echo $$.$RANDOM)
  pl=$(printf '%s\n%s\n%s\n%s\n%s' POST "$p" "$b" "$ts" "$n"); sg=$(_sig "$pl")
  curl -fsS -X POST "$PUBLIC_HOST$p" \
    -H "Authorization: Bearer $API_BEARER_TOKEN" -H "Content-Type: application/json" \
    -H "X-Timestamp: $ts" -H "X-Nonce: $n" -H "X-Signature: $sg" \
    --data-binary "$b"
}

sg(){ _ok || return 1; local p="$1"; local ts n pl sg;
  ts=$(date +%s); n=$(cat /proc/sys/kernel/random/uuid 2>/dev/null || echo $$.$RANDOM)
  pl=$(printf '%s\n%s\n%s\n%s\n%s' GET "$p" "" "$ts" "$n"); sg=$(_sig "$pl")
  curl -fsS "$PUBLIC_HOST$p" \
    -H "Authorization: Bearer $API_BEARER_TOKEN" \
    -H "X-Timestamp: $ts" -H "X-Nonce: $n" -H "X-Signature: $sg"
}

manage_once(){ _ok || return 1; local s="$1" beb="$2" atr="$3" p="$4" spx="$5" body="{\"symbol\":\"$s\"}"
  [ -n "$beb" ] && body="$body,\"offset_bps\":$beb"
  [ -n "$atr" ] && body="$body,\"atr_mult\":$atr"
  [ -n "$p" ]   && body="$body,\"pcts\":[${p}]"
  [ -n "$spx" ] && body="$body,\"splits\":[${spx}]"
  body="$body}"
  curl -fsS -X POST "$PUBLIC_HOST/manage-once" \
    -H "Authorization: Bearer $API_BEARER_TOKEN" -H "Content-Type: application/json" \
    --data-binary "$body"
}

healthz(){ curl -fsS "$PUBLIC_HOST/readyz" && echo OK; curl -fsS "$PUBLIC_HOST/health"; }
pending(){ curl -fsS -H "Authorization: Bearer $API_BEARER_TOKEN" "$PUBLIC_HOST/ops/ui/pending"; }
digest(){  curl -fsS -H "Authorization: Bearer $API_BEARER_TOKEN" "$PUBLIC_HOST/ops/digest/expired?hours=${1:-6}"; }
[ $# -eq 0 ] && _h






