# utils/precision_utils.py

import math
from utils.binance_client import client

def get_precision_info(symbol: str) -> dict:
    """
    מחזיר את הגדרות הדיוק של הסימול (מחיר וכמות) לפי הגדרות הבורסה.
    """
    info = client.get_symbol_info(symbol)
    filters = info.get('filters', [])

    # שליפת ה-stepSize (לכמות) ו-tickSize (למחיר)
    step_size = float(next(f['stepSize'] for f in filters if f['filterType'] == 'LOT_SIZE'))
    tick_size = float(next(f['tickSize'] for f in filters if f['filterType'] == 'PRICE_FILTER'))

    # חישוב מספר הספרות אחרי הנקודה
    quantity_precision = int(-math.log10(step_size)) if step_size < 1 else 0
    price_precision = int(-math.log10(tick_size)) if tick_size < 1 else 0

    return {
        "stepSize": f"{step_size:.8f}",
        "tickSize": f"{tick_size:.8f}",
        "quantityPrecision": quantity_precision,
        "pricePrecision": price_precision
    }

def round_to_precision(value: float, precision: int) -> float:
    """
    מעגל את value לפי מספר הספרות precision.
    """
    return round(value, precision)




