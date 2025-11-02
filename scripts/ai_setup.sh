#!/bin/bash
# ===========================================
# 🔧 AlgoGPT Unified AI Setup – Replit Optimized
# ===========================================
# Purpose: Connect all AI agents (Replit, DeepSeek, Grok, GPT-5)
# to your current server with automatic validation
# ===========================================

echo "🚀 Starting AlgoGPT AI Setup (Replit Environment)"

# --- General Settings ---
export BASE_URL="${PUBLIC_HOST:-http://localhost:5000}"
export APP_MODE="production"
export AGENT_ROLE="maintenance"
export AGENT_MODE="autofix"
export AIX_MODE="supervisor"

# --- API Keys (from environment) ---
export GITHUB_TOKEN="${GITHUB_TOKEN}"
export AIX_SUPERVISOR_TOKEN="${AIX_SUPERVISOR_TOKEN}"
export DEEPSEEK_API_KEY="${DEEPSEEK_API_KEY}"
export OPENAI_API_KEY="${OPENAI_API_KEY}"
export API_BEARER_TOKEN="${API_BEARER_TOKEN:-${API_TOKEN}}"
export BINANCE_API_KEY="${BINANCE_API_KEY}"
export BINANCE_API_SECRET="${BINANCE_API_SECRET}"
export TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN}"

echo "✅ Environment variables loaded"

# --- Verify required tools (Replit has these by default) ---
command -v curl >/dev/null 2>&1 || { echo "❌ curl not found"; exit 1; }
command -v jq >/dev/null 2>&1 || echo "⚠️ jq not found (optional)"

# --- GitHub Configuration ---
if [ -n "$GITHUB_TOKEN" ]; then
  git config --global user.name "AlgoGPT-Auto" 2>/dev/null
  git config --global user.email "algogpt@system.local" 2>/dev/null
  echo "✅ GitHub credentials configured"
else
  echo "⚠️ GITHUB_TOKEN not set – Git operations may fail"
fi

# --- Check Replit Agent Status ---
echo ""
echo "🤖 Checking Replit Agent..."
if [ -n "$REPL_ID" ]; then
  echo "✅ Running on Replit (REPL_ID: ${REPL_ID:0:8}...)"
  echo "✅ Replit Agent available for maintenance tasks"
else
  echo "⚠️ Not running on Replit or REPL_ID missing"
fi

