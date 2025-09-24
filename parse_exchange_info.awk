cat > parse_exchange_info.awk <<'AWK'
# מחלץ לכל סימבול: SYMBOL  STATUS  TICKSIZE  MINPRICE  STEPSIZE  MINQTY
BEGIN{
  RS="\"symbol\":\"";   # כל רשומה מתחילה אחרי "symbol":
  OFS="\t";
}
NR==1 { next }          # לדלג על ההקדמה לפני הסימבול הראשון
{
  rec=$0;

  # שם הסימבול הוא עד ה-" הבא
  split(rec, a, "\""); symbol=a[1];

  status=minPrice=tickSize=minQty=stepSize="";

  if (match(rec, /"status":"([^"]+)"/, m))                 status   = m[1];
  if (match(rec, /"PRICE_FILTER"[^}]*"minPrice":"([^"]+)"/, m)) minPrice = m[1];
  if (match(rec, /"PRICE_FILTER"[^}]*"tickSize":"([^"]+)"/, m)) tickSize = m[1];
  if (match(rec, /"LOT_SIZE"[^}]*"minQty":"([^"]+)"/, m))       minQty   = m[1];
  if (match(rec, /"LOT_SIZE"[^}]*"stepSize":"([^"]+)"/, m))     stepSize = m[1];

  if (symbol!="" && status!="")
    print symbol, status, tickSize, minPrice, stepSize, minQty;
}
AWK

