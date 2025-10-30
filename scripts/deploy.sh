#!/usr/bin/env bash
set -euo pipefail
git add -A
git commit -m "deploy: auto-fix $(date -Iseconds)" || true
git push origin main
echo "Pushed. Render will deploy via existing settings."
