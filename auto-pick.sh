cat > /app/auto-pick.sh <<'SH'
#!/usr/bin/env bash
set -euo pipefail

# ====== ENV ======
HOST="${HOST:-https://algogpt-docker.onrender.com}"
TOKEN="${TOKEN:-}"
SECRET_HEX="${SECRET_HEX:-}"
OPS_SECRET_HEX="${OPS_SECRET_HEX:-}"
BINANCE_API_KEY="${BINANCE_API_KEY:-}"
BINANCE_API_SECRET="${BINANCE_API_SECRET:-}"

UNIVERSE="${UNIVERSE:-BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,NEARUSDT}"
INTERVALS="${INTERVALS:-15m,30m,1h,1d}"
MODE="${MODE:-approve}"

BUDGET_MIN="${BUDGET_MIN:-100}"
BUDGET_MAX="${BUDGET_MAX:-200}"
LEV_MIN="${LEV_MIN:-15}"
LEV_MAX="${LEV_MAX:-35}"

SCORE_MIN="${SCORE_MIN:-6.0}"
ADX_MIN="${ADX_MIN:-20}"

# ====== Utils ======
ts_ms(){ date +%s%3N; }
ts_s(){ date +%s; }
sig_hmac(){ printf "%s" "$2" | openssl dgst -sha256 -mac HMAC -macopt hexkey:"$1" | awk '{print $2}'; }
mbx_sig(){ printf "%s" "$1" | openssl dgst -sha256 -hmac "$BINANCE_API_SECRET" -binary | xxd -p -c 256; }

