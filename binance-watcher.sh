#!/usr/bin/env bash
set -euo pipefail

# ========= קונפיג =========
: "${TG_TOKEN:?export TG_TOKEN=...}"        # טוקן של הבוט
: "${TG_CHAT_ID:?export TG_CHAT_ID=...}"    # chat id (מספרי או @channelusername)
BINANCE_API="${BINANCE_API:-https://fapi.binance.com/fapi/v1}"
INTERVAL_SEC="${INTERVAL_SEC:-60}"          # מרווח בדיקה (שניות)
WORKDIR="${WORKDIR:-./binance-state}"       # תיקיית מצב/לוגים
DAEMON="${DAEMON:-1}"                       # 1=לולאה אין־סופית, 0=ריצה חד־פעמית
CONNECT_TIMEOUT="${CONNECT_TIMEOUT:-5}"
MAX_TIME="${MAX_TIME:-12}"
RETRIES="${RETRIES:-3}"

mkdir -p "$WORKDIR"/{state,logs,tmp}

STATE_TSV="$WORKDIR/state/current.tsv"
PREV_TSV="$WORKDIR/state/prev.tsv"
TMP_RESP="$WORKDIR/tmp/exchangeInfo.json"
TODAY_LOG="$WORKDIR/logs/$(date +%F).log"

# ========= טלגרם =========
tg_send() {
  local text="$1"
  curl -sS -m 15 -X POST "https://api.telegram.org/bot${TG_TOKEN}/sendMessage" \
    -d "chat_id=${TG_CHAT_ID}" \
    --data-urlencode "text=${text}" \
    -d "disable_web_page_preview=true" \
    -d "parse_mode=MarkdownV2" >/dev/null || true
}

# escape בסיסי ל־MarkdownV2
md_escape() {
  sed -e 's/[_*[\]()~`>#+\-=|{}.!]/\\&/g'
}

# ========= משיכה מה־API עם retry =========
fetch_exchange_info() {
  local i
  for i in $(seq 1 "$RETRIES"); do
    if curl -sS --fail \
      --connect-timeout "$CONNECT_TIMEOUT" \
      --max-time "$MAX_TIME" \
      "$BINANCE_API/exchangeInfo" >"$TMP_RESP"; then
      # בדיקת sanity מינימלית
      if grep -q '"symbols"' "$TMP_RESP"; then
        return 0
      fi
    fi
    sleep 2
  done
  echo "ERROR: failed to fetch exchangeInfo after $RETRIES attempts" >&2
  return 1
}

# ========= פרסור ל־TSV (ללא jq) =========
# משתמש בסקריפט awk נפרד (parse_exchange_info.awk)
build_tsv() {
  awk -f "$(dirname "$0")/parse_exchange_info.awk" "$TMP_RESP" > "$STATE_TSV".new
  mv -f "$STATE_TSV".new "$STATE_TSV"
}

