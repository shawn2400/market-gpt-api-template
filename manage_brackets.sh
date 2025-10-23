#!/usr/bin/env bash
set -euo pipefail

# ====== הגדרות ======
API_KEY="${API_KEY:-}"            # חובה: מפתח Binance Futures
API_SECRET="${API_SECRET:-}"      # חובה: סוד Binance Futures
SYMBOL="${SYMBOL:-ETHUSDT}"       # לדוגמה ETHUSDT
SIDE="${SIDE:-BUY}"               # BUY אם הפוזיציה שלך SELL (סגירה בקנייה)
RECV="${RECV:-5000}"

# TP/SL: אפשר לבחור בין מחירים מוחלטים או אחוזים מהכניסה
# אפשרות א: מחירים מוחלטים (מקור מההתראות שלך)
TP1_PRICE="${TP1_PRICE:-3854.18}"
TP2_PRICE="${TP2_PRICE:-3856.11}"
TP3_PRICE="${TP3_PRICE:-3830.00}"
TP4_PRICE="${TP4_PRICE:-}"        # ריק = לא לשים TP4
SL_PRICE="${SL_PRICE:-3859.19}"

# חלוקת כמויות ל-TPים (סה״כ חייב להיות <= 1.0). לדוגמה: 20%/25%/25%/30%
SPLIT1="${SPLIT1:-0.20}"
SPLIT2="${SPLIT2:-0.25}"
SPLIT3="${SPLIT3:-0.25}"
SPLIT4="${SPLIT4:-0.30}"

# טלגרם (לא חובה, רק אם רוצים דיווחים)
TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"  # eg: 123456:ABC...
TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID:-}"      # eg: 449087907
REPORT_EVERY_SEC="${REPORT_EVERY_SEC:-1800}"  # 30 דקות

BASE="https://fapi.binance.com"

# ====== פונקציות עזר ======
ms() { echo $(( $(date +%s)*1000 )); }

sign() { # usage: sign "querystring"
  printf '%s' "$1" | openssl dgst -sha256 -hmac "$API_SECRET" -hex -r | awk '{print $1}'
}

post() { # POST חתום
  local path="$1"; shift
  local q="$1"; shift || true
  local s; s=$(sign "$q")
  curl -fsS -X POST "$BASE$path" -H "X-MBX-APIKEY: $API_KEY" --data "$q&signature=$s"
}

del() { # DELETE חתום
  local path="$1"; shift
  local q="$1"; shift || true
  local s; s=$(sign "$q")
  curl -fsS -X DELETE "$BASE$path?$q&signature=$s" -H "X-MBX-APIKEY: $API_KEY"
}

get_signed() {
  local path="$1"; shift
  local q="$1"; shift || true
  local s; s=$(sign "$q")
  curl -fsS "$BASE$path?$q&signature=$s" -H "X-MBX-APIKEY: $API_KEY"
}

get_public() {
  local path="$1"; shift
  local q="${1:-}"
  if [ -n "$q" ]; then curl -fsS "$BASE$path?$q"; else curl -fsS "$BASE$path"; fi
}

place() { # עוטף הזמנת פקודה
  local q="$1"
  post "/fapi/v1/order" "$q"
}

telegram() {
  [ -z "$TELEGRAM_BOT_TOKEN" ] && return 0
  [ -z "$TELEGRAM_CHAT_ID" ] && return 0
  local text="$1"
  curl -fsS -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/sendMessage" \
    --data-urlencode "chat_id=$TELEGRAM_CHAT_ID" \
    --data-urlencode "parse_mode=HTML" \
    --data-urlencode "text=$text" >/dev/null
}

# ====== לוגיקה ======

# מביא גודל פוזיציה, מחיר כניסה וסימון רווח/הפסד — בלי jq
read_position() {
  local T=$(ms)
  local Q="recvWindow=$RECV&timestamp=$T"
  # /fapi/v2/positionRisk מחזיר מערך; נסנן לפי SYMBOL
  local R; R=$(get_signed "/fapi/v2/positionRisk" "$Q" | tr -d '\n')

  # קח את הבלוק של הסימבול
  local BLK; BLK=$(echo "$R" | sed 's/},{/}\n{/g' | grep -F "\"symbol\":\"$SYMBOL\"" || true)
  POS_AMT=$(echo "$BLK" | sed -n 's/.*"positionAmt":"\([^"]*\)".*/\1/p')
  ENTRY_PRICE=$(echo "$BLK" | sed -n 's/.*"entryPrice":"\([^"]*\)".*/\1/p')
  UN_PNL=$(echo "$BLK" | sed -n 's/.*"unRealizedProfit":"\([^"]*\)".*/\1/p')
  MARK_PRICE=$(echo "$BLK" | sed -n 's/.*"markPrice":"\([^"]*\)".*/\1/p')
  MARGIN_TYPE=$(echo "$BLK" | sed -n 's/.*"marginType":"\([^"]*\)".*/\1/p')

  # נורמליזציה
  POS_AMT="${POS_AMT:-0}"
  ENTRY_PRICE="${ENTRY_PRICE:-0}"
  UN_PNL="${UN_PNL:-0}"
  MARK_PRICE="${MARK_PRICE:-0}"
  MARGIN_TYPE="${MARGIN_TYPE:-unknown}"
}

