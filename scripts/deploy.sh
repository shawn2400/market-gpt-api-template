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

# === פונקציית שליחת הודעות לטלגרם ===
notify_tg() {
  local text="$1"
  if [[ -n "$TG_TOKEN" && -n "$TG_CHAT_ID" ]]; then
    curl -s -X POST "https://api.telegram.org/bot${TG_TOKEN}/sendMessage" \
      -d "chat_id=${TG_CHAT_ID}" \
      -d "text=${text}" \
      -d "parse_mode=HTML" >/dev/null || true
  fi
}

# === פונקציה לרישום ללוג ===
log() {
  echo -e "$1" | tee -a "$LOG_FILE"
}

echo "" > "$LOG_FILE"
log "=============================="
log "🚀 AlgoGPT Auto Deploy Started"
log "=============================="

# === שלב 1: סנכרון עם GitHub ===
log "${Y}📥  מושך עדכונים מ-GitHub...${N}"
git fetch origin main >>"$LOG_FILE" 2>&1
git rebase origin/main || true

log "${Y}▶️  שולח עדכונים ל-GitHub...${N}"
git add -A
git_commit_msg="deploy: auto-fix $(date -Iseconds)"
git commit -m "$git_commit_msg" || true

commit_hash=$(git rev-parse --short HEAD || echo "unknown")

if git push origin main >>"$LOG_FILE" 2>&1; then
  log "${G}✔️  נשלח ל-GitHub. Render יבצע Auto-Deploy.${N}"
  notify_tg "🚀 <b>AlgoGPT Deploy</b> התחיל 🔧%0ACommit: <code>${commit_hash}</code>%0A📦 ${git_commit_msg}"
else
  log "${R}❌ בעיה ב-push ל-GitHub.${N}"
  notify_tg "❌ <b>Deploy נכשל</b> בזמן push ל-GitHub 🚫%0ACommit: <code>${commit_hash}</code>"
  exit 1
fi

# === שלב 2: בדיקת Render ===
log "${Y}⌛  ממתין ש-Render יעלה גרסה חדשה...${N}"
for i in {1..20}; do
  sleep 10
  STATUS=$(curl -fs -o /dev/null -w "%{http_code}" "$BASE/readyz" || true)
  if [[ "$STATUS" == "200" ]]; then
    log "${G}✅ Render מוכן (${BASE})${N}"
    version_json=$(curl -fsS -H "Authorization: Bearer $BEARER" "$BASE/version" || echo "")
    log "📄 גרסת שירות: ${version_json}"
    notify_tg "✅ <b>Deploy הושלם בהצלחה</b>%0A🌐 <code>${BASE}</code>%0ACommit: <code>${commit_hash}</code>%0A📄 גרסה: <code>${version_json}</code>"
    log "✅ Deploy Success — ${commit_hash}"
    exit 0
  fi
  log "🔄 עדיין בטעינה (status=$STATUS)..."
done

# === Render לא עלה ===
log "${R}❌ Render לא חזר ל-OK אחרי 200 שניות.${N}"
notify_tg "⚠️ <b>Deploy נכשל</b> – Render לא עלה בזמן ⏱️%0ACommit: <code>${commit_hash}</code>%0A📎 לוג: <code>${BASE}/static/deploy_log.txt</code>"
exit 1