# --- Test AI X (Grok) Connection ---
echo ""
echo "🧠 Testing AI X (Grok) API..."
if [ -n "$AIX_SUPERVISOR_TOKEN" ]; then
  response=$(curl -s -w "\n%{http_code}" --max-time 10 \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $AIX_SUPERVISOR_TOKEN" \
    -d '{"messages":[{"role":"user","content":"ping"}],"model":"grok-beta","stream":false}' \
    https://api.x.ai/v1/chat/completions)
  
  http_code=$(echo "$response" | tail -n1)
  body=$(echo "$response" | head -n-1)
  
  if [ "$http_code" = "200" ]; then
    echo "✅ AI X (Grok) Connected Successfully"
  else
    echo "⚠️ AI X Connection Issue (HTTP $http_code)"
    echo "   Response: ${body:0:100}"
  fi
else
  echo "⚠️ AIX_SUPERVISOR_TOKEN not set – Skipping Grok test"
fi

# --- Test DeepSeek API ---
echo ""
echo "🧮 Testing DeepSeek API..."
if [ -n "$DEEPSEEK_API_KEY" ]; then
  response=$(curl -s -w "\n%{http_code}" --max-time 10 \
    -H "Authorization: Bearer $DEEPSEEK_API_KEY" \
    -H "Content-Type: application/json" \
    -d '{"model":"deepseek-chat","messages":[{"role":"user","content":"test"}]}' \
    https://api.deepseek.com/v1/chat/completions)
  
  http_code=$(echo "$response" | tail -n1)
  
  if [ "$http_code" = "200" ]; then
    echo "✅ DeepSeek Connected Successfully"
  else
    echo "⚠️ DeepSeek Connection Issue (HTTP $http_code)"
  fi
else
  echo "⚠️ DEEPSEEK_API_KEY not set – Skipping DeepSeek test"
fi

# --- Test OpenAI (GPT-5 / GPT-4) ---
echo ""
echo "🤖 Testing OpenAI API..."
if [ -n "$OPENAI_API_KEY" ]; then
  response=$(curl -s -w "\n%{http_code}" --max-time 10 \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $OPENAI_API_KEY" \
    -d '{"model":"gpt-4o","messages":[{"role":"user","content":"test"}]}' \
    https://api.openai.com/v1/chat/completions)
  
  http_code=$(echo "$response" | tail -n1)
  
  if [ "$http_code" = "200" ]; then
    echo "✅ OpenAI (GPT) Connected Successfully"
  else
    echo "⚠️ OpenAI Connection Issue (HTTP $http_code)"
  fi
else
  echo "⚠️ OPENAI_API_KEY not set – Skipping OpenAI test"
fi

# --- Test Binance API ---
echo ""
echo "💰 Testing Binance API..."
if [ -n "$BINANCE_API_KEY" ]; then
  response=$(curl -s -w "\n%{http_code}" --max-time 10 \
    "https://fapi.binance.com/fapi/v1/time")
  
  http_code=$(echo "$response" | tail -n1)
  
  if [ "$http_code" = "200" ]; then
    echo "✅ Binance API Reachable"
  else
    echo "⚠️ Binance API Issue (HTTP $http_code)"
  fi
else
  echo "⚠️ BINANCE_API_KEY not set – Skipping Binance test"
fi

# --- Test Telegram Bot ---
echo ""
echo "💬 Testing Telegram Bot..."
if [ -n "$TELEGRAM_BOT_TOKEN" ]; then
  response=$(curl -s -w "\n%{http_code}" --max-time 10 \
    "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getMe")
  
  http_code=$(echo "$response" | tail -n1)
  body=$(echo "$response" | head -n-1)
  
  if [ "$http_code" = "200" ]; then
    bot_name=$(echo "$body" | grep -o '"username":"[^"]*"' | cut -d'"' -f4)
    echo "✅ Telegram Bot Connected (@${bot_name})"
  else
    echo "⚠️ Telegram Bot Connection Issue (HTTP $http_code)"
  fi
else
  echo "⚠️ TELEGRAM_BOT_TOKEN not set – Skipping Telegram test"
fi

# --- System Health Check ---
echo ""
echo "📊 Running System Health Check..."

# Check if server is running
if curl -s --max-time 5 "${BASE_URL}/readyz" >/dev/null 2>&1; then
  echo "✅ AlgoGPT Server is UP (${BASE_URL})"
else
  echo "⚠️ AlgoGPT Server not responding at ${BASE_URL}"
fi

# --- Summary Report ---
echo ""
echo "======================================"
echo "🧾 AI SETUP SUMMARY"
echo "======================================"
echo "Base URL: $BASE_URL"
echo "Environment: ${APP_MODE}"
echo ""
echo "AI Agents Status:"
echo "  - Replit Agent: $( [ -n "$REPL_ID" ] && echo "✅ Available" || echo "⚠️ Not on Replit" )"
echo "  - AI X (Grok): $( [ -n "$AIX_SUPERVISOR_TOKEN" ] && echo "✅ Configured" || echo "❌ Missing" )"
echo "  - DeepSeek: $( [ -n "$DEEPSEEK_API_KEY" ] && echo "✅ Configured" || echo "❌ Missing" )"
echo "  - OpenAI: $( [ -n "$OPENAI_API_KEY" ] && echo "✅ Configured" || echo "❌ Missing" )"
echo "  - Binance: $( [ -n "$BINANCE_API_KEY" ] && echo "✅ Configured" || echo "❌ Missing" )"
echo "  - Telegram: $( [ -n "$TELEGRAM_BOT_TOKEN" ] && echo "✅ Configured" || echo "❌ Missing" )"
echo ""
echo "======================================"
echo "✅ AI Setup Check Complete"
echo "======================================"

# --- Save Report ---
REPORT_FILE="/tmp/ai_setup_report_$(date +%s).txt"
{
  echo "AlgoGPT AI Setup Report"
  echo "Generated: $(date)"
  echo "========================"
  echo ""
  echo "Environment Variables:"
  echo "  BASE_URL: $BASE_URL"
  echo "  REPL_ID: ${REPL_ID:-Not set}"
  echo ""
  echo "API Keys Status:"
  echo "  AIX_SUPERVISOR_TOKEN: $( [ -n "$AIX_SUPERVISOR_TOKEN" ] && echo "SET (${#AIX_SUPERVISOR_TOKEN} chars)" || echo "NOT SET" )"
  echo "  DEEPSEEK_API_KEY: $( [ -n "$DEEPSEEK_API_KEY" ] && echo "SET (${#DEEPSEEK_API_KEY} chars)" || echo "NOT SET" )"
  echo "  OPENAI_API_KEY: $( [ -n "$OPENAI_API_KEY" ] && echo "SET (${#OPENAI_API_KEY} chars)" || echo "NOT SET" )"
  echo "  BINANCE_API_KEY: $( [ -n "$BINANCE_API_KEY" ] && echo "SET (${#BINANCE_API_KEY} chars)" || echo "NOT SET" )"
  echo "  TELEGRAM_BOT_TOKEN: $( [ -n "$TELEGRAM_BOT_TOKEN" ] && echo "SET (${#TELEGRAM_BOT_TOKEN} chars)" || echo "NOT SET" )"
} > "$REPORT_FILE"

echo ""
echo "📄 Full report saved: $REPORT_FILE"
echo ""
echo "🎯 Next Steps:"
echo "   1. Fix any ⚠️ warnings above"
echo "   2. Ensure render.com has the same environment variables"
echo "   3. Deploy code changes to render.com for production"
