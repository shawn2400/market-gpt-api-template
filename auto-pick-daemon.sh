cat > /app/auto-pick-daemon.sh <<'SH'
#!/usr/bin/env bash
set -euo pipefail
SLEEP="${AUTO_PICK_EVERY_SEC:-60}"
while true; do
  /app/auto-pick.sh >> /app/auto-pick.log 2>&1 || true
  sleep "$SLEEP"
done
SH
chmod +x /app/auto-pick-daemon.sh
