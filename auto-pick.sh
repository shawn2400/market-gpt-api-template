cat > ./auto-pick.sh <<'SH'
#!/usr/bin/env bash
# auto-pick.sh (PRO) — בוחר timeframe לפי ADX+ATR%, יוצר טיקט HYBRID עם TP/SL לפי פרופיל דינמי.
set -euo pipefail

: "${HOST:?set in algogpt.env}"
: "${TOKEN:?set in algogpt.env}"

# ===== Tunables (אפשר לשנות ב-env לפני הרצה) =====
INTERVALS_CSV="${INTERVALS:-15m,30m,1h,4h,1d}"
ADX_WEIGHT="${ADX_WEIGHT:-0.6}"
ATRW_WEIGHT="${ATRW_WEIGHT:-0.4}"        # משקל ל־ATR% (ATR/Price*100)
ATRW_CAP_PCT="${ATRW_CAP_PCT:-3.0}"      # חיתוך ATR% מקסימלי לנרמול
SCORE_FALLBACK_MIN="${SCORE_FALLBACK_MIN:-6.0}"  # אם אין score מהשרת
APPROVAL_MAX_SL_PCT="${APPROVAL_MAX_SL_PCT:-3.0}" # תקרת SL% לבטיחות

log(){ echo "$(date -u +'%Y-%m-%dT%H:%M:%SZ') [INFO] $*"; }
warn(){ echo "$(date -u +'%Y-%m-%dT%H:%M:%SZ') [WARN] $*" >&2; }

json_field() { # json, key -> first numeric/string
  printf '%s' "$1" | grep -o "\"$2\":[[:space:]]*[-0-9.]\+" | head -n1 | awk -F: '{print $2}'
}

json_keystr() { # json, key -> first string
  printf '%s' "$1" | sed -n "s/.*\"$2\":\"\\([^\"]\\+\\)\".*/\\1/p" | head -n1
}

has_open_position(){
  local sym="$1"
  local resp
  resp="$(curl -fsS -X POST "$HOST/guard/smoke/run" \
      -H "Authorization: Bearer $TOKEN" \
      -H "Content-Type: application/json" \
      -d "\"$sym\"" || true)"
  # אם יש "No open position" => אין פוזיציה; אחרת מניחים שיש פוזיציה פתוחה
  if printf '%s\n' "$resp" | grep -q 'No open position'; then
    return 1  # אין פוזיציה
  else
    return 0  # יש פוזיציה
  fi
}

best_interval_for(){
  local sym="$1"
  local best_if=""
  local best_score="-1"

  IFS=',' read -r -a IFS_ARR <<< "$INTERVALS_CSV"
  for ifr in "${IFS_ARR[@]}"; do
    local scan resp adx atr bbmid ema21 price atrw norm_adx norm_atrw tf_score
    resp="$(curl -fsS "$HOST/scan/public-now?symbol=$sym&interval=$ifr&rich=1" || true)"
    # לשלוף ADX/ATR
    adx="$(printf '%s' "$resp" | sed -n 's/.*"adx":[[:space:]]*\([-0-9.]\+\).*/\1/p' | head -n1)"
    atr="$(printf '%s' "$resp" | sed -n 's/.*"atr":[[:space:]]*\([-0-9.]\+\).*/\1/p' | head -n1)"
    # נסה מחיר מ-bb_mid או ema_21
    bbmid="$(printf '%s' "$resp" | sed -n 's/.*"bb_mid":[[:space:]]*\([-0-9.]\+\).*/\1/p' | head -n1)"
    ema21="$(printf '%s' "$resp" | sed -n 's/.*"ema_21":[[:space:]]*\([-0-9.]\+\).*/\1/p' | head -n1)"
    price="$bbmid"; [ -z "$price" ] && price="$ema21"
    [ -z "$adx" ] && adx="0"
    [ -z "$atr" ] && atr="0"
    [ -z "$price" ] && { warn "no price for $sym@$ifr"; continue; }

    # ATR% משוער
    atrw="$(awk -v a="$atr" -v p="$price" 'BEGIN{ if(p>0){print (a/p*100)} else {print 0} }')"
    # נרמולים: ADX 20..40, ATR% 0..ATRW_CAP_PCT
    norm_adx="$(awk -v x="$adx" 'BEGIN{v=(x-20)/20; if(v<0)v=0; if(v>1)v=1; print v}')"
    norm_atrw="$(awk -v x="$atrw" -v cap="$ATRW_CAP_PCT" 'BEGIN{ if(x<0)x=0; if(x>cap)x=cap; print x/cap }')"

    tf_score="$(awk -v a="$norm_adx" -v b="$norm_atrw" -v wa="$ADX_WEIGHT" -v wb="$ATRW_WEIGHT" \
      'BEGIN{print a*wa + b*wb}')"

    log "$sym@$ifr: ADX=$adx ATR%=$(printf '%.3f' "$atrw") -> score=$(printf '%.3f' "$tf_score")"
    if awk "BEGIN{exit !($tf_score > $best_score)}"; then
      best_score="$tf_score"
      best_if="$ifr"
    fi
  done

  printf '%s|%s\n' "$best_if" "$best_score"
}

