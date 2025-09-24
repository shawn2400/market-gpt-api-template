cd /app

cat > parse_exchange_info.awk <<'AWK'
# Output columns per symbol: SYMBOL  STATUS  TICKSIZE  MINPRICE  STEPSIZE  MINQTY
BEGIN{
  RS="\"symbol\":\"";   # each record starts right after "symbol":
  OFS="\t";
}
NR==1 { next }          # skip preamble before first symbol
{
  rec = $0
  # symbol until next "
  split(rec, a, "\""); symbol = a[1]

  status=minPrice=tickSize=minQty=stepSize=""

  # status
  if (match(rec, /"status":"[^"]+"/)) {
    tmp = substr(rec, RSTART, RLENGTH)
    sub(/^"status":"/, "", tmp); sub(/"$/, "", tmp)
    status = tmp
  }

  # PRICE_FILTER: minPrice
  if (match(rec, /"PRICE_FILTER"[^}]*"minPrice":"[^"]+"/)) {
    tmp = substr(rec, RSTART, RLENGTH)
    sub(/^.*"minPrice":"/, "", tmp); sub(/".*$/, "", tmp)
    minPrice = tmp
  }

  # PRICE_FILTER: tickSize
  if (match(rec, /"PRICE_FILTER"[^}]*"tickSize":"[^"]+"/)) {
    tmp = substr(rec, RSTART, RLENGTH)
    sub(/^.*"tickSize":"/, "", tmp); sub(/".*$/, "", tmp)
    tickSize = tmp
  }

  # LOT_SIZE: minQty
  if (match(rec, /"LOT_SIZE"[^}]*"minQty":"[^"]+"/)) {
    tmp = substr(rec, RSTART, RLENGTH)
    sub(/^.*"minQty":"/, "", tmp); sub(/".*$/, "", tmp)
    minQty = tmp
  }

  # LOT_SIZE: stepSize
  if (match(rec, /"LOT_SIZE"[^}]*"stepSize":"[^"]+"/)) {
    tmp = substr(rec, RSTART, RLENGTH)
    sub(/^.*"stepSize":"/, "", tmp); sub(/".*$/, "", tmp)
    stepSize = tmp
  }

  if (symbol!="" && status!="")
    print symbol, status, tickSize, minPrice, stepSize, minQty
}
AWK




