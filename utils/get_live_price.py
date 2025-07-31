# utils/get_live_price.py

from utils.binance_client import client

def get_live_price(symbol: str, market_type: str = "futures") -> float:
    """
    מחזיר את מחיר השוק החי לפי סוג השוק (futures / spot / grid).
    אם market_type הוא 'grid', ישתמש ב-futures כברירת מחדל.
    """
    try:
        # grid נחשב כ־futures כברירת מחדל
        if market_type == "grid":
            market_type = "futures"

        if market_type == "futures":
            res = client.futures_symbol_ticker(symbol=symbol)
        elif market_type == "spot":
            res = client.get_symbol_ticker(symbol=symbol)
        else:
            print(f"[get_live_price] שוק לא נתמך: {market_type}")
            return None

        return float(res["price"])

    except Exception as e:
        print(f"[get_live_price] שגיאה בשליפת מחיר עבור {symbol}: {e}")
        return None















