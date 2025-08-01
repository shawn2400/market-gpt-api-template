# utils/precision_utils.py

import logging
from utils.binance_client import client

def get_precision_info(symbol: str) -> dict:
    """
    מחזיר dict עם:
      - pricePrecision: מספר ספרות אחרי הנקודה למחיר
      - quantityPrecision: מספר ספרות אחרי הנקודה לכמות
    """
    try:
        info = client.futures_exchange_info()
        for s in info.get("symbols", []):
            if s["symbol"] == symbol:
                return {
                    "pricePrecision": s.get("pricePrecision", 8),
                    "quantityPrecision": s.get("quantityPrecision", 8)
                }
        raise ValueError(f"Symbol not found in exchange info: {symbol}")
    except Exception as e:
        logging.error(f"[PrecisionUtils] failed to fetch precision for {symbol}: {e}")
        # ברירת מחדל
        return {"pricePrecision": 8, "quantityPrecision": 8}

def round_to_precision(value: float, precision: int) -> float:
    """
    עיגול ערך float ל־precision ספרות אחרי הנקודה
    """
    format_str = "{:0." + str(precision) + "f}"
    try:
        return float(format_str.format(value))
    except Exception as e:
        logging.warning(f"[PrecisionUtils] round failed ({value} @ {precision}): {e}")
        return value










