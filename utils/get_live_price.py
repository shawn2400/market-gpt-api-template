# utils/get_live_price.py

from utils.binance_client import client

def get_live_price(symbol: str) -> float:
    """
    מחזיר את מחיר השוק החי של סימבול Futures (כמו BTCUSDT).
    """
    try:
        res = client.futures_symbol_ticker(symbol=symbol)
        return float(res["price"])
    except Exception as e:
        print(f"[get_live_price] שגיאה בשליפת מחיר עבור {symbol}: {e}")
        return None














