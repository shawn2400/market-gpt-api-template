#!/usr/bin/env bash
set -euo pipefail

# ======================================
# 🧩 AlgoGPT Full System Health Reporter
# ======================================

BASE="https://algogpt-docker.onrender.com"
BEARER="${API_BEARER_TOKEN:?missing API_BEARER_TOKEN in secrets}"
TG_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
TG_CHAT="${TELEGRAM_CHAT_ID:-}"
Y="\033[1;33m"; G="\033[1;32m"; R="\033[1;31m"; N="\033[0m"

ts() { date '+%Y-%m-%d %H:%M:%S'; }

send_tg() {
  local msg="$1"
  if [[ -n "$TG_TOKEN" && -n "$TG_CHAT" ]]; then
    curl -s -X POST "https://api.telegram.org/bot${TG_TOKEN}/sendMessage" \
         -d "chat_id=${TG_CHAT}" \
         -d "parse_mode=HTML" \
         --data-urlencode "text=${msg}" >/dev/null || true
  fi
}

section() { echo -e "\n==============================\n$1\n==============================\n"; }

# --- HEADERS ---
section "🧩 AlgoGPT Health Diagnostic"
echo -e "🕐 $(ts)"
echo

# --- 1️⃣ Render / API Check ---
echo -e "☁️ Checking Render..."
R_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/readyz" || echo "000")
if [[ "$R_CODE" == "200" ]]; then
  echo -e "${G}✅ Render reachable (HTTP 200)${N}"
  R_STATUS="✅ OK"
else
  echo -e "${R}❌ Render not reachable (HTTP $R_CODE)${N}"
  R_STATUS="❌ DOWN"
fi

# --- 2️⃣ Version ---
VER=$(curl -s -H "Authorization: Bearer $BEARER" "$BASE/version" | grep -o '"algogpt_version":"[^"]*"' | cut -d'"' -f4 || echo "unknown")
echo -e "🧠 Version: ${Y}${VER}${N}"

# --- 3️⃣ Telegram ---
echo -e "\n🤖 Checking Telegram bot..."
if curl -s -H "Authorization: Bearer $BEARER" "$BASE/telegram/status" | grep -q '"ok":true'; then
  echo -e "${G}✅ Telegram connected${N}"
  TG_STATUS="✅ OK"
else
  echo -e "${R}❌ Telegram disconnected${N}"
  TG_STATUS="❌ DOWN"
fi

# --- 4️⃣ PnL ---
echo -e "\n💰 Checking PnL export..."
if curl -s -H "Authorization: Bearer $BEARER" "$BASE/export/daily" | grep -q '"ok":true'; then
  echo -e "${G}✅ PnL export endpoint OK${N}"
  PNL_STATUS="✅ OK"
else
  echo -e "${Y}⚠️ PnL endpoint partial${N}"
  PNL_STATUS="⚠️ PARTIAL"
fi

# --- 5️⃣ Binance Futures ---
echo -e "\n🔐 Checking Binance API connectivity..."
if [[ -x "scripts/fix_binance_api.sh" ]]; then
  bash scripts/fix_binance_api.sh | tee /tmp/binance_report.txt || true
  if grep -q "✅ Futures balance reachable" /tmp/binance_report.txt; then
    BIN_STATUS="✅ OK"
  else
    BIN_STATUS="❌ FAIL"
  fi
else
  BIN_STATUS="⚠️ Missing"
  echo -e "${Y}⚠️ fix_binance_api.sh missing${N}"
fi

# --- 6️⃣ Summary ---
section "📊 Summary"
printf "☁️ Render: %s\n" "$R_STATUS"
printf "🤖 Telegram: %s\n" "$TG_STATUS"
printf "💰 PnL: %s\n" "$PNL_STATUS"
printf "🔐 Binance: %s\n" "$BIN_STATUS"
printf "🧠 Version: %s\n" "$VER"
echo

# --- STATUS AGGREGATION ---
if [[ "$R_STATUS" == *OK* && "$TG_STATUS" == *OK* && "$BIN_STATUS" == *OK* ]]; then
  OVERALL="🟢 SYSTEM HEALTH: OK ✅"
else
  OVERALL="🟡 SYSTEM HEALTH: WARNING ⚠️"
fi

echo -e "$OVERALL"

# --- Telegram Detailed Report ---
if [[ -n "$TG_TOKEN" && -n "$TG_CHAT" ]]; then
  MSG="<b>📊 AlgoGPT Health Report</b>\n"
  MSG+="🕐 $(ts)\n\n"
  MSG+="☁️ Render: <b>${R_STATUS}</b>\n"
  MSG+="🤖 Telegram: <b>${TG_STATUS}</b>\n"
  MSG+="💰 PnL: <b>${PNL_STATUS}</b>\n"
  MSG+="🔐 Binance: <b>${BIN_STATUS}</b>\n"
  MSG+="🧠 Version: <b>${VER}</b>\n\n"
  MSG+="$OVERALL"
  send_tg "$MSG"
fi

echo -e "\n✅ Report completed.\n"



