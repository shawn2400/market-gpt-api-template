#!/usr/bin/env bash
set -euo pipefail

# === צבעים ===
G="\033[1;32m"; R="\033[1;31m"; Y="\033[1;33m"; C="\033[1;36m"; N="\033[0m"

# === Telegram Config ===
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

# === Branch & Start Time ===
BRANCH="${GIT_BRANCH:-main}"
START_TS=$(date +%s)
echo -e "${C}🔧 Starting Git auto-fix & sync...${N}"
send_tg "⚙️ <b>Git Auto-Sync Started</b>\nBranch: <code>${BRANCH}</code>\n⏱️ $(date '+%H:%M:%S %d/%m/%Y')"

# === Backup & Fetch ===
echo -e "${Y}📦 Stashing local changes...${N}"
git add -A || true
git stash || true
echo -e "${Y}🌐 Fetching latest from origin/${BRANCH}...${N}"
git fetch origin "$BRANCH" || true

# === Rebase & Restore ===
echo -e "${Y}🔁 Rebasing local branch...${N}"
if ! git rebase origin/"$BRANCH"; then
  echo -e "${R}⚠️ Rebase failed. Attempting pull --rebase...${N}"
  git pull --rebase origin "$BRANCH" || true
fi

echo -e "${Y}📤 Restoring local stash...${N}"
git stash pop || true
git add -A || true
git commit -am "auto-merge: resolved sync conflicts" || true

# === Push + Auto-Heal ===
echo -e "${Y}🚀 Pushing branch to origin...${N}"
if ! git push origin "$BRANCH"; then
  echo -e "${R}⚠️ Push failed. Attempting Auto-Heal...${N}"
  send_tg "🧩 <b>Git Auto-Heal Activated</b>\nTrying to repair conflicts and re-sync..."
  git fetch origin "$BRANCH" || true
  git rebase origin/"$BRANCH" || git merge origin/"$BRANCH" || true
  git add -A || true
  git commit -am "auto-heal: resolved sync conflicts" || true
  git push -f origin "$BRANCH" && send_tg "✅ <b>Auto-Heal Success</b>\nAll conflicts resolved and branch synced!" || send_tg "❌ <b>Auto-Heal Failed</b>\nManual fix required ⚠️"
else
  send_tg "✅ <b>Git Auto-Sync Success</b>\nBranch: <code>${BRANCH}</code>\nDuration: <b>$(( $(date +%s) - START_TS ))s</b>\n🕐 $(date '+%H:%M:%S %d/%m/%Y')"
  echo -e "${G}✅ Git sync completed successfully.${N}"
fi
