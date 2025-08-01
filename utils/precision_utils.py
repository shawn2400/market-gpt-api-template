# utils/precision_utils.py

import logging
from utils.binance_client import client

def get_precision_info(symbol: str) -> dict:
    """
    מחזיר dict עם שני שדות:
    - pricePrecision: מספר הנקודות אחרי הנקודה במחיר
    - quantityPrecision: מספר הנקודות אחרי הנקודה בכמות
    """
    try:
        info = client.futures_exchange_info()
        for s in info.get("symbols", []):
            if s["symbol"] == symbol:
                return {
                    "pricePrecision": s.get("pricePrecision", 8),
                    "quantityPrecision": s.get("quantityPrecision", 8)
                }
        raise ValueError(f"Symbol not found: {symbol}")
    except Exception as e:
        logging.error(f"[precision_utils] failed for {symbol}: {e}")
        # במקרה של תקלה, נחזיר ברירות מחדל סבירות
        return {"pricePrecision": 8, "quantityPrecision": 8}

def round_to_precision(value: float, precision: int) -> float:
    """
    מעגל את הערך ל־precision ספרות אחרי הנקודה.
    """
    fmt = "{:0." + str(precision) + "f}"
    try:
        return float(fmt.format(value))
    except Exception as e:
        logging.warning(f"[precision_utils] round failed ({value}@{precision}): {e}")
        return value















