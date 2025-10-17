#!/usr/bin/env sh
set -eu

HOST="127.0.0.1"
PORT="${PORT:-10000}"

# /health
curl -fsS "http://${HOST}:${PORT}/health" >/dev/null
# /meta/version
curl -fsS "http://${HOST}:${PORT}/meta/version" >/dev/null

# /readyz – חייב להחזיר JSON עם ws_ok + policy_loaded (מה-router, לא מהמידלוור)
resp="$(curl -fsS "http://${HOST}:${PORT}/readyz")" || { echo "[health_full] /readyz failed"; exit 1; }

# בדיקות טקסט פשוטות (תואם sh)
echo "$resp" | grep -q '"ws_ok":' || { echo "[health_full] missing ws_ok in /readyz"; exit 1; }
echo "$resp" | grep -q '"policy_loaded":' || { echo "[health_full] missing policy_loaded in /readyz"; exit 1; }

# דיסק חופשי על /app/data (ב־MB)
DF="$(df -Pm /app/data | awk 'NR==2{print $4}')"
[ -n "$DF" ] || { echo "[health_full] df parse error"; exit 1; }
if [ "$DF" -lt 50 ]; then
  echo "[health_full] low free disk on /app/data (${DF}M)"; exit 1
fi

# /metrics (לא חובה, אך רצוי)
curl -fsS "http://${HOST}:${PORT}/metrics" >/dev/null || true

echo "[health_full] OK"