choose_profile(){
  # קלט: score (יכול להגיע מהשרת; אם לא - נגזרת מה-ADX/ATR)
  # פלט: profile,tp1,tp2,tp3,sl_pct,lev_hint,budget_hint,trail_atr,be_bps
  local sc="$1" atrw="$2"
  # ברירת מחדל:
  local prof="base" tp1=3 tp2=6 tp3=12 slp=1.2 lev="10-25x" bud="80-400" trail=2.3 be=6

  if awk "BEGIN{exit !($sc >= 8.5)}"; then
    prof="extreme"; tp1=6; tp2=12; tp3=24; lev="25-35x"; bud="150-600"; trail=3.2; be=4
  elif awk "BEGIN{exit !($sc >= 7.5)}"; then
    prof="aggressive"; tp1=4; tp2=8; tp3=16; lev="20-30x"; bud="120-500"; trail=2.6; be=5
  elif awk "BEGIN{exit !($sc >= 6.0)}"; then
    prof="base"; tp1=3; tp2=6; tp3=12; lev="10-25x"; bud="80-400"; trail=2.3; be=6
  else
    prof="conservative"; tp1=2; tp2=4; tp3=7; lev="5-12x"; bud="50-150"; trail=1.6; be=10
  fi

  # SL% לפי ATR% (עם תקרה הגנתית)
  # אם atrw=0 -> נשתמש במינימום שמרני
  local raw_sl
  raw_sl="$(awk -v a="$atrw" 'BEGIN{ if(a>0){print a*0.9} else {print 0.8} }')"
  slp="$(awk -v x="$raw_sl" -v cap="$APPROVAL_MAX_SL_PCT" 'BEGIN{ if(x>cap)x=cap; if(x<0.5)x=0.5; print x }')"

  printf '%s|%s|%s|%s|-%s|%s|%s|%s|%s\n' "$prof" "$tp1" "$tp2" "$tp3" "$slp" "$lev" "$bud" "$trail" "$be"
}

