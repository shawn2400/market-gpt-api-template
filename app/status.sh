cat >/app/status.sh <<'BASH'
#!/usr/bin/env bash
set -euo pipefail
BASE="${PUBLIC_HOST:-http://localhost:10000}"

echo "# readyz:"
curl -sS "${BASE}/readyz" ; echo
echo
echo "# health:"
curl -sS "${BASE}/health" ; echo
echo
echo "# manager health:"
curl -sS "${BASE}/ops/manager/health" ; echo
echo
echo "# pending tickets (HTML):"
if [ -n "${API_BEARER_TOKEN:-}" ]; then
  curl -sS -H "Authorization: Bearer ${API_BEARER_TOKEN}" "${BASE}/ops/ui/pending"
else
  curl -sS "${BASE}/ops/ui/pending"
fi
echo
BASH

chmod +x /app/status.sh