# ========= השוואה + דיווח =========
diff_and_notify() {
  # אם אין prev, ניצור אחד ראשוני בלי לשלוח ספאם
  if [ ! -s "$PREV_TSV" ]; then
    cp -f "$STATE_TSV" "$PREV_TSV"
    echo "$(date -Is) INIT state with $(wc -l <"$STATE_TSV") symbols" >> "$TODAY_LOG"
    return 0
  fi

  # מצא סמלים שהתווספו/נמחקו
  cut -f1 "$PREV_TSV" | sort > "$WORKDIR/tmp/prev.syms"
  cut -f1 "$STATE_TSV" | sort > "$WORKDIR/tmp/cur.syms"
  comm -13 "$WORKDIR/tmp/prev.syms" "$WORKDIR/tmp/cur.syms" > "$WORKDIR/tmp/added.syms" || true
  comm -23 "$WORKDIR/tmp/prev.syms" "$WORKDIR/tmp/cur.syms" > "$WORKDIR/tmp/removed.syms" || true

  local msgs=()

  # הודעות על הוספות
  if [ -s "$WORKDIR/tmp/added.syms" ]; then
    while read -r s; do
      local row
      row=$(grep -F -m1 -P "^${s}\t" "$STATE_TSV" || true)
      if [ -n "$row" ]; then
        IFS=$'\t' read -r sym status tick minp step minq <<<"$row"
        msgs+=("*NEW* $(printf %s "$sym" | md_escape) — status=$(printf %s "$status" | md_escape), tickSize=$tick, minPrice=$minp, stepSize=$step, minQty=$minq")
        echo "$(date -Is) NEW $sym $status $tick $minp $step $minq" >> "$TODAY_LOG"
      fi
    done < "$WORKDIR/tmp/added.syms"
  fi

  # הודעות על מחיקות
  if [ -s "$WORKDIR/tmp/removed.syms" ]; then
    while read -r s; do
      msgs+=("*REMOVED* $(printf %s "$s" | md_escape)")
      echo "$(date -Is) REMOVED $s" >> "$TODAY_LOG"
    done < "$WORKDIR/tmp/removed.syms"
  fi

  # בדיקת שינויים בפרמטרים/סטטוס
  join -t $'\t' -o 1.1,1.2,1.3,1.4,1.5,1.6,2.2,2.3,2.4,2.5,2.6 \
    <(sort -t$'\t' -k1,1 "$PREV_TSV") \
    <(sort -t$'\t' -k1,1 "$STATE_TSV") \
    > "$WORKDIR/tmp/join.tsv" || true

  while IFS=$'\t' read -r sym p_status p_tick p_minp p_step p_minq c_status c_tick c_minp c_step c_minq; do
    local changed=()
    [ "$p_status" != "$c_status" ] && changed+=("status: $p_status → $c_status")
    [ "$p_tick"   != "$c_tick"   ] && changed+=("tickSize: $p_tick → $c_tick")
    [ "$p_minp"   != "$c_minp"   ] && changed+=("minPrice: $p_minp → $c_minp")
    [ "$p_step"   != "$c_step"   ] && changed+=("stepSize: $p_step → $c_step")
    [ "$p_minq"   != "$c_minq"   ] && changed+=("minQty: $p_minq → $c_minq")
    if [ "${#changed[@]}" -gt 0 ]; then
      local line="*UPDATE* $(printf %s "$sym" | md_escape) — $(printf %s "$(IFS='; '; echo "${changed[*]}")" | md_escape)"
      msgs+=("$line")
      echo "$(date -Is) UPDATE $sym | ${changed[*]}" >> "$TODAY_LOG"
    fi
  done < "$WORKDIR/tmp/join.tsv"

  # שליחה מרוכזת (אם יש)
  if [ "${#msgs[@]}" -gt 0 ]; then
    # פיצול למקטעים קצרים אם ארוך מדי
    local chunk=""
    for m in "${msgs[@]}"; do
      local try="$chunk"$'\n'"$m"
      if [ "${#try}" -gt 3800 ]; then
        tg_send "$chunk"
        chunk="$m"
      else
        chunk="$try"
      fi
    done
    [ -n "$chunk" ] && tg_send "$chunk"
  fi

  # הפיכת current ל־prev
  cp -f "$STATE_TSV" "$PREV_TSV"
}

# ========= סיכום יומי =========
send_daily_summary() {
  local day="${1:-$(date +%F)}"
  local log="$WORKDIR/logs/$day.log"
  if [ ! -s "$log" ]; then
    tg_send "$(printf 'No changes recorded for %s' "$day" | md_escape)"
    return 0
  fi

  # סיכומי NEW/REMOVED/UPDATE
  local news removed updates
  news=$(grep -c '^.* NEW ' "$log" || true)
  removed=$(grep -c '^.* REMOVED ' "$log" || true)
  updates=$(grep -c '^.* UPDATE ' "$log" || true)

  local header
  header="*Daily summary* $(printf %s "$day" | md_escape)
NEW: $news, REMOVED: $removed, UPDATES: $updates"

  # נאסוף כמה שורות דוגמה מכל סוג (עד 20 מכל אחד)
  {
    echo "$header"
    echo
    echo "*NEW examples*"
    grep ' NEW ' "$log" | tail -n 20 | sed 's/^[^ ]* //' | md_escape
    echo
    echo "*REMOVED examples*"
    grep ' REMOVED ' "$log" | tail -n 20 | sed 's/^[^ ]* //' | md_escape
    echo
    echo "*UPDATE examples*"
    grep ' UPDATE ' "$log" | tail -n 20 | sed 's/^[^ ]* //' | md_escape
  } > "$WORKDIR/tmp/summary.txt"

  tg_send "$(cat "$WORKDIR/tmp/summary.txt")"
}

# ========= CLI =========
cmd="${1:-run}"
case "$cmd" in
  run)
    while :; do
      if fetch_exchange_info; then
        build_tsv
        diff_and_notify
      fi
      [ "$DAEMON" = "1" ] || exit 0
      sleep "$INTERVAL_SEC"
    done
    ;;
  once)
    fetch_exchange_info
    build_tsv
    diff_and_notify
    ;;
  daily)
    # daily [YYYY-MM-DD]
    send_daily_summary "${2:-}"
    ;;
  *)
    echo "Usage: $0 {run|once|daily [YYYY-MM-DD]}" >&2
    exit 1
    ;;
esac
