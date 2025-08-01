# utils/precision_utils.py

import math
from utils.binance_client import client
import logging

def get_precision_info(symbol: str) -> dict:
    """
    מחזיר את הגדרות הדיוק של הסימול (מחיר וכמות) לפי הגדרות הבורסה.
    """
    try:
        info = client.get_symbol_info(symbol)
        filters = info.get('filters', [])

        step_size = float(next(f['stepSize'] for f in filters if f['filterType'] == 'LOT_SIZE'))
        tick_size = float(next(f['tickSize'] for f in filters if f['filterType'] == 'PRICE_FILTER'))

        quantity_precision = int(-math.log10(step_size)) if step_size < 1 else 0
        price_precision = int(-math.log10(tick_size)) if tick_size < 1 else 0

        return {
            "stepSize": step_size,
            "tickSize": tick_size,
            "quantityPrecision": quantity_precision,
            "pricePrecision": price_precision
        }
    except Exception as e:
        logging.error(f"❌ שגיאה ב־get_precision_info עבור {symbol}: {e}")
        # ברירת מחדל
        return {"stepSize": 1, "tickSize": 1, "quantityPrecision": 0, "pricePrecision": 0}


def round_to_precision(value: float, precision: int) -> float:
    """
    מעגל את value לפי מספר הספרות precision.
    """
    fmt = "{:0." + str(precision) + "f}"
    try:
        return float(fmt.format(value))
    except Exception:
        return round(value, precision)





