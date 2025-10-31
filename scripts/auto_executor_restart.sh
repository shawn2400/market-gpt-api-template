#!/usr/bin/env bash
set -euo pipefail
G="\033[1;32m"; R="\033[1;31m"; Y="\033[1;33m"; C="\033[1;36m"; N="\033[0m"

echo -e "${C}♻️ Restarting AutoExecutor process...${N}"

# בדוק אם קיים PID של AutoExecutor ורוץ מחדש
PID_FILE="static/cache/auto_executor.pid"
if [[ -f "$PID_FILE" ]]; then
  PID=$(cat "$PID_FILE")
  echo -e "${Y}Stopping existing AutoExecutor (PID: $PID)...${N}"
  kill -9 "$PID" 2>/dev/null || true
  rm -f "$PID_FILE"
else
  echo -e "${Y}No existing AutoExecutor process found${N}"
fi

# הפעל מחדש את המנוע
nohup python3 -m utils.auto_executor >/tmp/auto_executor.log 2>&1 &
NEW_PID=$!
echo "$NEW_PID" > "$PID_FILE"

echo -e "${G}✅ AutoExecutor restarted (PID: $NEW_PID)${N}"
