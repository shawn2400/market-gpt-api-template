#!/usr/bin/env bash

SYMBOLS=("BTCUSDT" "ETHUSDT")
URL_INFO="https://fapi.binance.com/fapi/v1/exchangeInfo"
URL_PRICE="https://fapi.binance.com/fapi/v1/ticker/price"

echo "=============================="
echo "🔍 בדיקת דרישות מינימום Binance (minQty / minNotional)"
echo "=============================="

# שליפת exchangeInfo פעם אחת
info=$(curl -s "$URL_INFO" || true)

for sym in "${SYMBOLS[@]}"; do
  echo "=== $sym ==="

  block=$(echo "$info" | tr '{' '\n' | grep "\"symbol\":\"$sym\"" || true)

  minQty=$(echo "$block" | grep -o '"minQty":"[^"]*"' | head -n1 | cut -d':' -f2 | tr -d '"' || echo "0.0")
  minNotional=$(echo "$block" | grep -o '"notional":"[^"]*"' | head -n1 | cut -d':' -f2 | tr -d '"' || echo "5.0")

  price=$(curl -s "$URL_PRICE?symbol=$sym" | sed -E 's/.*"price":"([^"]+)".*/\1/' || echo "0.0")

  if [[ -z "$minQty" ]]; then minQty="0.0"; fi
  if [[ -z "$minNotional" ]]; then minNotional="5.0"; fi
  if [[ -z "$price" ]]; then price="0.0"; fi

  testQty="0.001"
  if [[ "$sym" == "ETHUSDT" ]]; then
    testQty="0.01"
  fi

  notional=$(awk "BEGIN {print $testQty * $price}" 2>/dev/null)

  echo "מחיר נוכחי: $price"
  echo "minQty: $minQty | minNotional: $minNotional"
  echo "בדיקת כמות לדוגמה: $testQty → notional=$notional"

  cmp1=$(awk "BEGIN {print ($testQty < $minQty)}" 2>/dev/null)
  cmp2=$(awk "BEGIN {print ($notional < $minNotional)}" 2>/dev/null)

  if [[ "$cmp1" == "1" ]]; then
    echo "⚠️ הכמות קטנה מהמינימום!"
  elif [[ "$cmp2" == "1" ]]; then
    echo "⚠️ הערך הכספי קטן מהמינימום!"
  else
    echo "✅ הכמות חוקית לפי דרישות Binance"
  fi
  echo ""
done

echo "=============================="
echo "✔️ סיום בדיקות"
exit 0














