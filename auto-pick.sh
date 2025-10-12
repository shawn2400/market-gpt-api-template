#!/usr/bin/env bash
set -euo pipefail

# ===================== CONFIG =====================
# Hosts/tokens (מילוי מהסביבה שלך):
HOST="${HOST:-https://algogpt-docker.onrender.com}"
TOKEN="${TOKEN:-}"                 # API bearer (לקריאות פרטיות)
SECRET_HEX="${SECRET_HEX:-}"       # API_SIGNING_SECRET (hex) ל-/manage-once
OPS_SECRET_HEX="${OPS_SECRET_HEX:-}" # OPS_SIGN_SECRET (hex) ל-/ops/ui/ticket/signed

# Binance (ל-Fallback ישיר בלבד; לא חובה אם עובדים רק באישור טלגרם):
BINANCE_API_KEY="${BINANCE_API_KEY:-}"
BINANCE_API_SECRET="${BINANCE_API_SECRET:-}"

# Universe לסריקה (הוסף/שנה חופשי):
UNIVERSE="${UNIVERSE:-BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,NEARUSDT}"

# בחירת מוד פעולה: "approve" = יצירת טיקט לאישור בטלגרם (מומלץ),
#                    "direct"  = פתיחה ישירה בבינאנס (Fallback)
MODE="${MODE:-approve}"

# תקציב ומינוף דינמיים:
BUDGET_MIN="${BUDGET_MIN:-100}"
BUDGET_MAX="${BUDGET_MAX:-200}"
LEV_MIN="${LEV_MIN:-15}"
LEV_MAX="${LEV_MAX:-35}"

# ספי איכות:
SCORE_MIN="${SCORE_MIN:-6.0}"      # מינימום ציון כדי להחשב מועמד
ADX_MIN="${ADX_MIN:-20}"           # מינ' ADX לשקלול
INTERVAL="${INTERVAL:-15m}"

# ===================== HELPERS =====================
ts_ms() { date +%s%3N; }
ts_s()  { date +%s; }

sig_hmac() { # $1=secret_hex $2=blob
  printf "%s" "$2" | openssl dgst -sha256 -mac HMAC -macopt hexkey:"$1" | awk '{print $2}'
}

mbx_sig() { # Binance HMAC (ascii secret)
  printf "%s" "$1" | openssl dgst -sha256 -hmac "$BINANCE_API_SECRET" -binary | xxd -p -c 256
}

# tiny json number/string extractors בלי jq:
jnum() {  # usage: jnum "json" "key"
  printf "%s" "$1" | tr -d '\n' \
  | sed -n 's/.*"'"$2"'":[[:space:]]*\([-0-9.]\+\).*/\1/p' | head -n1
}
jstr() {  # usage: jstr "json" "key"
  printf "%s" "$1" | tr -d '\n' \
  | sed -n 's/.*"'"$2"'":[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1
}

