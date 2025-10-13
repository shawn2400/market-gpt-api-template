cat > ./auto-pick-daemon.sh <<'SH'
#!/usr/bin/env bash
set -euo pipefail
SLEEP="${AUTO_PICK_EVERY_SEC:-60}"
while true; do
  ./auto-pick.sh >> ./auto-pick.log 2>&1 || true
  sleep "$SLEEP"
done
SH
chmod +x ./auto-pick-daemon.sh
