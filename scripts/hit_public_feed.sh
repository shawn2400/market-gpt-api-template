#!/usr/bin/env bash
# ------------------------------------------------------------
# Hit public feed endpoints (with optional bearer)
# שימוש:
#   bash scripts/hit_public_feed.sh "<BASE_URL>" "<PUBLIC_BEARER (optional)>"
# הערות:
#   - תואם ל־PUBLIC_REQUIRE_BEARER=1 (אם מופעל — חייבים טוקן)
#   - מכסה: /scan/public-topk, /scan/public-now, /topk, /topk.csv, ו־SSE ticket (דוגמית קצרה)
# ------------------------------------------------------------
set -Eeuo pipefail

BASE_URL="${1:-http://127.0.0.1:10000}"
PUBLIC_BEARER="${2:-${API_BEARER_TOKEN:-}}"

if [[ -t 1 ]]; then G='\033[0;32m'; R='\033[0;31m'; Y='\033[1;33m'; B='\033[0;34m'; N='\033[0m'; else G=''; R=''; Y=''; B=''; N=''; fi
ok(){ echo -e "${G}OK${N}   - $1"; }
warn(){ echo -e "${Y}WARN${N} - $1"; }
fail(){ echo -e "${R}FAIL${N} - $1"; exit 1; }

_auth=()
[[ -n "$PUBLIC_BEARER" ]] && _auth=(-H "Authorization: Bearer ${PUBLIC_BEARER}")

echo -e "${B}=== 🌐 Public feed: ${BASE_URL} ===${N}"

# JSON endpoints
for path in "/scan/public-topk" "/scan/public-now" "/topk"; do
  if out="$(curl -fsS "${_auth[@]}" "${BASE_URL}${path}" 2>/dev/null | sed -e 's/^[[:space:]]*//' | head -n 20)"; then
    ok "$path"
    printf "%s\n\n" "$out"
  else
    # Try to catch likely 401 when bearer is required
    code="$(curl -s -o /dev/null -w "%{http_code}" "${_auth[@]}" "${BASE_URL}${path}" || true)"
    [[ "$code" == "401" || "$code" == "403" ]] && warn "$path unauthorized (PUBLIC_REQUIRE_BEARER=1?)" || warn "$path failed"
  fi
done

# CSV
if out="$(curl -fsS "${_auth[@]}" "${BASE_URL}/topk.csv" 2>/dev/null | head -n 10)"; then
  ok "/topk.csv"
  printf "%s\n\n" "$out"
else
  code="$(curl -s -o /dev/null -w "%{http_code}" "${_auth[@]}" "${BASE_URL}/topk.csv" || true)"
  [[ "$code" == "401" || "$code" == "403" ]] && warn "/topk.csv unauthorized" || warn "/topk.csv failed"
fi

# SSE (sample 5s)
if command -v timeout >/dev/null 2>&1; then
  if head="$(timeout 5 curl -fsS "${_auth[@]}" "${BASE_URL}/public/sse-ticket" 2>/dev/null | head -n 10)"; then
    ok "/public/sse-ticket (sample)"
    printf "%s\n\n" "$head"
  else
    code="$(curl -s -o /dev/null -w "%{http_code}" "${_auth[@]}" "${BASE_URL}/public/sse-ticket" || true)"
    [[ "$code" == "401" || "$code" == "403" ]] && warn "/public/sse-ticket unauthorized" || warn "/public/sse-ticket failed (maybe blocked or no events)"
  fi
else
  warn "skip SSE (timeout cmd missing)"
fi

echo -e "${G}DONE${N}"
