# utils/calculate_quantity.py

from math import floor
from utils.binance_client import client

def get_step_size(symbol):
    try:
        info = client.futures_exchange_info()
        for s in info["symbols"]:
            if s["symbol"] == symbol:
                for f in s["filters"]:
                    if f["filterType"] == "LOT_SIZE":
                        return float(f["stepSize"])
    except Exception as e:
        print(f"שגיאה בשליפת stepSize עבור {symbol}: {e}")
    return 0.01  # ברירת מחדל

def calculate_quantity(symbol, entry_price, leverage, budget_usdt):
    try:
        step_size = get_step_size(symbol)
        if entry_price == 0:
            raise ValueError("Entry price cannot be zero")
        raw_qty = (budget_usdt * leverage) / entry_price
        qty = floor(raw_qty / step_size) * step_size
        return round(qty, 6)
    except Exception as e:
        print(f"שגיאה בחישוב כמות: {e}")
        return 0

