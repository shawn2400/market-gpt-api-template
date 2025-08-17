cat <<'EOF' > setup_auth.sh
#!/usr/bin/env bash
set -euo pipefail

SERVICE_ID="srv-d2346lfgi27c73fii3ag"
RENDER_API_KEY="rnd_5rVtiIvxFqqEBzYNwTTH7NTdYiEt"
AUTH_TOKEN="MySecretAlgoGPT_123456789"

echo "[1] מגדיר AUTH_TOKEN חדש ב-Render..."
curl -sS -X PATCH "https://api.render.com/v1/services/$SERVICE_ID/env-vars" \
  -H "Authorization: Bearer $RENDER_API_KEY" \
  -H "Content-Type: application/json" \
  -d "[{\"key\":\"AUTH_TOKEN\",\"value\":\"$AUTH_TOKEN\"}]"

echo "[2] מפעיל רידפלוי לשירות..."
curl -sS -X POST "https://api.render.com/v1/services/$SERVICE_ID/deploys" \
  -H "Authorization: Bearer $RENDER_API_KEY"

echo "[3] מחכה כמה שניות שהשירות יעלה..."
sleep 15

echo "[4] בודק התחברות ל-API..."
curl -sS -H "Authorization: Bearer $AUTH_TOKEN" \
https://algogpt-docker.onrender.com/debug/auth-check
EOF
