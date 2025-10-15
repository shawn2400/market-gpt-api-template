cat > /app/status.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
: "${PUBLIC_HOST:?need PUBLIC_HOST}"
: "${API_BEARER_TOKEN:?need API_BEARER_TOKEN}"

sym="${1:-}"
if [[ -z "$sym" ]]; then
  echo "usage: status.sh SYMBOL"
  exit 2
fi

_hdr(){ printf 'Authorization: Bearer %s' "$API_BEARER_TOKEN"; }

_fetch(){
  local path="$1"
  curl -sS -H "$(_hdr)" "${PUBLIC_HOST}${path}" || echo '{}'
}

pp(){ python3 - <<'PY' 2>/dev/null || cat
import sys,json
try: print(json.dumps(json.load(sys.stdin), indent=2, ensure_ascii=False))
except: print(sys.stdin.read())
PY
}

echo "# manager/health"
_fetch "/ops/manager/health" | pp
echo
echo "# ui/orders?symbol=${sym}"
_fetch "/ops/ui/orders?symbol=${sym}" | pp
echo
echo "# ui/ticket?symbol=${sym}"
_fetch "/ops/ui/ticket?symbol=${sym}" | pp
echo
echo "# scan/public-now (סינון ידני בצד הלקוח)"
_fetch "/scan/public-now" | pp
EOF
chmod +x /app/status.sh
