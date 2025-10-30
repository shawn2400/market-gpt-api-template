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
      -d "parse_mode=HTML" >/dev/null && echo "📢 Telegram alert sent"
  else
    echo "⚠️ Telegram not configured"
  fi
}

# === Get Market Indicators ===
rsi=$(curl -fsS "$BASE/scan/public-now?symbols=BTCUSDT&indicators=1" 2>/dev/null | grep -o '"rsi":[0-9.]*' | cut -d: -f2 | head -1)
adx=$(curl -fsS "$BASE/scan/public-now?symbols=BTCUSDT&indicators=1" 2>/dev/null | grep -o '"adx":[0-9.]*' | cut -d: -f2 | head -1)
macd=$(curl -fsS "$BASE/scan/public-now?symbols=BTCUSDT&indicators=1" 2>/dev/null | grep -o '"macd":[0-9.-]*' | cut -d: -f2 | head -1)

regime="Unknown"
if (( $(echo "$adx > 25" | bc -l) )); then
  regime=$([[ $(echo "$macd > 0" | bc -l) -eq 1 ]] && echo "TREND_UP" || echo "TREND_DOWN")
elif (( $(echo "$adx < 15" | bc -l) )); then
  regime="CHOP"
elif (( $(echo "$rsi > 70" | bc -l) )); then
  regime="REVERSAL_SHORT"
elif (( $(echo "$rsi < 30" | bc -l) )); then
  regime="REVERSAL_LONG"
else
  regime="NEUTRAL"
fi

# === Detect Regime Change ===
last_state=$(cat "$STATE_FILE" 2>/dev/null || echo "UNKNOWN")
if [[ "$regime" != "$last_state" ]]; then
  echo "$regime" > "$STATE_FILE"
  now=$(date '+%Y-%m-%d %H:%M:%S %Z')

  case "$regime" in
    TREND_UP)
      mode="AUTO"
      msg="🔥 <b>Market Alert:</b> BTC entered <b>UP TREND</b>!\n💹 Auto-Executor <b>ENABLED</b>\n🕐 ${now}"
      ;;
    TREND_DOWN)
      mode="AUTO"
      msg="📉 <b>Market Alert:</b> BTC in <b>DOWN TREND</b>!\n💹 Auto-Executor <b>ENABLED</b>\n🕐 ${now}"
      ;;
    CHOP)
      mode="PAUSE"
      msg="⚠️ <b>Market Alert:</b> CHOP detected (sideways market)\n🤖 Auto-Executor <b>DISABLED</b>\n🕐 ${now}"
      ;;
    REVERSAL_SHORT)
      mode="AUTO"
      msg="🔄 <b>Reversal Alert:</b> Overbought zone (RSI>70)\n🧠 Prefer SHORT setups\n🕐 ${now}"
      ;;
    REVERSAL_LONG)
      mode="AUTO"
      msg="🔄 <b>Reversal Alert:</b> Oversold zone (RSI<30)\n🧠 Prefer LONG setups\n🕐 ${now}"
      ;;
    *)
      mode="IDLE"
      msg="ℹ️ <b>Market Neutral</b> — monitoring only\n🕐 ${now}"
      ;;
  esac

  send_telegram "$msg"

  # === Toggle auto-trading accordingly ===
  if [[ "$mode" == "AUTO" ]]; then
    curl -fsS -X POST -H "Authorization: Bearer $BEARER" "$BASE/trade/auto-on" >/dev/null \
      && echo "✅ Auto-Executor enabled"
  elif [[ "$mode" == "PAUSE" ]]; then
    curl -fsS -X POST -H "Authorization: Bearer $BEARER" "$BASE/trade/auto-off" >/dev/null \
      && echo "🛑 Auto-Executor paused"
  fi
else
  echo "ℹ️ No regime change — still ${regime}"
fi
