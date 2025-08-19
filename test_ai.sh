#!/usr/bin/env bash
set -euo pipefail

HOST="https://algogpt-docker.onrender.com"
TOKEN="${API_BEARER_TOKEN:-}"

if [ -z "$TOKEN" ]; then
  echo "❌ שגיאה: לא הוגדר API_BEARER_TOKEN"
  exit 1
fi

AUTH=(-H "Authorization: Bearer $TOKEN")

echo "🔄 בדיקה לנתיב /ai/health..."
curl -sS "${AUTH[@]}" "$HOST/ai/health" | tee ai_health.json
echo

if grep -q '"ok": true' ai_health.json; then
  echo "✅ AI מוכן (חיבור ל־OpenAI תקין)"
else
  echo "❌ בעיה – בדוק ai_health.json (כנראה חסר OPENAI_API_KEY או לא תקין)"
fi
