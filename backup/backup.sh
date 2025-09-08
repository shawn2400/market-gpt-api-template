#!/usr/bin/env bash
set -euo pipefail

SRC="/app/data/algogpt.db"
DST="/backups"
KEEP=7

mkdir -p "$DST"

DATE="$(date +%Y%m%d-%H%M%S)"
if [ -f "$SRC" ]; then
  cp -f "$SRC" "$DST/algogpt-${DATE}.db"
fi

# מחיקה לפי סדר כרונולוגי (השארת 7 אחרונים)
ls -1t "$DST"/algogpt-*.db | tail -n +$((KEEP+1)) | xargs -r rm -f
