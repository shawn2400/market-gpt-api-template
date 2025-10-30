#!/usr/bin/env bash
set -euo pipefail

BASE="${BASE:-https://algogpt-docker.onrender.com}"
BEARER="${API_BEARER_TOKEN:?Missing API_BEARER_TOKEN}"
BOT="${TELEGRAM_BOT_TOKEN:-}"
CHAT="${TELEGRAM_CHAT_ID:-}"

escape_html() { sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g'; }

send_telegram() {
  local msg="$1"
  if [[ -n "$BOT" && -n "$CHAT" ]]; then
    curl -s -X POST "https://api.telegram.org/bot${BOT}/sendMessage" \
      -d "chat_id=${CHAT}" \
      -d "text=${msg}" \
      -d "parse_mode=HTML" >/dev/null && echo "✅ Report sent to Telegram"
  else
    echo "⚠️ Telegram not configured"
  fi
}

# === System Info ===
ver=$(curl -fsS "$BASE/health" 2>/dev/null | grep -o '"algogpt_version":"[^"]*"' | cut -d'"' -f4)
render=$(curl -fsS "$BASE/readyz" >/dev/null 2>&1 && echo "🟢 OK" || echo "🔴 DOWN")
tele=$(curl -fsS -H "Authorization: Bearer $BEARER" "$BASE/telegram/status" 2>/dev/null | grep -o '"state":"[^"]*"' | cut -d'"' -f4)
trades=$(curl -fsS -H "Authorization: Bearer $BEARER" "$BASE/trade/active" 2>/dev/null | grep -c '"symbol"')
pnl=$(curl -fsS -H "Authorization: Bearer $BEARER" "$BASE/export/daily" 2>/dev/null | grep -E '"total_profit"|total_loss' | head -3 | sed 's/[{}\",]//g')

# === Market Snapshot (BTCUSDT) ===
rsi=$(curl -fsS "$BASE/scan/public-now?symbols=BTCUSDT&indicators=1" 2>/dev/null | grep -o '"rsi":[0-9.]*' | cut -d: -f2 | head -1)
adx=$(curl -fsS "$BASE/scan/public-now?symbols=BTCUSDT&indicators=1" 2>/dev/null | grep -o '"adx":[0-9.]*' | cut -d: -f2 | head -1)
macd=$(curl -fsS "$BASE/scan/public-now?symbols=BTCUSDT&indicators=1" 2>/dev/null | grep -o '"macd":[0-9.-]*' | cut -d: -f2 | head -1)

regime="Unknown"
interval_hr=6
if [[ -n "$adx" ]]; then
  if (( $(echo "$adx > 25" | bc -l) )); then
    if (( $(echo "$macd > 0" | bc -l) )); then
      regime="📈 STRONG TREND (Favor Pullbacks)"
      interval_hr=2
    else
      regime="📉 STRONG DOWNTREND (Favor Breakdowns)"
      interval_hr=2
    fi
  elif (( $(echo "$adx < 15" | bc -l) )); then
    regime="⚠️ CHOP ZONE (Avoid Breakouts)"
    interval_hr=12
  elif (( $(echo "$rsi > 70" | bc -l) )); then
    regime="🔄 REVERSAL ZONE (Possible Short Setup)"
    interval_hr=4
  elif (( $(echo "$rsi < 30" | bc -l) )); then
    regime="🔄 REVERSAL ZONE (Possible Long Setup)"
    interval_hr=4
  fi
fi

# === Extra Data for the Report ===
market_data=$(curl -fsS "$BASE/scan/public-now?indicators=1&symbols=BTCUSDT,ETHUSDT,SOLUSDT" 2>/dev/null | grep -E '"symbol"|"rsi"|"macd"|"trend"|"price"' | head -20 | sed 's/[{}\",]//g' | escape_html)
top_trades=$(curl -fsS -H "Authorization: Bearer $BEARER" "$BASE/export/daily" 2>/dev/null | grep -E '"symbol"|"pnl"|"side"' | head -15 | escape_html)
ai_suggestion=$(curl -fsS -H "Authorization: Bearer $BEARER" "$BASE/ai/summary" 2>/dev/null | head -10 | escape_html)

now=$(date '+%Y-%m-%d %H:%M:%S %Z')

msg="<b>📊 AlgoGPT — Adaptive Market Report</b>\n"
msg+="🕐 <b>${now}</b>\n\n"
msg+="<b>🧠 Version:</b> <code>${ver:-unknown}</code>\n"
msg+="<b>☁️ Render:</b> ${render}\n"
msg+="<b>🤖 Telegram:</b> ${tele:-offline}\n"
msg+="<b>💰 Active Trades:</b> <code>${trades}</code>\n\n"
msg+="<b>📈 Market Regime:</b> ${regime}\n"
msg+="<b>🕒 Next Report In:</b> <code>${interval_hr}h</code>\n\n"
msg+="<b>📈 PnL Summary:</b>\n<pre>$(echo "$pnl" | escape_html)</pre>\n"
msg+="──────────────────────────────\n"
msg+="<b>🪙 Market Snapshot (BTC/ETH/SOL):</b>\n<pre>${market_data}</pre>\n"
msg+="──────────────────────────────\n"
msg+="<b>🏆 Top 3 Trades Today:</b>\n<pre>${top_trades}</pre>\n"
msg+="──────────────────────────────\n"
msg+="<b>🧭 AI Suggestion:</b>\n<pre>${ai_suggestion}</pre>\n"
msg+="──────────────────────────────\n"
msg+="✅ <b>Status:</b> System Online & Functional\n"
msg+="🔄 <b>Dynamic Interval:</b> ${interval_hr}h (auto-adjusted)"

send_telegram "$msg"
echo "📤 Auto report executed successfully."

# === Schedule Next Run Dynamically ===
echo "🕒 Sleeping ${interval_hr}h before next report..."
sleep "$((interval_hr * 3600))"
exec "$0"   # relaunch
