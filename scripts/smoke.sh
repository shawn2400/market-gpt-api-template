#!/usr/bin/env bash
# ------------------------------------------------------------
# AlgoGPT UltraTop — Smoke Test (full)
# שימוש:
#   bash scripts/smoke.sh "<BASE_URL>" "<API_BEARER_TOKEN (optional)>" "<METRICS_BEARER (optional)>" "<OPS_SIGN_SECRET (optional)>"
# דוגמאות:
#   bash scripts/smoke.sh "http://127.0.0.1:10000"
#   bash scripts/smoke.sh "http://127.0.0.1:10000" "dev_token"
#   bash scripts/smoke.sh "https://algogpt-docker.onrender.com" "" "METRICS_BEARER" "OPS_SECRET"
# ------------------------------------------------------------
set -Eeuo pipefail

BASE_URL="${1:-http://127.0.0.1:10000}"
API_BEARER_TOKEN="${2:-${API_BEARER_TOKEN:-}}"
METRICS_BEARER="${3:-${METRICS_BEARER:-}}"
OPS_SIGN_SECRET="${4:-${OPS_SIGN_SECRET:-}}"

# Colors
if [[ -t 1 ]]; then
  G='\033[0;32m'; R='\033[0;31m'; Y='\033[1;33m'; B='\033[0;34m'; N='\033[0m'
else
  G=''; R=''; Y=''; B=''; N=''
fi
ok()   { echo -e "${G}OK${N}   - $1"; }
warn() { echo -e "${Y}WARN${N} - $1"; }
fail() { echo -e "${R}FAIL${N} - $1"; exit 1; }

_have() { command -v "$1" >/dev/null 2>&1; }
JQ=cat; _have jq && JQ="jq"

PY=python3; _have python3 || { _have python && PY=python; }

# Sign helper (uses scripts/sign_ultra.py if exists; else inline)
_sign_body() {
  local secret="$1"; shift
  local body="${1:-}"; shift || true
  local ts sig
  ts="$(date +%s)"
  if [[ -n "$secret" && -f "scripts/sign_ultra.py" ]]; then
    sig="$(TS="$ts" OPS_SIGN_SECRET="$secret" BODY="$body" "$PY" scripts/sign_ultra.py --print-sig 2>/dev/null || true)"
  elif [[ -n "$secret" ]]; then
    sig="$("$PY" - <<'PY' 2>/dev/null || true
import os,hmac,hashlib,sys
sec=os.environ.get("OPS_SIGN_SECRET",""); ts=os.environ.get("TS",""); body=os.environ.get("BODY","").encode()
if not sec or not ts: sys.exit(1)
print(hmac.new(sec.encode(), ts.encode()+b"."+body, hashlib.sha256).hexdigest())
PY
    )" OPS_SIGN_SECRET="$secret" TS="$ts" BODY="$body"
  else
    ts=""; sig=""
  fi
  printf "%s;%s" "$ts" "$sig"
}

echo ""
echo -e "${B}=== 🚀 Smoke: ${BASE_URL} ===${N}"
[[ -n "$API_BEARER_TOKEN" ]] && echo "API Bearer: (set)" || echo "API Bearer: (empty)"
[[ -n "$METRICS_BEARER"   ]] && echo "Metrics Bearer: (set)" || echo "Metrics Bearer: (empty)"
[[ -n "$OPS_SIGN_SECRET"  ]] && echo "OPS_SIGN_SECRET: (set)" || echo "OPS_SIGN_SECRET: (empty)"
echo ""

failc=0

# 1) Core /health (root)
if curl -fsS "${BASE_URL}/health" >/dev/null; then
  ok "/health"
else
  # Ultra fallback
  if curl -fsS "${BASE_URL}/ultra/health" >/dev/null; then
    ok "/ultra/health"
  else
    warn "/health not reachable"
    failc=$((failc+1))
  fi
fi

# 2) /ultra/meta/version
if out="$(curl -fsS "${BASE_URL}/ultra/meta/version" | $JQ)"; then
  ok "/ultra/meta/version"
  printf "%s\n" "$out"
