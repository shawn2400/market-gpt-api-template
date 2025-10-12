cat > /app/auto-pick-daemon.sh <<'SH'
#!/usr/bin/env bash
set -euo pipefail
while true; do
  /app/auto-pick.sh >> /app/auto-pick.log 2>&1 || true
  sleep 60
done
SH
chmod +x /app/auto-pick-daemon.sh