jnum(){ printf "%s" "$1" | tr -d '\n' | sed -n 's/.*"'"$2"'":[[:space:]]*\([-0-9.]\+\).*/\1/p' | head -n1; }
jstr(){ printf "%s" "$1" | tr -d '\n' | sed -n 's/.*"'"$2"'":[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1; }

quant_floor() {
python3 - <<PY
from decimal import Decimal, getcontext
getcontext().prec = 28
v=Decimal("$1"); s=Decimal("$2")
q=(v//s)*s
d=len(str(s).split('.')[-1]) if '.' in str(s) else 0
print(f"{q:.{d}f}")
PY
}

price_round() {
python3 - <<PY
from decimal import Decimal, getcontext
getcontext().prec = 28
p=Decimal("$1"); t=Decimal("$2")
q=(p//t)*t
d=len(str(t).split('.')[-1]) if '.' in str(t) else 0
print(f"{q:.{d}f}")
PY
}

get_mark_price(){ curl -sS "https://fapi.binance.com/fapi/v1/premiumIndex?symbol=$1" | sed -n 's/.*"markPrice":"\([0-9.]\+\)".*/\1/p'; }
get_filters(){
  local EX="$(curl -sS "https://fapi.binance.com/fapi/v1/exchangeInfo?symbol=$1")"
  local STEP="$(printf "%s" "$EX" | tr -d '\n' | sed -n 's/.*"symbol":"'"$1"'".*?"stepSize":"\([0-9.]\+\)".*/\1/p' | head -n1)"
  local TICK="$(printf "%s" "$EX" | tr -d '\n' | sed -n 's/.*"symbol":"'"$1"'".*?"tickSize":"\([0-9.]\+\)".*/\1/p' | head -n1)"
  echo "${STEP:-0.001}|${TICK:-0.10}"
}

calc_linear(){
python3 - <<PY
v=$1; a=6.0; b=8.8
c=$2; d=$3
v=max(a, min(b, v))
t=(v-a)/(b-a) if b>a else 0.5
print(int(round(c + t*(d-c))))
PY
}

# ====== Composite scorer for timeframe: Score+ADX+ATR% ======
# נורמליזציה: score∈[0,10]→[0,1]; ADX∈[10,40]→[0,1]; ATR%∈[0,5%]→[0,1] (קלמפ)
# משקולות ברירת-מחדל: wS=0.55, wA=0.35, wV=0.10
tf_score(){
python3 - <<PY
import sys, json
score=float(sys.argv[1]); adx=float(sys.argv[2]); atrp=float(sys.argv[3])
def clamp(x,a,b): return max(a,min(b,x))
s = clamp(score/10.0, 0, 1)
a = clamp((adx-10)/30.0, 0, 1)
v = clamp(atrp/5.0, 0, 1)
wS, wA, wV = 0.55, 0.35, 0.10
print( round(wS*s + wA*a + wV*v, 6) )
PY
"$1" "$2" "$3"
}

best_interval_for(){
  local S="$1" best_i="" best_val=""
  IFS=',' read -ra IFR <<< "$INTERVALS"
  for I in "${IFR[@]}"; do
    local R="$(curl -sS "$HOST/scan/public-now?symbol=$S&interval=$I&rich=1" || true)"
    [ -z "$R" ] && R="$(curl -sS "$HOST/scan/now?symbol=$S&interval=$I&rich=1" -H "Authorization: Bearer $TOKEN" || true)"
    [ -z "$R" ] && continue
    local sc="$(jnum "$R" "score")"
    local adx="$(jnum "$R" "adx")"
    local atrp="$(jnum "$R" "atr_pct")"
    [ -z "$sc" ] && continue
    [ -z "$adx" ] && adx="0"
    [ -z "$atrp" ] && atrp="0"
    awk "BEGIN{exit !($sc >= $SCORE_MIN)}" || continue
    local comp="$(tf_score "$sc" "$adx" "$atrp")"
    if [ -z "$best_val" ] || awk "BEGIN{exit !($comp > $best_val)}"; then
      best_val="$comp"; best_i="$I"
    fi
  done
  [ -n "$best_i" ] && echo "$best_i" || echo ""
}

pick_symbol(){
  local best="" bsc=""
  local TOP="$(curl -sS "$HOST/topk" || true)"
  if [ -n "$TOP" ]; then
    IFS=',' read -ra SYMS <<< "$UNIVERSE"
    for S in "${SYMS[@]}"; do
      local C; C="$(printf "%s" "$TOP" | tr -d '\n' | sed -n 's/.*{"symbol":"'"$S"'".\{1,200\}}/\0/p' | head -n1)"
      [ -z "$C" ] && continue
      local sc="$(jnum "$C" "score")"
      [ -z "$sc" ] && continue
      awk "BEGIN{exit !($sc >= $SCORE_MIN)}" || continue
      if [ -z "$bsc" ] || awk "BEGIN{exit !($sc > $bsc)}"; then best="$S"; bsc="$sc"; fi
    done
    [ -n "$best" ] && { echo "$best|$bsc"; return; }
  fi
  IFS=',' read -ra SYMS <<< "$UNIVERSE"
  for S in "${SYMS[@]}"; do
    local R="$(curl -sS "$HOST/scan/public-now?symbol=$S&interval=15m&rich=1" || true)"
    [ -z "$R" ] && R="$(curl -sS "$HOST/scan/now?symbol=$S&interval=15m&rich=1" -H "Authorization: Bearer $TOKEN" || true)"
    [ -z "$R" ] && continue
    local sc="$(jnum "$R" "score")"
    [ -z "$sc" ] && continue
    awk "BEGIN{exit !($sc >= $SCORE_MIN)}" || continue
    if [ -z "$bsc" ] || awk "BEGIN{exit !($sc > $bsc)}"; then best="$S"; bsc="$sc"; fi
  done
  [ -n "$best" ] && echo "$best|$bsc" || echo ""
}

decide_side(){
  local sc="$1" adx="$2" guess="${3:-}"
  [ -n "$guess" ] && { [[ "$guess" =~ ^(long|buy|LONG|BUY)$ ]] && echo BUY && return; [[ "$guess" =~ ^(short|sell|SHORT|SELL)$ ]] && echo SELL && return; }
  awk "BEGIN{exit !($adx >= 28 && $sc >= 7.3)}" && { echo BUY;  return; }
  awk "BEGIN{exit !($adx >= 28 && $sc <  7.3)}" && { echo SELL; return; }
  echo BUY
}

profile_map(){
  local sc="$1" adx="$2" p="base"
  awk "BEGIN{exit !($sc < 6.0)}" && p="conservative"
  awk "BEGIN{exit !($sc >= 6.0 && $sc < 7.5)}" && p="base"
  awk "BEGIN{exit !($sc >= 7.5 && $sc < 8.5)}" && p="aggressive"
  awk "BEGIN{exit !($sc >= 8.5)}" && p="extreme"
  awk "BEGIN{exit !($adx < 22)}" && p="conservative"
  awk "BEGIN{exit !($adx >= 28 && $sc >= 7.3)}" && { case "$p" in conservative)p="base";; base)p="aggressive";; aggressive)p="extreme";; esac; }
  case "$p" in
    conservative) echo "[2,4,7]|[0.50,0.30,0.20]|1.6|10" ;;
    base)         echo "[3,6,12]|[0.25,0.25,0.50]|2.3|6" ;;
    aggressive)   echo "[4,8,16]|[0.30,0.30,0.40]|2.6|5" ;;
    extreme)      echo "[6,12,24]|[0.20,0.30,0.50]|3.2|4" ;;
  esac
}

