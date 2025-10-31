#!/usr/bin/env bash
set -euo pipefail
G="\033[1;32m"; R="\033[1;31m"; Y="\033[1;33m"; C="\033[1;36m"; N="\033[0m"

echo -e "${C}⚙️ Activating Render Executor Mode...${N}"

# === בדיקה באיזו סביבה אנחנו ===
if hostname | grep -qi "render"; then
  echo -e "${G}✅ Running on Render environment${N}"
  EXEC_ENV="render"
else
  echo -e "${Y}⚠️ Not detected as Render — forcing Render route mode${N}"
  EXEC_ENV="forced-render"
fi

# === בדיקת מפתחות Binance ===
if [[ -z "${BINANCE_API_KEY:-}" || -z "${BINANCE_API_SECRET:-}" ]]; then
  echo -e "${R}❌ Missing Binance API keys${N}"
  exit 1
fi

# === בדיקת חתימה אמיתית ===
TS=$(date +%s%3N)
QS="timestamp=$TS"
SIG=$(echo -n "$QS" | openssl dgst -sha256 -hmac "$BINANCE_API_SECRET" -hex | sed 's/^.* //')

echo -e "${Y}🔍 Checking Binance Futures permissions...${N}"
RESP=$(curl -s -w "\n%{http_code}" -H "X-MBX-APIKEY: $BINANCE_API_KEY" "https://fapi.binance.com/fapi/v2/account?$QS&signature=$SIG")
BODY=$(echo "$RESP" | head -n1)
CODE=$(echo "$RESP" | tail -n1)

if [[ "$CODE" == "200" ]]; then
  echo -e "${G}✅ Binance Futures access confirmed${N}"
else
  echo -e "${R}⚠️ Binance connection failed ($CODE)${N}"
  echo "$BODY"
  echo -e "\n🩻 Verify in Binance:\n☑️ Enable Reading\n☑️ Enable Futures\n☑️ IP unrestricted or includes Render IP."
  exit 1
fi

# === בדיקת DRY_RUN ===
if [[ "${DRY_RUN:-true}" == "true" ]]; then
  echo -e "${Y}⚠️ DRY_RUN is still enabled. Disabling now...${N}"
  export DRY_RUN=false
else
  echo -e "${G}✅ DRY_RUN already disabled${N}"
fi

# === בדיקת משתני סביבה קריטיים ===
req_vars=(API_BEARER_TOKEN TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID)
for v in "${req_vars[@]}"; do
  if [[ -z "${!v:-}" ]]; then
    echo -e "${Y}⚠️ Missing env var: $v${N}"
  else
    echo -e "${G}✅ $v detected${N}"
  fi
done

# === סימון שה־Render מנהל טריידים ===
echo -e "\n${C}📦 Writing executor state marker...${N}"
mkdir -p static/cache
echo "{\"executor\":\"$EXEC_ENV\",\"timestamp\":\"$TS\"}" > static/cache/executor_state.json
echo -e "${G}✅ Executor route updated to Render${N}"

# === נוטיפיקציה לטלגרם ===
if [[ -n "${TELEGRAM_BOT_TOKEN:-}" && -n "${TELEGRAM_CHAT_ID:-}" ]]; then
  MSG="✅ <b>Render Executor Activated</b>%0AAll trades will now route via Render.%0A🕐 $(date '+%H:%M:%S %d/%m/%Y')"
  curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
       -d "chat_id=${TELEGRAM_CHAT_ID}" -d "text=${MSG}" -d "parse_mode=HTML" >/dev/null || true
fi

# === הפעלה מחדש של AutoExecutor ===
if [[ -x "scripts/auto_executor_restart.sh" ]]; then
  echo -e "${C}♻️ Restarting AutoExecutor...${N}"
  bash scripts/auto_executor_restart.sh
  echo -e "${G}✅ AutoExecutor restarted${N}"
else
  echo -e "${Y}ℹ️ No auto_executor_restart.sh found, skipping restart${N}"
fi

echo -e "${G}🚀 Render Executor is now active and managing live trades!${N}"
