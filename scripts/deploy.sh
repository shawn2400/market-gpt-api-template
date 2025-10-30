#!/usr/bin/env bash
set -euo pipefail

# === צבעים ===
G="\033[1;32m"; Y="\033[1;33m"; R="\033[1;31m"; N="\033[0m"

# === משתנים ===
RENDER_APP="algogpt-docker"
BASE="https://${RENDER_APP}.onrender.com"
BEARER="${API_BEARER_TOKEN:-}"
TG_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
TG_CHAT_ID="${TELEGRAM_CHAT_ID:-}"
LOG_FILE="deploy_log.txt"

# === פונקציה: שליחת טלגרם ===
notify_tg() {
  local text="$1"
  if [[ -n "$TG_TOKEN" && -n "$TG_CHAT_ID" ]]; then
    curl -s -X POST "https://api.telegram.org/bot${TG_TOKEN}/sendMessage" \
      -d "chat_id=${TG_CHAT_ID}" \
      -d "text=${text}" \
      -d "parse_mode=HTML" >/dev/null || true
  fi
}

# === לוג מקומי ===
log() { echo -e "$1" | tee -a "$LOG_FILE"; }

echo "" > "$LOG_FILE"
log "=============================="
log "🚀 AlgoGPT Auto Deploy Started"
log "=============================="

# === שלב 1: שמירת שינויים מקומיים ===
log "${Y}💾 שומר שינויים מקומיים...${N}"
git add -A || true
if git diff --cached --quiet; then
  log "ℹ️ אין שינויים לשמור."
else
  git commit -m "deploy: auto-fix $(date -Iseconds)" || true
fi

# === שלב 2: ריבייס עם ה־Remote ===
log "${Y}🔄 מבצע git fetch + rebase...${N}"
git fetch origin main || true
if ! git rebase origin/main; then
  log "${Y}⚠️ קונפליקט או שגיאה — מנסה שוב עם stash.${N}"
  git stash push -m "pre-rebase"
  git rebase origin/main || true
  git stash pop || true
fi

# === שלב 3: שליחת Commit ל־GitHub ===
commit_hash=$(git rev-parse --short HEAD || echo "unknown")
tries=0
until git push origin main; do
  tries=$((tries + 1))
  if (( tries >= 3 )); then
    log "${R}❌ Git push נכשל אחרי 3 ניסיונות.${N}"
    notify_tg "❌ <b>Deploy נכשל</b> אחרי 3 ניסיונות push 🚫%0ACommit: <code>${commit_hash}</code>"
    exit 1
  fi
  log "🔁 ניסיון נוסף (${tries}/3)..."
  sleep 3
done

log "${G}✔️ נשלח ל-GitHub. Render יבצע Auto-Deploy.${N}"
notify_tg "🚀 <b>AlgoGPT Deploy התחיל</b> 🔧%0A📦 Commit: <code>${commit_hash}</code>"

# === שלב 4: המתנה ל-Render ===
log "${Y}⌛ ממתין ש-Render יעלה גרסה חדשה...${N}"
for i in {1..20}; do
  sleep 10
  STATUS=$(curl -fs -o /dev/null -w "%{http_code}" "$BASE/readyz" || true)
  if [[ "$STATUS" == "200" ]]; then
    version_json=$(curl -fsS -H "Authorization: Bearer $BEARER" "$BASE/version" || echo "")
    log "${G}✅ Render מוכן (${BASE})${N}"
    log "📄 גרסה: ${version_json}"
    notify_tg "✅ <b>Deploy הושלם בהצלחה</b>%0A🌐 <code>${BASE}</code>%0ACommit: <code>${commit_hash}</code>%0A📄 גרסה: <code>${version_json}</code>"
    exit 0
  fi
  log "🔄 עדיין ממתין (status=$STATUS)..."
done

log "${R}❌ Render לא עלה בזמן.${N}"
notify_tg "⚠️ <b>Deploy נכשל</b> – Render לא עלה בזמן ⏱️%0ACommit: <code>${commit_hash}</code>"
exit 1

