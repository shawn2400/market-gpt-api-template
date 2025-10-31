#!/usr/bin/env bash
set -euo pipefail
G="\033[1;32m"; R="\033[1;31m"; Y="\033[1;33m"; C="\033[1;36m"; N="\033[0m"

TG_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
TG_CHAT="${TELEGRAM_CHAT_ID:-}"
LOG_FILE="/tmp/auto_executor.log"
PID_FILE="static/cache/auto_executor.pid"

echo -e "${C}♻️ Restarting AutoExecutor...${N}"

# --- בדיקה אם יש תהליך פעיל ---
if [[ -f "$PID_FILE" ]]; then
  OLD_PID=$(cat "$PID_FILE" 2>/dev/null || echo "")
  if [[ -n "$OLD_PID" && -e /proc/$OLD_PID ]]; then
    echo -e "${Y}⚙️ AutoExecutor already running (PID: $OLD_PID).${N}"
    echo -e "${Y}⏸️ Skipping restart to avoid duplicate instance.${N}"
    if [[ -n "$TG_TOKEN" && -n "$TG_CHAT" ]]; then
      MSG="⚠️ <b>AutoExecutor Already Running</b>%0APID: <code>${OLD_PID}</code>%0A🕐 $(date '+%H:%M:%S %d/%m/%Y')%0A⏸️ Restart skipped."
      curl -s -X POST "https://api.telegram.org/bot${TG_TOKEN}/sendMessage" \
           -d "chat_id=${TG_CHAT}" \
           -d "text=${MSG}" \
           -d "parse_mode=HTML" >/dev/null || true
    fi
    exit 0
  fi
fi

# --- עצירה של תהליך ישן (אם לא פעיל כראוי) ---
if [[ -f "$PID_FILE" ]]; then
  echo -e "${Y}🧹 Cleaning stale PID file...${N}"
  rm -f "$PID_FILE"
fi

# --- הפעלה מחדש ---
echo -e "${C}🚀 Launching new AutoExecutor...${N}"
nohup python3 -m utils.auto_executor >"$LOG_FILE" 2>&1 &
NEW_PID=$!
echo "$NEW_PID" >"$PID_FILE"

echo -e "${G}✅ AutoExecutor started successfully (PID: $NEW_PID)${N}"

# --- שליחת נוטיפיקציה לטלגרם ---
if [[ -n "$TG_TOKEN" && -n "$TG_CHAT" ]]; then
  MSG="♻️ <b>AutoExecutor Restarted</b>%0APID: <code>${NEW_PID}</code>%0ALogs: <code>${LOG_FILE}</code>%0A🕐 $(date '+%H:%M:%S %d/%m/%Y')"
  curl -s -X POST "https://api.telegram.org/bot${TG_TOKEN}/sendMessage" \
       -d "chat_id=${TG_CHAT}" \
       -d "text=${MSG}" \
       -d "parse_mode=HTML" >/dev/null || true
fi

echo -e "${C}📡 Log file: $LOG_FILE${N}"
echo -e "${G}Done.${N}"