manage_once_signed(){
  local BODY="$1" TS NONCE SIG
  TS="$(ts_s)"; NONCE="$(openssl rand -hex 8)"
  SIG="$(sig_hmac "$SECRET_HEX" "$TS.$NONCE.$BODY")"
  curl -sS -X POST "$HOST/manage-once" \
    -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    -H "X-Timestamp: $TS" -H "X-Nonce: $NONCE" -H "X-Signature: $SIG" \
    --data "$BODY"
}

create_ticket(){
  local payload="$1" TS NONCE SIG
  TS="$(ts_s)"; NONCE="$(openssl rand -hex 8)"
  SIG="$(sig_hmac "$OPS_SECRET_HEX" "$TS.$NONCE.$payload")"
  curl -sS -X POST "$HOST/ops/ui/ticket/signed" \
    -H "Content-Type: application/json" \
    -H "X-Timestamp: $TS" -H "X-Nonce: $NONCE" -H "X-Signature: $SIG" \
    --data "$payload"
}

binance_open_market(){
  local S="$1" SIDE="$2" LEV="$3" QTY="$4" BASE="https://fapi.binance.com" RECV="45000"
  local q="symbol=$S&marginType=ISOLATED&timestamp=$(ts_ms)&recvWindow=$RECV"
  curl -sS -X POST "$BASE/fapi/v1/marginType" -H "X-MBX-APIKEY: $BINANCE_API_KEY" --data "$q&signature=$(mbx_sig "$q")" >/dev/null || true
  q="symbol=$S&leverage=$LEV&timestamp=$(ts_ms)&recvWindow=$RECV"
  curl -sS -X POST "$BASE/fapi/v1/leverage" -H "X-MBX-APIKEY: $BINANCE_API_KEY" --data "$q&signature=$(mbx_sig "$q")" >/dev/null
  q="symbol=$S&side=$SIDE&type=MARKET&quantity=$QTY&timestamp=$(ts_ms)&recvWindow=$RECV"
  curl -sS -X POST "$BASE/fapi/v1/order" -H "X-MBX-APIKEY: $BINANCE_API_KEY" --data "$q&signature=$(mbx_sig "$q")"
}

