#!/usr/bin/env bash
set -euo pipefail

BASE="https://algogpt-docker.onrender.com"
TG_TOKEN="${TELEGRAM_BOT_TOKEN:?set TELEGRAM_BOT_TOKEN in secrets}"
TG_CHAT="${TELEGRAM_CHAT_ID:?set TELEGRAM_CHAT_ID in secrets}"
G="\033[1;32m"; R="\033[1;31m"; Y="\033[1;33m"; B="\033[1;34m"; N="\033[0m"

send_tg() {
  local msg="$1"
  curl -s -X POST "https://api.telegram.org/bot${TG_TOKEN}/sendMessage" \
       -d "chat_id=${TG_CHAT}" -d "text=${msg}" -d "parse_mode=HTML" >/dev/null || true
}

header() { echo -e "${B}\n==============================\n🚀 AlgoGPT Auto Deploy Started\n==============================${N}"; }

deploy() {
  header
  echo -e "${Y}📦 שלב 1: בדיקת מצב Git...${N}"
  git fetch origin main >/dev/null 2>&1 || true
  echo -e "${G}✅ Fetch הצליח${N}"

  if ! git diff --quiet; then
    echo -e "${Y}💾 שומר שינויים זמניים (stash)...${N}"
    git add -A && git stash push -m "auto-stash-before-deploy" >/dev/null || true
  fi

  echo -e "${Y}🔁 מרנדר שינויים מקומיים עם remote...${N}"
  git pull --rebase origin main || {
    echo -e "${R}⚠️ Rebase נכשל — מנסה פתרון אוטומטי${N}"
    git rebase --abort >/dev/null 2>&1 || true
    git reset --merge origin/main || true
  }

  echo -e "${Y}🧱 מבצע commit${N}"
  git add -A
  git commit -m "deploy: auto-sync $(date -u +'%Y-%m-%dT%H:%M:%S%z')" || true

  echo -e "${Y}🚀 שולח עדכון ל-GitHub...${N}"
  attempt=1
  until git push origin main >/dev/null 2>&1; do
    echo -e "${R}❌ ניסיון $attempt נכשל${N}"
    ((attempt++))
    if ((attempt > 3)); then
      echo -e "${R}💥 Git push נכשל אחרי 3 ניסיונות${N}"
      send_tg "❌ <b>Deploy Failed</b>\nReason: <code>Git push failed after 3 retries</code>"
      exit 1
    fi
    echo -e "${Y}⏳ מנסה שוב...${N}"
    git fetch origin main && git rebase origin/main || true
    sleep 3
  done

  echo -e "${G}✔️ Git push הצליח — Render יבצע Auto-Deploy${N}"

  echo -e "${Y}⌛ ממתין ש-Render יסיים להעלות גרסה חדשה...${N}"
  for i in {1..15}; do
    sleep 4
    status=$(curl -s "$BASE/readyz" || echo "fail")
    if [[ "$status" == *"ok"* || "$status" == *"true"* ]]; then
      echo -e "${G}✅ Render מוכן (${i})${N}"
      break
    fi
    echo -e "${Y}🔄 ממתין... ($i)${N}"
  done

  version=$(curl -s "$BASE/version" | grep -o '"algogpt_version":"[^"]*"' | cut -d'"' -f4 || echo "unknown")
  commit=$(git rev-parse --short HEAD)
  msg="✅ <b>Deploy Success</b>\n🌐 <a href='${BASE}'>Service Online</a>\n📦 Commit: <code>${commit}</code>\n🧠 Version: <code>${version}</code>"
  send_tg "$msg"

  echo -e "${G}✅ Deploy Success — Commit:${N} ${commit}"
  echo -e "${Y}📄 גרסה:${N} ${version}"
}

deploy