else
  warn "/ultra/meta/version failed"
  failc=$((failc+1))
fi

# 3) /ultra/readyz (json) + strict (status code)
if out="$(curl -fsS "${BASE_URL}/ultra/readyz" | $JQ)"; then
  ok "/ultra/readyz"
  printf "%s\n" "$out"
else
  warn "/ultra/readyz failed"
  failc=$((failc+1))
fi
code="$(curl -fsS -o /dev/null -w "%{http_code}" "${BASE_URL}/ultra/readyz/strict" || true)"
[[ "$code" == "200" ]] && ok "/ultra/readyz/strict => 200" || warn "/ultra/readyz/strict => $code"

# 4) Metrics (Bearer)
if [[ -n "$METRICS_BEARER" ]]; then
  if head="$(curl -fsS -H "Authorization: Bearer ${METRICS_BEARER}" "${BASE_URL}/ultra/metrics" | head -n 6)"; then
    ok "/ultra/metrics"
    printf "%s\n" "$head"
  else
    warn "/ultra/metrics failed (check bearer)"
    failc=$((failc+1))
  fi
else
  warn "skip /ultra/metrics — METRICS_BEARER empty"
fi

# 5) Optional app routes with API bearer
if [[ -n "$API_BEARER_TOKEN" ]]; then
  # market/ping (optional)
  if curl -fsS -H "Authorization: Bearer ${API_BEARER_TOKEN}" "${BASE_URL}/market/ping" >/dev/null 2>&1; then
    ok "/market/ping"
  else
    warn "/market/ping (missing route?)"
  fi
  # binance/status (optional)
  if out="$(curl -fsS -H "Authorization: Bearer ${API_BEARER_TOKEN}" "${BASE_URL}/binance/status" 2>/dev/null | $JQ)"; then
    ok "/binance/status"
    printf "%s\n" "$out"
  else
    warn "/binance/status (missing route?)"
  fi
else
  warn "skip /market/* tests — API_BEARER_TOKEN empty"
fi

# 6) Signed ops — /ultra/ops/policy/reload
if [[ -n "$OPS_SIGN_SECRET" ]]; then
  IFS=";" read -r XTS XSIG < <(_sign_body "$OPS_SIGN_SECRET" "")
  if [[ -n "$XTS" && -n "$XSIG" ]]; then
    if out="$(curl -fsS -X POST "${BASE_URL}/ultra/ops/policy/reload" -H "X-Timestamp: ${XTS}" -H "X-Signature: ${XSIG}" | $JQ)"; then
      ok "POST /ultra/ops/policy/reload"
      printf "%s\n" "$out"
    else
      warn "POST /ultra/ops/policy/reload failed"
      failc=$((failc+1))
    fi
  else
    warn "signing failed for /ultra/ops/policy/reload"
    failc=$((failc+1))
  fi

  # 7) Signed prefs patch
  BODY='{"patch":{"TP_DYNAMIC_ENABLE":1,"ENTRY_CONF_MIN":0.7}}'
  IFS=";" read -r XTS XSIG < <(_sign_body "$OPS_SIGN_SECRET" "$BODY")
  if [[ -n "$XTS" && -n "$XSIG" ]]; then
    if out="$(curl -fsS -X POST "${BASE_URL}/ultra/ops/runtime/prefs" \
      -H "Content-Type: application/json" -H "X-Timestamp: ${XTS}" -H "X-Signature: ${XSIG}" -d "$BODY" | $JQ)"; then
      ok "POST /ultra/ops/runtime/prefs"
      printf "%s\n" "$out"
    else
      warn "POST /ultra/ops/runtime/prefs failed"
      failc=$((failc+1))
    fi
  else
    warn "signing failed for /ultra/ops/runtime/prefs"
    failc=$((failc+1))
  fi
else
  warn "skip signed ops — OPS_SIGN_SECRET empty"
fi

echo ""
if [[ "$failc" -eq 0 ]]; then
  ok "SMOKE ✓"
  exit 0
else
  fail "SMOKE had ${failc} errors"
fi

