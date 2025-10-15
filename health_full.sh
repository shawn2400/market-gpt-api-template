#!/usr/bin/env bash
set -euo pipefail

HOST="127.0.0.1"
PORT="${PORT:-10000}"

curl -fsS "http://${HOST}:${PORT}/health" >/dev/null
curl -fsS "http://${HOST}:${PORT}/meta/version" >/dev/null

# readyz צריך תמיד להיות 200; נבדוק שהתוכן מכיל מפתחות
resp="$(curl -fsS "http://${HOST}:${PORT}/readyz")"
echo "$resp" | grep -q '"ws_ok":' || { echo "[health_full] missing ws_ok in /readyz"; exit 1; }
echo "$resp" | grep -q '"policy_loaded":' || { echo "[health_full] missing policy_loaded in /readyz"; exit 1; }

# דיסק חופשי
DF=$(df -Pm /app/data | awk 'NR==2{print $4}')
if [ "$DF" -lt 50 ]; then
  echo "[health_full] low free disk on /app/data (${DF}M)"; exit 1
fi

# קצב תגובה /metrics (לא חובה, אבל טוב לבדוק)
curl -fsS "http://${HOST}:${PORT}/metrics" >/dev/null

echo "[health_full] OK"
