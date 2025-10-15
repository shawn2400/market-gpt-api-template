cat >/app/status.sh <<'BASH'
#!/usr/bin/env bash
set -euo pipefail
BASE="${PUBLIC_HOST:-http://localhost:10000}"
echo "# /readyz";                    curl -sS "$BASE/readyz"; echo
echo; echo "# /health";              curl -sS "$BASE/health"; echo
echo; echo "# /ops/manager/health";  curl -sS "$BASE/ops/manager/health"; echo
echo; echo "# /ops/ui/pending (HTML, מוגן Bearer)"; 
curl -sS -H "Authorization: Bearer ${API_BEARER_TOKEN:-}" "$BASE/ops/ui/pending" || true; echo
BASH
chmod 755 /app/status.sh







