#!/usr/bin/env bash
set -euo pipefail

BASE="${BASE:-https://algogpt-docker.onrender.com}"
BEARER="${API_BEARER_TOKEN:?Missing API_BEARER_TOKEN}"
BOT="${TELEGRAM_BOT_TOKEN:-}"
CHAT="${TELEGRAM_CHAT_ID:-}"
STATE_FILE="/tmp/algogpt_market_state.txt"

escape_html() { sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g'; }

send_telegram() {
  local msg="$1"
  if [[ -n "$BOT" && -n "$CHAT" ]]; then
    curl -s -X POST "https://api.telegram.org/bot${BOT}/sendMessage" \
      -d "chat_id=${CHAT}" \
      -d "text=${msg}" \
      -d "parse_mode=HTML" >/dev/null && echo "✅ Telegram message sent"
  else
    echo "⚠️ Telegram not configured"
  fi
}

# === Fetch indicators ===
get_ind() {
  curl -fsS "$BASE/scan/public-now?symbols=BTCUSDT&indicators=1" 2>/dev/null
}

# --- Parse BTCUSDT indicators ---
raw=$(get_ind)
rsi=$(echo "$raw" | grep -o '"rsi":[0-9.]*' | cut -d: -f2 | head -1)
adx=$(echo "$raw" | grep -o '"adx":[0-9.]*' | cut -d: -f2 | head -1)
macd=$(echo "$raw" | grep -o '"macd":[0-9.-]*' | cut -d: -f2 | head -1)

regime="NEUTRAL"
interval_hr=6
alert=""

if (( $(echo "$adx > 25" | bc -l) )); then
  if (( $(echo "$macd > 0" | bc -l) )); then
    regime="TREND_UP"
    interval_hr=2
  else
    regime="TREND_DOWN"
    interval_hr=2
  fi
elif (( $(echo "$adx < 15" | bc -l) )); then
  regime="CHOP"
  interval_hr=12
elif (( $(echo "$rsi > 70" | bc -l) )); then
  regime="REVERSAL_SHORT"
  interval_hr=4
elif (( $(echo "$rsi < 30" | bc -l) )); then
  regime="REVERSAL_LONG"
  interval_hr=4
fi

# === Check if regime changed ===
last_state=$(cat "$STATE_FILE" 2>/dev/null || echo "UNKNOWN")
if [[ "$regime" != "$last_state" ]]; then
  echo "$regime" > "$STATE_FILE"
  case "$regime" in
    TREND_UP)
      alert="🔥 BTC entered <b>UP TREND</b> — Auto-Trading ENABLED"
      curl -fsS -X POST -H "Authorization: Bearer $BEARER" "$BASE/trade/auto-on" >/dev/null
      ;;
    TREND_DOWN)
      alert="📉 BTC in <b>DOWN TREND</b> — Auto-Trading ENABLED"
      curl -fsS -X POST -H "Authorization: Bearer $BEARER" "$BASE/trade/auto-on" >/dev/null
      ;;
    CHOP)
      alert="⚠️ CHOP ZONE detected — Auto-Trading DISABLED"
      curl -fsS -X POST -H "Authorization: Bearer $BEARER" "$BASE/trade/auto-off" >/dev/null
      ;;
    REVERSAL_SHORT)
      alert="🔄 Overbought Zone — favor SHORT setups"
      ;;
    REVERSAL_LONG)
      alert="🔄 Oversold Zone — favor LONG setups"
      ;;
    *)
      alert="ℹ️ Neutral state — monitoring"
      ;;
  esac
fi

# === Build market report ===
ver=$(curl -fsS "$BASE/health" | grep -o '"algogpt_version":"[^"]*"' | cut -d'"' -f4)
render=$(curl -fsS "$BASE/readyz" >/dev/null 2>&1 && echo "🟢 OK" || echo "🔴 DOWN")
tele=$(curl -fsS -H "Authorization: Bearer $BEARER" "$BASE/telegram/status" 2>/dev/null | grep -o '"state":"[^"]*"' | cut -d'"' -f4)
trades=$(curl -fsS -H "Authorization: Bearer $BEARER" "$BASE/trade/active" 2>/dev/null | grep -c '"symbol"')
pnl=$(curl -fsS -H "Authorization: Bearer $BEARER" "$BASE/export/daily" 2>/dev/null | grep -E '"total_profit"|total_loss' | head -3 | sed 's/[{}\",]//g')

market_data=$(curl -fsS "$BASE/scan/public-now?indicators=1&symbols=BTCUSDT,ETHUSDT,SOLUSDT" 2>/dev/null | grep -E '"symbol"|"rsi"|"macd"|"trend"|"price"' | head -20 | sed 's/[{}\",]//g' | escape_html)
ai_suggestion=$(curl -fsS -H "Authorization: Bearer $BEARER" "$BASE/ai/summary" 2>/dev/null | head -10 | escape_html)
top_trades=$(curl -fsS -H "Authorization: Bearer $BEARER" "$BASE/export/daily" 2>/dev/null | grep -E '"symbol"|"pnl"|"side"' | head -15 | escape_html)

now=$(date '+%Y-%m-%d %H:%M:%S %Z')

msg="<b>📊 AlgoGPT — Live Market Intelligence</b>\n"
msg+="🕐 ${now}\n"
msg+="<b>🧠 Version:</b> <code>${ver:-unknown}</code>\n"
msg+="<b>☁️ Render:</b> ${render}\n"
msg+="<b>🤖 Telegram:</b> ${tele:-offline}\n"
msg+="<b>💰 Active Trades:</b> ${trades}\n\n"
msg+="<b>📈 Market Regime:</b> ${regime}\n"
[[ -n "$alert" ]] && msg+="<b>📢 Alert:</b> ${alert}\n\n"
msg+="<b>🕒 Next Report In:</b> <code>${interval_hr}h</code>\n\n"
msg+="<b>📊 PnL:</b>\n<pre>$(echo "$pnl" | escape_html)</pre>\n"
msg+="──────────────────────────────\n"
msg+="<b>🪙 Market Snapshot (BTC/ETH/SOL):</b>\n<pre>${market_data}</pre>\n"
msg+="──────────────────────────────\n"
msg+="<b>🧭 AI Summary:</b>\n<pre>${ai_suggestion}</pre>\n"
msg+="──────────────────────────────\n"
msg+="✅ System OK — Dynamic Interval ${interval_hr}h"

send_telegram "$msg"
echo "✅ Auto Intel report sent (${regime})"
sleep "$((interval_hr * 3600))"
exec "$0"
