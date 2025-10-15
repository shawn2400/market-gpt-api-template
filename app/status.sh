cat >/app/status.sh <<'BASH'
#!/usr/bin/env bash
set -euo pipefail
BASE="${PUBLIC_HOST:-http://localhost:10000}"

echo "# /readyz"
curl -fsS "$BASE/readyz"; echo; echo

echo "# /health"
curl -fsS "$BASE/health"; echo; echo

echo "# /ops/manager/health"
curl -fsS "$BASE/ops/manager/health"; echo; echo

echo "# /ops/ui/pending (HTML; מוגן Bearer)"
curl -fsS -H "Authorization: Bearer ${API_BEARER_TOKEN:-}" "$BASE/ops/ui/pending" || true; echo
BASH