quant_floor() { # floor value to step using python (דיוק טוב)
  python3 - <<PY
from decimal import Decimal, getcontext
getcontext().prec = 28
v=Decimal("$1"); s=Decimal("$2")
q=(v//s)*s
d=len(str(s).split('.')[-1]) if '.' in str(s) else 0
print(f"{q:.{d}f}")
PY
}

# ===================== DATA FETCH =====================
get_mark_price() { # $1=symbol  -> prints mark price
  curl -sS "https://fapi.binance.com/fapi/v1/premiumIndex?symbol=$1" | sed -n 's/.*"markPrice":"\([0-9.]\+\)".*/\1/p'
}

get_filters() { # $1=symbol -> echo "QTY_STEP|TICK_SIZE"
  local EXINFO; EXINFO="$(curl -sS "https://fapi.binance.com/fapi/v1/exchangeInfo?symbol=$1")"
  local STEP TICK
  STEP="$(printf "%s" "$EXINFO" | tr -d '\n' | sed -n 's/.*"symbol":"'"$1"'".*?"stepSize":"\([0-9.]\+\)".*/\1/p' | head -n1)"
  TICK="$(printf "%s" "$EXINFO" | tr -d '\n' | sed -n 's/.*"symbol":"'"$1"'".*?"tickSize":"\([0-9.]\+\)".*/\1/p' | head -n1)"
  echo "${STEP:-0.001}|${TICK:-0.10}"
}

# החזרת (symbol,score,adx,side_guess) עם ה-Score הכי גבוה
pick_top_candidate() {
  # ננסה קודם /topk (ציבורי), אח"כ private scan לכל הסימבולים
  local TOP; TOP="$(curl -sS "$HOST/topk")" || TOP=""
  if [ -n "$TOP" ]; then
    # נשלוף את השורה הראשונה שעוברת סף
    # נזהה מועמד ראשון לפי סדר הופעה (topk אמור להיות ממויין)
    IFS=',' read -ra SYMS <<< "$UNIVERSE"
    local best_sym="" best_score="" best_adx="" best_side=""
    for S in "${SYMS[@]}"; do
      # חיפוש מקומי לערך הספציפי
      local CHUNK; CHUNK="$(printf "%s" "$TOP" | tr -d '\n' | sed -n 's/.*{"symbol":"'"$S"'".\{1,200\}}/\0/p' | head -n1)"
      [ -z "$CHUNK" ] && continue
      local sc adx side
      sc="$(jnum "$CHUNK" "score")"
      adx="$(jnum "$CHUNK" "adx")"
      side="$(jstr "$CHUNK" "side")"
      [ -z "$sc" ] && continue
      awk "BEGIN{exit !($sc >= $SCORE_MIN)}" || continue
      if [ -z "$best_score" ] || awk "BEGIN{exit !($sc > $best_score)}"; then
        best_sym="$S"; best_score="$sc"; best_adx="${adx:-0}"; best_side="${side:-}"
      fi
    done
    if [ -n "$best_sym" ]; then
      echo "$best_sym|$best_score|${best_adx:-0}|${best_side:-}"
      return 0
    fi
  fi

  # fallback: סריקה פרטית/ציבורית לכל סימבול ב-UNIVERSE
  local best_sym="" best_score="" best_adx="" best_side=""
  IFS=',' read -ra SYMS <<< "$UNIVERSE"
  for S in "${SYMS[@]}"; do
    local R; R="$(curl -sS "$HOST/scan/now?symbol=$S&interval=$INTERVAL&rich=1" -H "Authorization: Bearer $TOKEN" || true)"
    [ -z "$R" ] && R="$(curl -sS "$HOST/scan/public-now?symbol=$S&interval=$INTERVAL&rich=1" || true)"
    [ -z "$R" ] && continue
    local sc adx side
    sc="$(jnum "$R" "score")"
    adx="$(jnum "$R" "adx")"
    side="$(jstr "$R" "side")"
    [ -z "$sc" ] && continue
    awk "BEGIN{exit !($sc >= $SCORE_MIN)}" || continue
    if [ -z "$best_score" ] || awk "BEGIN{exit !($sc > $best_score)}"; then
      best_sym="$S"; best_score="$sc"; best_adx="${adx:-0}"; best_side="${side:-}"
    fi
  done
  [ -n "$best_sym" ] && echo "$best_sym|$best_score|${best_adx:-0}|${best_side:-}" || echo ""
}

# קביעה דינמית של צד (BUY/SELL)
decide_side() { # args: score adx side_guess
  local sc="$1" adx="$2" guess="${3:-}"
  if [ -n "$guess" ]; then
    case "$guess" in
      long|LONG|buy|BUY)  echo "BUY";  return;;
      short|SHORT|sell|SELL) echo "SELL"; return;;
    esac
  fi
  # אם אין guess מה-API: כללים פשוטים—ADX נמוך => זהירות (נעדיף כיוון כללי חיובי), ADX גבוה => לפי score>סף: BUY, אחרת SELL
  awk "BEGIN{exit !($adx >= 28 && $sc >= 7.3)}" && { echo "BUY";  return; }
  awk "BEGIN{exit !($adx >= 28 && $sc <  7.3)}" && { echo "SELL"; return; }
  echo "BUY"
}