main(){
  # manager health
  local H="$(curl -sS "$HOST/ops/manager/health" -H "Authorization: Bearer $TOKEN" || true)"
  local TC="$(jnum "$H" "tick_count")"
  if [ -z "$TC" ] || [ "$TC" -le 0 ]; then
    echo "[auto-pick] manager_not_available"; exit 0
  fi

  # best symbol (score גבוה) מתוך UNIVERSE
  local PS="$(pick_symbol)"; [ -z "$PS" ] && { echo "[auto-pick] no symbol"; exit 0; }
  local SYMBOL="${PS%%|*}"

  # בחר timeframe ע"פ משקלול Score+ADX+ATR%
  local INTERVAL="$(best_interval_for "$SYMBOL")"
  [ -z "$INTERVAL" ] && { echo "[auto-pick] no interval"; exit 0; }

  # משוך נתונים (כולל side/score/adx/atr_pct)
  local R="$(curl -sS "$HOST/scan/public-now?symbol=$SYMBOL&interval=$INTERVAL&rich=1" || true)"
  [ -z "$R" ] && R="$(curl -sS "$HOST/scan/now?symbol=$SYMBOL&interval=$INTERVAL&rich=1" -H "Authorization: Bearer $TOKEN" || true)"
  local SCORE="$(jnum "$R" "score")"
  local ADX="$(jnum "$R" "adx")"; [ -z "$ADX" ] && ADX="0"
  local ATRP="$(jnum "$R" "atr_pct")"; [ -z "$ATRP" ] && ATRP="0"
  local SIDE_GUESS="$(jstr "$R" "side")"

  awk "BEGIN{exit !($SCORE >= $SCORE_MIN)}" || { echo "[auto-pick] score too low"; exit 0; }
  awk "BEGIN{exit !($ADX >= $ADX_MIN)}"     || { echo "[auto-pick] adx too low"; exit 0; }

  local SIDE="$(decide_side "$SCORE" "$ADX" "$SIDE_GUESS")"
  IFS='|' read -r PCTS SPLITS ATR OFF <<<"$(profile_map "$SCORE" "$ADX")"

  local LEV="$(calc_linear "$SCORE" "$LEV_MIN" "$LEV_MAX")"
  local BUDGET="$(calc_linear "$SCORE" "$BUDGET_MIN" "$BUDGET_MAX")"

  # דיוק לכל מטבע: stepSize/tickSize
  local MP="$(get_mark_price "$SYMBOL")"
  IFS='|' read -r QSTEP TICK <<<"$(get_filters "$SYMBOL")"
  local RAW_QTY="$(python3 - <<PY
from decimal import Decimal as D
print((D("$BUDGET")/D("$MP")))
PY
)"
  local QTY="$(quant_floor "$RAW_QTY" "$QSTEP")"
  local MP_ROUNDED="$(price_round "$MP" "$TICK")"

  echo "[auto-pick] sym=$SYMBOL itv=$INTERVAL side=$SIDE score=$SCORE adx=$ADX atr%=$ATRP lev=$LEV budget=$BUDGET mp=$MP_ROUNDED qty=$QTY step=$QSTEP tick=$TICK"

  if [ "$MODE" = "approve" ]; then
    local PAYLOAD="$(cat <<JSON
{
  "type": "trade_request",
  "symbol": "$SYMBOL",
  "side": "$SIDE",
  "interval": "$INTERVAL",
  "leverage": $LEV,
  "budget_usdt": $BUDGET,
  "reason": "auto-pick (score+adx+atr%)",
  "params": { "offset_bps": $OFF, "pcts": $PCTS, "splits": $SPLITS, "atr_mult": $ATR }
}
JSON
)"
    create_ticket "$PAYLOAD"
    exit 0
  else
    # פתיחה מיידית + ניהול (כמות מעוגלת לפי stepSize, מחיר לפי tickSize)
    binance_open_market "$SYMBOL" "$SIDE" "$LEV" "$QTY" | sed 's/.*/[binance] &/'
    local BODY="{\"symbol\":\"$SYMBOL\",\"offset_bps\":$OFF,\"pcts\":$PCTS,\"splits\":$SPLITS,\"atr_mult\":$ATR}"
    manage_once_signed "$BODY" | sed 's/.*/[manage-once] &/'
  fi
}
main "$@"
SH
chmod +x /app/auto-pick.sh



