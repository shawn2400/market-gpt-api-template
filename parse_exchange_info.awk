# פרסור JSON ל־TSV בלי jq
# קלט: exchangeInfo.json כפי שמוחזר מ־/fapi/v1/exchangeInfo
# פלט (TSV): SYMBOL  STATUS  TICKSIZE  MINPRICE  STEPSIZE  MINQTY

BEGIN {
  FS = "\n"
  RS = ""
}

# פונקציה שמחזירה ערך אחרי "key":"value"
function get_str(rec, key,    r,pat) {
  pat = "\"" key "\":\""
  r = index(rec, pat)
  if (!r) return ""
  r += length(pat)
  return substr(rec, r, index(substr(rec, r), "\"")-1)
}

# פונקציה שמוצאת תת-בלוק לפי filterType
function get_filter_block(rec, ftype,   pos,blk,s,e) {
  # מחפשים "filterType":"FTYPE"
  pos = match(rec, "\"filterType\":\"" ftype "\"")
  if (!pos) return ""
  # חפש את ה- { הקודם
  s = rindex_to(rec, "{", pos)
  # חפש את ה- } הבא
  e = index(substr(rec, pos), "}")
  if (!e) return ""
  e = pos + e - 1
  return substr(rec, s, e - s + 1)
}

# חיפוש מהסוף אחורה לתו
function rindex_to(s, ch, to_pos,    i) {
  if (to_pos <= 0 || to_pos > length(s)) to_pos = length(s)
  for (i = to_pos; i >= 1; i--) {
    if (substr(s, i, 1) == ch) return i
  }
  return 1
}

# מוציא value מבלוק בסגנון "key":"value" או "key":value
function get_kv(block, key,    m,a) {
  # נסה עם גרשיים
  m = match(block, "\"" key "\":\"[^\"]+\"")
  if (m) {
    a = substr(block, RSTART+length(key)+4, RLENGTH-(length(key)+4+1))
    return a
  }
  # נסה בלי גרשיים
  m = match(block, "\"" key "\":[^,}]+")
  if (m) {
    a = substr(block, RSTART+length(key)+3, RLENGTH-(length(key)+3))
    gsub(/[ \t\r\n"]/, "", a)
    return a
  }
  return ""
}

{
  # הופך לשורה אחת
  json = $0
  gsub(/[\r\n]/, "", json)

  # חותך רק את אזור הסימבולים
  m = match(json, /"symbols":[[]/)
  if (!m) exit
  start = RSTART + RLENGTH
  # סוף המערך - הסוגר המרובע הסגור הראשון אחרי
  tail = substr(json, start)
  # נסיר את הזנב אחרי ה- ] הראשון
  closeIdx = index(tail, "]")
  if (!closeIdx) exit
  syms = substr(tail, 1, closeIdx-1)

  # מפריד בין רשומות סימבול — משתמש בדפוס המפורש '},{"symbol":"'
  gsub(/\},\{"symbol":"\044/, "\n\044", syms)  # \044 == "

  n = split(syms, rows, "\n")
  for (i=1; i<=n; i++) {
    rec = rows[i]
    if (rec == "") continue
    # מחזיר את הסוגריים החסרים כי חתכנו על דלימיטר
    rec = "{\"symbol\":\"" rec

    sym = get_str(rec, "symbol")
    status = get_str(rec, "status")

    # בלוקים של פילטרים
    pf = get_filter_block(rec, "PRICE_FILTER")
    lf = get_filter_block(rec, "LOT_SIZE")

    tick = get_kv(pf, "tickSize")
    minp = get_kv(pf, "minPrice")
    step = get_kv(lf, "stepSize")
    minq = get_kv(lf, "minQty")

    # ניקוי רווחים
    gsub(/[ \t]/, "", tick); gsub(/[ \t]/, "", minp)
    gsub(/[ \t]/, "", step); gsub(/[ \t]/, "", minq)

    if (sym != "") {
      printf "%s\t%s\t%s\t%s\t%s\t%s\n", sym, status, tick, minp, step, minq
    }
  }
}
