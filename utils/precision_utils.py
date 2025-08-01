# utils/precision_utils.py

import math
from utils.binance_client import client

def get_precision_info(symbol: str) -> dict:
    """
    מחזיר מידע על הדיוקים של symbol כפי שמוגדרים ב-Binance:
    - stepSize (מחרוזת)
    - tickSize (מחרוזת)
    - quantity_precision (int, מספר ספרות אחרי הנקודה לעיגול כמות)
    - price_precision (int, מספר ספרות אחרי הנקודה לעיגול מחיר)
    - quantityPrecision (same as quantity_precision, camelCase)
    - pricePrecision (same as price_precision, camelCase)
    """
    info = client.get_symbol_info(symbol=symbol)
    step_size_str = None
    tick_size_str = None

    for f in info.get("filters", []):
        if f.get("filterType") == "LOT_SIZE":
            step_size_str = f.get("stepSize")
        elif f.get("filterType") == "PRICE_FILTER":
            tick_size_str = f.get("tickSize")

    # המרה לפלוט ועיגול עשרוני
    step_size = float(step_size_str) if step_size_str else 1.0
    tick_size = float(tick_size_str) if tick_size_str else 1.0

    quantity_precision = int(round(-math.log10(step_size))) if 0 < step_size < 1 else 0
    price_precision = int(round(-math.log10(tick_size))) if 0 < tick_size < 1 else 0

    return {
        "stepSize": step_size_str or "1",
        "tickSize": tick_size_str or "1",
        "quantity_precision": quantity_precision,
        "price_precision": price_precision,
        "quantityPrecision": quantity_precision,
        "pricePrecision": price_precision
    }

def round_to_precision(value: float, precision: int) -> float:
    """
    עיגול ערך ל־precision עשרוניות.
    """
    return round(value, precision)

