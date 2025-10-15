cat >/app/status.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
BASE="${PUBLIC_HOST:-http://localhost:10000}"

echo "# /readyz"
curl -sS "$BASE/readyz"; echo
echo

echo "# /health"
curl -sS "$BASE/health"; echo
echo

echo "# /ops/manager/health"
curl -sS "$BASE/ops/manager/health"; echo
echo

echo "# /ops/ui/pending (HTML)"
if [ -n "${API_BEARER_TOKEN:-}" ]; then
  curl -sS -H "Authorization: Bearer ${API_BEARER_TOKEN}" "$BASE/ops/ui/pending"
else
  curl -sS "$BASE/ops/ui/pending"
fi
echo
EOF

chmod 755 /app/status.sh






