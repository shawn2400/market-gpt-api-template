#!/bin/bash
set -euo pipefail

if [ -z "${TELEGRAM_BOT_TOKEN:-}" ]; then
  echo "❌ TELEGRAM_BOT_TOKEN not set"
  exit 1
fi

# Get current Replit domain
if [ -n "${REPL_SLUG:-}" ] && [ -n "${REPL_OWNER:-}" ]; then
  DOMAIN="${REPL_SLUG}.${REPL_OWNER}.repl.co"
else
  DOMAIN=$(env | grep -i "replit.*domain" | head -1 | cut -d= -f2 | tr -d '\n' || echo "")
fi

if [ -z "$DOMAIN" ]; then
  echo "⚠️ Could not detect Replit domain. Please set manually:"
  echo "WEBHOOK_URL=https://YOUR-REPL-URL.repl.co/telegram/callback"
  exit 1
fi

WEBHOOK_URL="https://${DOMAIN}/telegram/callback"

echo "🔗 Setting Telegram webhook to: $WEBHOOK_URL"

# Delete old webhook first
curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/deleteWebhook"
echo ""

# Set new webhook
RESPONSE=$(curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook" \
  -d "url=${WEBHOOK_URL}" \
  -d "allowed_updates=[\"message\",\"callback_query\"]" \
  -d "drop_pending_updates=true")

echo "$RESPONSE"

if echo "$RESPONSE" | grep -q '"ok":true'; then
  echo "✅ Webhook set successfully!"
  echo "📱 Test by clicking a button in Telegram"
else
  echo "❌ Failed to set webhook"
  echo "Response: $RESPONSE"
fi

# Verify webhook info
echo ""
echo "📊 Current webhook info:"
curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getWebhookInfo" | jq '.'