cancel_all_orders() {
  local T=$(ms)
  local Q="symbol=$SYMBOL&recvWindow=$RECV&timestamp=$T"
  # ביטול גורף
  post "/fapi/v1/allOpenOrders" "$Q" >/dev/null || true
}

place_tp() { # price qty
  local P="$1"; local QTY="$2"
  local T=$(ms)
  place "symbol=$SYMBOL&side=$SIDE&type=TAKE_PROFIT_MARKET&reduceOnly=true&workingType=MARK_PRICE&stopPrice=$P&quantity=$QTY&recvWindow=$RECV&timestamp=$T"
}

place_sl_closepos() { # price
  local P="$1"
  local T=$(ms)
  place "symbol=$SYMBOL&side=$SIDE&type=STOP_MARKET&closePosition=true&workingType=MARK_PRICE&stopPrice=$P&recvWindow=$RECV&timestamp=$T"
}

fmt3() { awk 'BEGIN{printf "%.3f",'$1'}'; }

setup_brackets() {
  read_position
  local ABSQ; ABSQ=$(awk -v a="$POS_AMT" 'BEGIN{if (a<0) a=-a; printf "%.3f", a}')
  if [ "$(awk -v a="$ABSQ" 'BEGIN{print (a>0?1:0)}')" -eq 0 ]; then
    telegram "ℹ️ אין פוזיציה פתוחה ב־<b>$SYMBOL</b>; דילוג על הצבת ברקטים."
    return 0
  fi

  # ניקוי הזמנות ישנות
  cancel_all_orders

  # חלוקת כמויות
  local Q1 Q2 Q3 Q4
  Q1=$(awk -v q="$ABSQ" -v p="$SPLIT1" 'BEGIN{printf "%.3f", q*p}')
  Q2=$(awk -v q="$ABSQ" -v p="$SPLIT2" 'BEGIN{printf "%.3f", q*p}')
  Q3=$(awk -v q="$ABSQ" -v p="$SPLIT3" 'BEGIN{printf "%.3f", q*p}')
  Q4=$(awk -v q="$ABSQ" -v p="$SPLIT4" 'BEGIN{printf "%.3f", q*p}')

  # הצבת TPים קיימים מהפרמטרים
  [ -n "$TP1_PRICE" ] && place_tp "$TP1_PRICE" "$Q1" || true
  [ -n "$TP2_PRICE" ] && place_tp "$TP2_PRICE" "$Q2" || true
  [ -n "$TP3_PRICE" ] && place_tp "$TP3_PRICE" "$Q3" || true
  if [ -n "$TP4_PRICE" ] && [ "$(awk -v q="$Q4" 'BEGIN{print (q>0?1:0)}')" -eq 1 ]; then
    place_tp "$TP4_PRICE" "$Q4"
  fi

  # SL על כל היתרה שנשארת
  [ -n "$SL_PRICE" ] && place_sl_closepos "$SL_PRICE"

  telegram "✅ הוצבו ברקטים ל־<b>$SYMBOL</b>\nTPs: $TP1_PRICE / $TP2_PRICE / $TP3_PRICE ${TP4_PRICE:+/ $TP4_PRICE}\nSL: $SL_PRICE\nכמות: $ABSQ (חלוקה: $SPLIT1,$SPLIT2,$SPLIT3,${SPLIT4})"
}

report_once() {
  read_position
  # מחיר עדכני (אפשר גם מהפרמיום־אינדקס)
  local PRICE_JSON; PRICE_JSON=$(get_public "/fapi/v1/ticker/price" "symbol=$SYMBOL")
  local LAST; LAST=$(echo "$PRICE_JSON" | sed -n 's/.*"price":"\([^"]*\)".*/\1/p')

  local TXT="📊 <b>$SYMBOL</b> דיווח תקופתי
• Amount: <code>$POS_AMT</code>
• Entry: <code>$ENTRY_PRICE</code>
• Mark: <code>$MARK_PRICE</code> | Last: <code>$LAST</code>
• uPNL: <code>$UN_PNL</code>
• Margin: <code>$MARGIN_TYPE</code>"

  telegram "$TXT"
}

summary_and_exit_if_closed() {
  read_position
  local ABSQ; ABSQ=$(awk -v a="$POS_AMT" 'BEGIN{if (a<0) a=-a; print a}')
  if awk -v q="$ABSQ" 'BEGIN{exit !(q<0.0001)}'; then
    # אין פוזיציה: בטל הוראות, דווח סיכום וצא
    cancel_all_orders || true
    telegram "🏁 <b>$SYMBOL</b> נסגרה. סיכום:
• Entry: <code>$ENTRY_PRICE</code>
• Mark: <code>$MARK_PRICE</code>
• uPNL (סגירה): <code>$UN_PNL</code>"
    exit 0
  fi
}

main() {
  # בדיקת מפתחות
  if [ -z "$API_KEY" ] || [ -z "$API_SECRET" ]; then
    echo "ERROR: חסרים API_KEY / API_SECRET בסביבה." >&2
    exit 1
  fi

  setup_brackets
  report_once

  # לולאת דיווח כל 30 דק׳ + בדיקת סגירה
  while true; do
    sleep "$REPORT_EVERY_SEC"
    summary_and_exit_if_closed
    report_once
  done
}

main "$@"
