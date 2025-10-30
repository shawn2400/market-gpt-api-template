#!/usr/bin/env bash
set -euo pipefail

# צבעים
G="\033[1;32m"; Y="\033[1;33m"; R="\033[1;31m"; N="\033[0m"

echo -e "${Y}▶️  שולח עדכונים ל-GitHub...${N}"
git add -A
git commit -m "deploy: auto-fix $(date -Iseconds)" || true
git push origin main
echo -e "${G}✔️  נשלח ל-GitHub. Render יבצע Auto-Deploy.${N}"

# בדיקת מצב השירות ב-Render
RENDER_APP="algogpt-docker"   # שנה אם שם השירות שונה
BASE="https://${RENDER_APP}.onrender.com"

echo -e "${Y}⌛  ממתין ש-Render יעלה גרסה חדשה...${N}"
for i in {1..20}; do
  sleep 10
  STATUS=$(curl -fs -o /dev/null -w "%{http_code}" "$BASE/readyz" || true)
  if [[ "$STATUS" == "200" ]]; then
    echo -e "${G}✅ Render מוכן (${BASE})${N}"
    curl -fsS "$BASE/version" || true
    exit 0
  fi
  echo -e "🔄 עדיין בטעינה (status=$STATUS)..."
done

echo -e "${R}❌ לא התקבל OK מ-Render אחרי 200 שניות.${N}"
exit 1
