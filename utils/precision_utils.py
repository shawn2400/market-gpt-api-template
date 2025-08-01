# utils/precision_utils.py

import math
import logging
from utils.binance_client import client

def get_precision_info(symbol: str) -> dict:
    """
    מחזיר מידע על דיוק המחיר וכמות לפי הגדרות הבורסה (BINANCE futures).
    מבוסס על ה־PRICE_FILTER ו־LOT_SIZE מה־exchange_info.
    """
    try:
        info = client.futures_exchange_info()
        symbol_info = next((s for s in info["symbols"] if s["symbol"] == symbol), None)
        if symbol_info is None:
            raise ValueError(f"Symbol {symbol} not found in exchange info")

        filters = {f["filterType"]: f for f in symbol_info["filters"]}
        tick_size = float(filters["PRICE_FILTER"]["tickSize"])
        step_size = float(filters["LOT_SIZE"]["stepSize"])

        price_precision = int(round(-math.log10(tick_size)))
        quantity_precision = int(round(-math.log10(step_size)))

        return {
            "tickSize": tick_size,
            "stepSize": step_size,
            "pricePrecision": price_precision,
            "quantityPrecision": quantity_precision
        }

    except Exception as e:
        logging.error(f"[precision_utils] Failed to fetch precision for {symbol}: {e}")
        # ברירת מחדל במקרה של כישלון
        return {
            "tickSize": 0.01,
            "stepSize": 0.000001,
            "pricePrecision": 2,
            "quantityPrecision": 6
        }


def round_to_precision(value: float, precision: int) -> float:
    """
    מעגל ערך למספר הספרות אחרי הנקודה לפי precision.
    """
    try:
        if precision < 0:
            return value
        return round(value, precision)
    except Exception as e:
        logging.error(f"[precision_utils] round_to_precision failed: {e}")
        return value