# מיפוי פרופיל דינמי (TP/Splits/ATR/offset) — כמו בקונפיג שלך
profile_map() { # $1=score $2=adx -> echo "PCTS|SPLITS|ATR|OFF"
  local sc="$1" adx="$2"
  local prof="base"
  awk "BEGIN{exit !($sc < 6.0)}" && prof="conservative"
  awk "BEGIN{exit !($sc >= 6.0 && $sc < 7.5)}" && prof="base"
  awk "BEGIN{exit !($sc >= 7.5 && $sc < 8.5)}" && prof="aggressive"
  awk "BEGIN{exit !($sc >= 8.5)}" && prof="extreme"
  # ADX bias
  awk "BEGIN{exit !($adx < 22)}" && prof="conservative"
  awk "BEGIN{exit !($adx >= 28 && $sc >= 7.3)}" && {
    case "$prof" in
      conservative) prof="base" ;;
      base)         prof="aggressive" ;;
      aggressive)   prof="extreme" ;;
    esac
  }
  case "$prof" in
    conservative) echo "[-2,-4,-7]|[0.50,0.30,0.20]|1.6|10" ;; # הערה: שליליים ל-SELL נתקן בהמשך
    base)         echo "[3,6,12]|[0.25,0.25,0.50]|2.3|6" ;;
    aggressive)   echo "[4,8,16]|[0.30,0.30,0.40]|2.6|5" ;;
    extreme)      echo "[6,12,24]|[0.20,0.30,0.50]|3.2|4" ;;
  esac
}

# ===================== ACTIONS =====================
manage_once_signed() { # $1=JSON body
  local BODY="$1" TS NONCE SIG
  TS="$(ts_s)"; NONCE="$(openssl rand -hex 8)"
  SIG="$(sig_hmac "$SECRET_HEX" "$TS.$NONCE.$BODY")"
  curl -sS -X POST "$HOST/manage-once" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -H "X-Timestamp: $TS" -H "X-Nonce: $NONCE" -H "X-Signature: $SIG" \
    --data "$BODY"
}

create_approval_ticket() { # נשלח טיקט מאושר בטלגרם לפתיחה אוטומטית
  # נשתמש ב-OPS_SIGN_SECRET (hex) + פרמטרים ברורים ל-UI
  local payload="$1"
  local TS NONCE SIG
  TS="$(ts_s)"; NONCE="$(openssl rand -hex 8)"
  SIG="$(sig_hmac "$OPS_SECRET_HEX" "$TS.$NONCE.$payload")"
  curl -sS -X POST "$HOST/ops/ui/ticket/signed" \
    -H "Content-Type: application/json" \
    -H "X-Timestamp: $TS" -H "X-Nonce: $NONCE" -H "X-Signature: $SIG" \
    --data "$payload"
}

# Fallback פתיחה ישירה בבינאנס (אם MODE=direct)
binance_open_market() { # $1=symbol $2=side BUY/SELL $3=lev $4=qty
  local S="$1" SIDE="$2" LEV="$3" QTY="$4" BASE="https://fapi.binance.com" RECV="45000"
  # margin type
  local q="symbol=$S&marginType=ISOLATED&timestamp=$(ts_ms)&recvWindow=$RECV"
  curl -sS -X POST "$BASE/fapi/v1/marginType" -H "X-MBX-APIKEY: $BINANCE_API_KEY" --data "$q&signature=$(mbx_sig "$q")" >/dev/null || true
  # leverage
  q="symbol=$S&leverage=$LEV&timestamp=$(ts_ms)&recvWindow=$RECV"
  curl -sS -X POST "$BASE/fapi/v1/leverage" -H "X-MBX-APIKEY: $BINANCE_API_KEY" --data "$q&signature=$(mbx_sig "$q")" >/dev/null
  # order
  q="symbol=$S&side=$SIDE&type=MARKET&quantity=$QTY&timestamp=$(ts_ms)&recvWindow=$RECV"
  curl -sS -X POST "$BASE/fapi/v1/order" -H "X-MBX-APIKEY: $BINANCE_API_KEY" --data "$q&signature=$(mbx_sig "$q")"
}

