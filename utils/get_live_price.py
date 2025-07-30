# utils/get_live_price.py

from utils.binance_client import client

def get_price(symbol: str, market_type: str = "futures") -> float:
    """
    מחזיר מחיר חי מהבורסה. Fallback אוטומטי ל־Spot אם Futures לא מחזיר ערך.
    """
    try:
        if market_type == "futures":
            data = client.futures_symbol_ticker(symbol=symbol)
            price = float(data["price"])
            if price > 0:
                return price
        # fallback ל־Spot
        data = client.get_symbol_ticker(symbol=symbol)
        return float(data["price"])
    except Exception as e:
        raise RuntimeError(f"שגיאה בשליפת מחיר חי עבור {symbol}: {e}")








