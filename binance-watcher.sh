cat > binance-watcher.sh <<'BASH'
#!/usr/bin/env bash
set -euo pipefail

API_URL="${API_URL:-https://fapi.binance.com/fapi/v1/exchangeInfo}"  # USDT-M Futures
SCRIPT_DIR="$(cd -- "$(dirname "$0")" && pwd)"
PARSER="${PARSER:-$SCRIPT_DIR/parse_exchange_info.awk}"

mode="${1:-once}"   # once | notify

# הורדה ופרסור
json="$(curl -sSL "$API_URL")"
out="$(printf '%s' "$json" | awk -f "$PARSER")"

case "$mode" in
  once)
    printf '%s\n' "$out"
    ;;
  notify)
    : "${TG_TOKEN:?missing TG_TOKEN}"
    : "${TG_CHAT_ID:?missing TG_CHAT_ID}"
    while IFS= read -r line; do
      curl -sS "https://api.telegram.org/bot${TG_TOKEN}/sendMessage" \
        --data-urlencode "chat_id=${TG_CHAT_ID}" \
        --data-urlencode "text=${line}" >/dev/null
    done <<< "$out"
    ;;
  *)
    echo "usage: $0 [once|notify]" >&2
    exit 1
    ;;
esac
BASH

chmod +x binance-watcher.sh