# ===================== MAIN =====================
main() {
  local pick; pick="$(pick_top_candidate)"
  if [ -z "$pick" ]; then
    echo "[auto-pick] לא נמצא מועמד מתאים"; exit 0
  fi
  IFS='|' read -r SYMBOL SCORE ADX SIDE_GUESS <<<"$pick"
  echo "[auto-pick] pick: SYMBOL=$SYMBOL score=$SCORE adx=$ADX guess=$SIDE_GUESS"

  # צד (BUY/SELL)
  SIDE="$(decide_side "$SCORE" "$ADX" "$SIDE_GUESS")"
  echo "[auto-pick] side=$SIDE"

  # פרופיל דינמי -> pcts/splits/atr/offset
  IFS='|' read -r PCTS SPLITS ATR OFF <<<"$(profile_map "$SCORE" "$ADX")"
  # אם SELL, נהפוך אחוזי TP לסימן מתאים (אורך/שורט): המערכת שלך תומכת "offset_bps" כללי ו-TPS חיוביים.
  # לכן נשאיר PCTS חיוביים ונניח שה־SIDE ייקח אותנו לכיוון נכון (TP באחוזי רווח יחסיים).
  # אם בכל זאת התקנת לוגיקה שלילית, תוכל להחליף כאן.

  # בחירת מינוף/תקציב דינמיים:
  # מיפוי לינארי לפי score בתוך [LEV_MIN,LEV_MAX], [BUDGET_MIN,BUDGET_MAX]
  # clamp:
  calc_linear() { # val in [a,b] -> map to [c,d]
    python3 - <<PY
v=$1; a=6.0; b=8.8
c=$2; d=$3
v=max(a, min(b, v))
t=(v-a)/(b-a) if b>a else 0.5
print(int(round(c + t*(d-c))))
PY
  }
  LEV="$(calc_linear "$SCORE" "$LEV_MIN" "$LEV_MAX")"
  BUDGET="$(calc_linear "$SCORE" "$BUDGET_MIN" "$BUDGET_MAX")"
  echo "[auto-pick] lev=$LEV budget=$BUDGET"

  # חישוב כמות לפי מחיר שוק + וידוא stepSize:
  MP="$(get_mark_price "$SYMBOL")"
  [ -z "$MP" ] && { echo "[auto-pick] אין Mark Price"; exit 1; }
  IFS='|' read -r QSTEP TICK <<<"$(get_filters "$SYMBOL")"
  RAW_QTY="$(python3 - <<PY
from decimal import Decimal as D
print((D("$BUDGET")/D("$MP")))
PY
)"
  QTY="$(quant_floor "$RAW_QTY" "$QSTEP")"
  echo "[auto-pick] mark=$MP qty=$QTY (step=$QSTEP)"

  # ====== APPROVE MODE (טלגרם) ======
  if [ "$MODE" = "approve" ]; then
    # יוצרים טיקט חתום; במערכת שלך AUTO_OPEN_ON_APPROVE=1 + SMART_MANAGE_ON_APPROVE=1
    # נוסיף פרטים שיהיו נוחים להצגה ב-UI/טלגרם
    PAYLOAD="$(cat <<JSON
{
  "type": "trade_request",
  "symbol": "$SYMBOL",
  "side": "$SIDE",
  "interval": "$INTERVAL",
  "leverage": $LEV,
  "budget_usdt": $BUDGET,
  "reason": "auto-pick live",
  "params": {
    "offset_bps": $OFF,
    "pcts": $PCTS,
    "splits": $SPLITS,
    "atr_mult": $ATR
  }
}
JSON
)"
    echo "[auto-pick] creating approval ticket…"
    R="$(create_approval_ticket "$PAYLOAD")" || true
    echo "$R"
    exit 0
  fi

  # ====== DIRECT MODE (Fallback) ======
  if [ "$MODE" = "direct" ]; then
    echo "[auto-pick] opening directly on Binance (fallback)…"
    # מינוף+Margin:
    binance_open_market "$SYMBOL" "$SIDE" "$LEV" "$QTY" | sed 's/.*/[binance] &/'
    # ניהול אוטומטי דרך manage-once חתום:
    BODY="{\"symbol\":\"$SYMBOL\",\"pcts\":$PCTS,\"splits\":$SPLITS,\"atr_mult\":$ATR,\"offset_bps\":$OFF}"
    echo "[auto-pick] manage-once $BODY"
    manage_once_signed "$BODY" | sed 's/.*/[manage-once] &/'
  fi
}

main "$@"
