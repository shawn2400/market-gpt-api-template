#!/usr/bin/env bash
set -euo pipefail

# === צבעים ===
G="\033[1;32m"; R="\033[1;31m"; Y="\033[1;33m"; C="\033[1;36m"; N="\033[0m"

# === קונפיג טלגרם ===
TG_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
TG_CHAT="${TELEGRAM_CHAT_ID:-}"
send_tg() {
  local msg="$1"
  if [[ -n "$TG_TOKEN" && -n "$TG_CHAT" ]]; then
    curl -s -X POST "https://api.telegram.org/bot${TG_TOKEN}/sendMessage" \
      -d "chat_id=${TG_CHAT}" \
      -d "text=${msg}" \
      -d "parse_mode=HTML" >/dev/null || true
  fi
}

# === Git branch ===
BRANCH="${GIT_BRANCH:-main}"
START_TS=$(date +%s)

echo -e "${C}🔧 Starting Git auto-fix & sync...${N}"
send_tg "⚙️ <b>Git Auto-Sync Started</b>\nBranch: <code>${BRANCH}</code>\n⏱️ $(date '+%H:%M:%S %d/%m/%Y')"

# === שמירת שינויים ===
echo -e "${Y}📦 Stashing local changes...${N}"
git add -A || true
git stash || true

# === עדכון מה־remote ===
echo -e "${Y}🌐 Fetching latest from origin/${BRANCH}...${N}"
git fetch origin "$BRANCH" || true

# === מיזוג (rebase / pull) ===
echo -e "${Y}🔁 Rebasing local branch...${N}"
git rebase origin/"$BRANCH" || git pull --rebase origin "$BRANCH" || true

# === החזרת השינויים שלך ===
echo -e "${Y}📤 Restoring local stash...${N}"
git stash pop || true
git add -A || true

# === תיקון קונפליקטים ===
echo -e "${Y}🪄 Resolving merge conflicts...${N}"
git commit -am "auto-merge: resolved sync conflicts" || true

# === Push ל־GitHub ===
echo -e "${Y}🚀 Pushing branch to origin...${N}"
git push origin "$BRANCH" || git push -f origin "$BRANCH"

DURATION=$(( $(date +%s) - START_TS ))

echo -e "${G}✅ Git sync completed successfully in ${DURATION}s.${N}"
send_tg "✅ <b>Git Auto-Sync Success</b>\nBranch: <code>${BRANCH}</code>\nDuration: <b>${DURATION}s</b>\n🕐 $(date '+%H:%M:%S %d/%m/%Y')"

