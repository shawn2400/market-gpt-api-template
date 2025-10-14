#!/usr/bin/env bash
set -euo pipefail

SAFE_BUDGET=${SAFE_BUDGET:-2200}   # מרווח בטחון מתחת ל-2400
MAX_BACKOFF=${MAX_BACKOFF:-30}

guarded_curl() {
  # שימוש: guarded_curl GET "https://fapi.binance.com/fapi/v1/account" "-H 'X-MBX-APIKEY: ...'"
  local method="$1"; shift
  local url="$1"; shift
  local extra=("$@")
  local tmp=$(mktemp)
  local back=1

  while :; do
    # -D -: הדפסה של ההדרים ל-stdout; נפריד גוף/הדרים
    out="$(curl -sS -w '\n%{http_code}' -X "$method" -D - "$url" "${extra[@]}" || true)"
    body="$(echo "$out" | sed '$d')"
    code="$(echo "$out" | tail -n1)"

    used=$(echo "$body" | grep -i '^x-mbx-used-weight-1m:' | awk -F': *' '{print $2}' || echo "")
    [[ -z "$used" ]] && used=$(echo "$body" | tr -d '\r' | grep -i '^X-MBX-USED-WEIGHT-1M:' | awk -F': *' '{print $2}' || echo 0)

    # אם עברנו את התקציב הבטוח — backoff פרופורציונלי
    if [[ "$used" =~ ^[0-9]+$ ]] && (( used >= SAFE_BUDGET )); then
      # כמה נשאר עד 2400? הפוך את זה לזמן שינה, עם מינימום 1–2 שנ'
      sleep_for=$(( 1 + (used - SAFE_BUDGET)/50 ))
      (( sleep_for > MAX_BACKOFF )) && sleep_for=$MAX_BACKOFF
      echo "binance_guard: used=$used → sleep ${sleep_for}s" >&2
      sleep "$sleep_for"
      continue
    fi

    # 429/418/-1003 → backoff אקספוננציאלי + ג'יטר
    if [[ "$code" == "429" || "$code" == "418" ]] || echo "$body" | grep -qE 'code":-1003|Too many requests'; then
      jitter=$(( (RANDOM % 300) + 100 ))
      sleep_sec=$(( back + jitter/1000 ))
      echo "binance_guard: HTTP $code / -1003 → backoff ${sleep_sec}s" >&2
      python3 - <<PY
import time
time.sleep(${sleep_sec})
PY
      (( back < MAX_BACKOFF )) && back=$(( back*2 ))
      continue
    fi

    # הצלחה
    echo "$body"
    return 0
  done
}