# ====== שלב 1: קבל את ה-Top1 ======
TOP="$(curl -fsS "$HOST/topk?limit=1")"
SYMBOL="$(printf '%s' "$TOP" | sed -n 's/.*\["\([^"]\+\)"].*/\1/p')"
[ -n "$SYMBOL" ] || { warn "no symbol from /topk"; exit 0; }
log "Top1: $SYMBOL"

# אם יש פוזיציה פתוחה על הסימבול — לא נוגעים (לא פותחים טיקט חדש)
if has_open_position "$SYMBOL"; then
  warn "position already open on $SYMBOL — skipping new ticket to avoid conflict."
  exit 0
fi

# ====== שלב 2: בחר timeframe משוקלל ======
BEST="$(best_interval_for "$SYMBOL")"
BEST_IF="$(printf '%s' "$BEST" | cut -d'|' -f1)"
IF_SCORE="$(printf '%s' "$BEST" | cut -d'|' -f2)"
[ -n "$BEST_IF" ] || { warn "no best interval"; exit 0; }

# הבא נתונים מהסורק ל-BEST_IF כדי לחשב ATR%
SCAN="$(curl -fsS "$HOST/scan/public-now?symbol=$SYMBOL&interval=$BEST_IF&rich=1" || true)"
ADX="$(printf '%s' "$SCAN" | sed -n 's/.*"adx":[[:space:]]*\([-0-9.]\+\).*/\1/p' | head -n1)"
ATR="$(printf '%s' "$SCAN" | sed -n 's/.*"atr":[[:space:]]*\([-0-9.]\+\).*/\1/p' | head -n1)"
PRICE="$(printf '%s' "$SCAN" | sed -n 's/.*"bb_mid":[[:space:]]*\([-0-9.]\+\).*/\1/p' | head -n1)"
[ -z "$PRICE" ] && PRICE="$(printf '%s' "$SCAN" | sed -n 's/.*"ema_21":[[:space:]]*\([-0-9.]\+\).*/\1/p' | head -n1)"
[ -z "$ADX" ] && ADX="0"; [ -z "$ATR" ] && ATR="0"
ATRW="$(awk -v a="$ATR" -v p="$PRICE" 'BEGIN{ if(p>0){print (a/p*100)} else {print 0} }')"

# נסה לקרוא score אם קיים באובייקט
SCORE="$(printf '%s' "$SCAN" | sed -n 's/.*"score":[[:space:]]*\([-0-9.]\+\).*/\1/p' | head -n1)"
[ -z "$SCORE" ] && SCORE="$SCORE_FALLBACK_MIN"

log "$SYMBOL@$BEST_IF chosen. ADX=$(printf '%.2f' "$ADX") ATR%%=$(printf '%.3f' "$ATRW") baseScore=$SCORE tfScore=$(printf '%.3f' "$IF_SCORE")"

# ====== שלב 3: פרופיל -> TP/SL + רמזי Lev/Budget ======
MAP="$(choose_profile "$SCORE" "$ATRW")"
PROF="$(printf '%s' "$MAP" | cut -d'|' -f1)"
TP1="$(printf '%s' "$MAP" | cut -d'|' -f2)"
TP2="$(printf '%s' "$MAP" | cut -d'|' -f3)"
TP3="$(printf '%s' "$MAP" | cut -d'|' -f4)"
SLP="$(printf '%s' "$MAP" | cut -d'|' -f5)"
LEV_HINT="$(printf '%s' "$MAP" | cut -d'|' -f6)"
BUD_HINT="$(printf '%s' "$MAP" | cut -d'|' -f7)"
TRAIL_ATR="$(printf '%s' "$MAP" | cut -d'|' -f8)"
BE_BPS="$(printf '%s' "$MAP" | cut -d'|' -f9)"

log "PROFILE=$PROF TP=[${TP1},${TP2},${TP3}] SL=${SLP}% Hints: LEV=${LEV_HINT} BUD=${BUD_HINT} Trail=${TRAIL_ATR}x BE=${BE_BPS}bps"

# ====== שלב 4: צד (BUY/SELL) לפי ADX & MACD היסט ב-BEST_IF ======
MACDH="$(printf '%s' "$SCAN" | sed -n 's/.*"macd_hist":[[:space:]]*\([-0-9.]\+\).*/\1/p' | head -n1)"
SIDE="BUY"
awk "BEGIN{exit !($ADX >= 28 && $MACDH < 0)}" 2>/dev/null && SIDE="SELL"

# ====== שלב 5: יצירת טיקט HYBRID (qty/lev=0 -> המנג'ר ימלא אחרי אישור) ======
PAYLOAD="$(cat <<JSON
{
  "symbol":"$SYMBOL",
  "side":"$SIDE",
  "qty":0,
  "leverage":0,
  "tp1":$TP1,
  "tp2":$TP2,
  "tp3":$TP3,
  "sl":$SLP,
  "tp_splits":[0.25,0.25,0.50],
  "note":"auto-top1 PRO [$BEST_IF] score=$SCORE tfScore=$(printf '%.2f' "$IF_SCORE") adx=$(printf '%.1f' "$ADX") atr%=$(printf '%.2f' "$ATRW") prof=$PROF lev=$LEV_HINT bud=$BUD_HINT trail=${TRAIL_ATR}x be=${BE_BPS}bps"
}
JSON
)"

RESP="$(curl -fsS -X POST "$HOST/ops/ticket" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD")"

echo "$RESP"
log "ticket sent (Approve/Reject בטלגרם)."

SH
chmod +x ./auto-pick.sh


