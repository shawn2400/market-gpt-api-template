# utils/precision_utils.py

from utils.binance_client import client

# מטמון פנימי – מונע קריאות חוזרות ל־Binance
_precision_cache = {}

def get_precision_info(symbol: str) -> dict:
    """
    מחזיר מידע על דיוק החוזה (precision) מ־Binance עבור Futures symbol נתון.
    כולל stepSize לעיגול כמות נכונה.
    """
    try:
        if symbol in _precision_cache:
            return _precision_cache[symbol]

        exchange_info = client.futures_exchange_info()
        for s in exchange_info.get("symbols", []):
            if s["symbol"] == symbol:
                for f in s.get("filters", []):
                    if f.get("filterType") == "LOT_SIZE":
                        step_size = float(f.get("stepSize", 0.01))
                        _precision_cache[symbol] = {"stepSize": step_size}
                        return _precision_cache[symbol]

    except Exception as e:
        print(f"[precision_utils] שגיאה באחזור stepSize עבור {symbol}: {e}")

    return {"stepSize": 0.01}  # ברירת מחדל אם נכשל



