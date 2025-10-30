#!/usr/bin/env bash
set -euo pipefail

echo "🧾 Auto System Report Started — $(date)"
bash scripts/control.sh full-report
echo "✅ Report sent successfully at $(date)"
