# utils/precision_utils.py

import math
from utils.binance_client import client
import logging

def get_precision_info(symbol: str) -> dict:
    """
    מחזיר מידע על דיוק המחיר וכמות הסימבול לפי הגדרות הבורסה.
    מבוסס על ה־PRICE_FILTER ו־LOT_SIZE מה־exchange_info של Binance.
    """
    try:
        info = client.futures_exchange_info()
        # Exchange info returns dict with 'symbols' list
        symbol_info = next((s for s in info['symbols'] if s['symbol'] == symbol), None)
        if symbol_info is None:
            raise ValueError(f"Symbol {symbol} not found in exchange info")

        # בחרי את הפילטרים הרלוונטיים
        filters = {f['filterType']: f for f in symbol_info['filters']}
        tick_size = float(filters['PRICE_FILTER']['tickSize'])
        step_size = float(filters['LOT_SIZE']['stepSize'])

        # חשב את הדיוק כמספר הספרות אחרי הנקודה
        price_precision = int(round(-math.log10(tick_size)))
        quantity_precision = int(round(-math.log10(step_size)))

        return {
            'tickSize': tick_size,
            'stepSize': step_size,
            'pricePrecision': price_precision,
            'quantityPrecision': quantity_precision
        }

    except Exception as e:
        logging.error(f"[precision_utils] Failed to fetch precision info for {symbol}: {e}")
        # ערכים ברירת מחדל
        return {
            'tickSize': 0.01,
            'stepSize': 0.000001,
            'pricePrecision': 2,
            'quantityPrecision': 6
        }


def round_to_precision(value: float, precision: int) -> float:
    """
    מעגל ערך לדיוק נתון (מספר ספרות אחרי הנקודה).
    """
    if precision < 0:
        # לא עיגול במקרה של precision שלילי
        return value
    return round(value, precision)






