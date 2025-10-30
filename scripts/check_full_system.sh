#!/usr/bin/env bash
set -euo pipefail

BASE="https://algogpt-docker.onrender.com"
BEARER="${API_BEARER_TOKEN:?set API_BEARER_TOKEN}"
TG_TOKEN="${TELEGRAM_BOT_TOKEN:?set TELEGRAM_BOT_TOKEN}"
TG_CHAT="${TELEGRAM_CHAT_ID:?set TELEGRAM_CHAT_ID}"
BIN_KEY="${BINANCE_API_KEY:?set BINANCE_API_KEY}"
BIN_SEC="${BINANCE_API_SECRET:?set BINANCE_API_SECRET}"

G="\033[1;32m"; R="\033[1;31m"; Y="\033[1;33m"; N="\033[0m"

say(){ echo -e "$1"; }

send_tg(){
  curl -s -X POST "https://api.telegram.org/bot${TG_TOKEN}/sendMessage" \
       -d "chat_id=${TG_CHAT}" -d "text=${1}" -d "parse_mode=HTML" >/dev/null || true
}

timestamp(){ date +%s%3N; }

binance_check(){
  ts=$(timestamp)
  sig=$(printf "timestamp=%s" "$ts" | openssl dgst -sha256 -hmac "$BIN_SEC" -binary | xxd -p -c 256)
  resp=$(curl -s "https://fapi.binance.com/fapi/v2/account?timestamp=$ts&signature=$sig" -H "X-MBX-APIKEY: $BIN_KEY")
  if echo "$resp" | grep -q '"canTrade":true'; then
    say "${G}✅ Binance API OK (Futures enabled)${N}"
  else
    say "${R}❌ Binance API Error${N} → $resp"
    send_tg "⚠️ <code>Binance API Error</code>\n<pre>$resp</pre>"
  fi
}

render_check(){
  if curl -fsS "$BASE/readyz" >/dev/null; then
    say "${G}☁️ Render ready OK${N}"
  else
    say "${R}☁️ Render Down${N}"
  fi
}

telegram_check(){
  if curl -s -H "Authorization: Bearer $BEARER" "$BASE/telegram/status" | grep -q '"ok":true'; then
    say "${G}🧠 Telegram Bot OK${N}"
  else
    say "${R}⚠️ Telegram Bot not responding${N}"
  fi
}

pnl_check(){
  pnl=$(curl -s -H "Authorization: Bearer $BEARER" "$BASE/pnl/summary" | grep -o '"total_pnl":[^,]*' | cut -d: -f2 || echo "n/a")
  say "${Y}💰 PnL: ${pnl}${N}"
}

version_check(){
  ver=$(curl -s -H "Authorization: Bearer $BEARER" "$BASE/version" | grep -o '"algogpt_version":"[^"]*"' | cut -d'"' -f4 || echo "n/a")
  say "🟢 Version: ${ver}"
}

main(){
  echo "=============================="
  echo "🔍 Full System Check $(date '+%H:%M:%S %d/%m/%Y')"
  echo "=============================="
  render_check
  telegram_check
  binance_check
  pnl_check
  version_check
  echo "=============================="
}

[[ "${1:-}" == "--binance-only" ]] && binance_check || main




