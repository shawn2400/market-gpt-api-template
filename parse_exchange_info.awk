cat > parse_exchange_info.awk <<'AWK'
# מוציא לכל סימבול: SYMBOL  STATUS  TICKSIZE  MINPRICE  STEPSIZE  MINQTY
# עובד גם על ה־JSON המלא של Binance וגם על קובץ לוקאלי ששמרת.
BEGIN{
  RS="\"symbol\":\"";   # כל רשומה מתחילה אחרי "symbol":
  OFS="\t";
}
NR==1 { next }          # לדלג על כל מה שלפני הרשומה הראשונה
{
  rec = $0

  # שם הסימבול הוא עד ה-"
  split(rec, a, "\""); symbol = a[1]

  status=minPrice=tickSize=minQty=stepSize=""

  # סטטוס
  if (match(rec, /"status":"([^"]+)"/, m)) status = m[1]

  # מחיר/טיק מתוך PRICE_FILTER של אותה רשומה
  if (match(rec, /"PRICE_FILTER"[^}]*"minPrice":"([^"]+)"/, m)) minPrice = m[1]
  if (match(rec, /"PRICE_FILTER"[^}]*"tickSize":"([^"]+)"/, m)) tickSize = m[1]

  # כמות/סטפ מתוך LOT_SIZE של אותה רשומה
  if (match(rec, /"LOT_SIZE"[^}]*"minQty":"([^"]+)"/, m))   minQty   = m[1]
  if (match(rec, /"LOT_SIZE"[^}]*"stepSize":"([^"]+)"/, m)) stepSize = m[1]

  # הדפסה רק אם יש סימבול וסטטוס
  if (symbol!="" && status!="")
    print symbol, status, tickSize, minPrice, stepSize, minQty
}
AWK


