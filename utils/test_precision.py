# test_precision.py

from utils.precision_utils import get_precision_info, round_to_precision

def test_symbol_precision(symbol: str):
    print(f"\n🔍 בדיקת דיוק עבור {symbol}...")

    precision = get_precision_info(symbol)
    print(f"דיוק שנשלף מ־Binance:\n{precision}")

    test_price = 1234.56789
    test_qty = 0.123456

    rounded_price = round_to_precision(test_price, precision['pricePrecision'])
    rounded_qty = round_to_precision(test_qty, precision['quantityPrecision'])

    print(f"\nמחיר לדוגמה: {test_price} → עיגול ל־{precision['pricePrecision']} ספרות = {rounded_price}")
    print(f"כמות לדוגמה: {test_qty} → עיגול ל־{precision['quantityPrecision']} ספרות = {rounded_qty}")

if __name__ == "__main__":
    # בדיקה עבור מספר סמלים
    for symbol in ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]:
        test_symbol_precision(symbol)
