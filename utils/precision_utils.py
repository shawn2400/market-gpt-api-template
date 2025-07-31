# utils/precision_utils.py

from utils.binance_client import client

_precision_cache = {}

def get_precision_info(symbol: str):
    """
    מחזיר מידע על דיוק חוזים (precision) מ־Binance עבור symbol.
    """
    if symbol in _precision_cache:
        return _precision_cache[symbol]

    info = client.futures_exchange_info()
    for s in info["symbols"]:
        if s["symbol"] == symbol:
            for f in s["filters"]:
                if f["filterType"] == "LOT_SIZE":
                    step_size = float(f["stepSize"])
                    _precision_cache[symbol] = {"stepSize": step_size}
                    return _precision_cache[symbol]
    return {"stepSize": 0.01}  # ברירת מחדל


