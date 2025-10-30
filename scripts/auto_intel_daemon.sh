#!/usr/bin/env bash
set -euo pipefail

# ==============================
# AlgoGPT Auto-Intel Daemon
# ==============================
# ✅ רץ ברקע ברנדר/ריפליט
# ✅ משתמש ב-auto_intel.sh
# ✅ ללא עומס — ישן בין דוחות
# ✅ מתאפס לבד על קריסות

BASE="${BASE:-https://algogpt-docker.onrender.com}"
BEARER="${API_BEARER_TOKEN:-}"
INTERVAL_FILE="/tmp/algogpt_intel_interval.txt"
LOG_FILE="/app/logs/auto_intel.log"

mkdir -p /app/logs || true

run_cycle() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Running auto_intel.sh..." >> "$LOG_FILE"
  bash scripts/auto_intel.sh >> "$LOG_FILE" 2>&1 || echo "⚠️ auto_intel.sh failed" >> "$LOG_FILE"
}

safe_sleep() {
  local hrs="$1"
  local secs=$((hrs * 3600))
  echo "Sleeping for ${hrs}h (${secs}s)..."
  sleep "$secs"
}

# === Main Loop ===
while true; do
  run_cycle
  # קרא את זמן ההפעלה הבא מהקובץ (אם נוצר)
  if [[ -f "$INTERVAL_FILE" ]]; then
    interval=$(cat "$INTERVAL_FILE" | grep -Eo '[0-9]+' | head -1)
    [[ -z "$interval" ]] && interval=4
  else
    interval=4
  fi
  safe_sleep "$interval"
done
