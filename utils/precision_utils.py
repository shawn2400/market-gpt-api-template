# utils/precision_utils.py

import logging
from utils.binance_client import client

def get_precision_info(symbol: str) -> tuple:
    """
    מחזיר את ה־stepSize ו־minQty לפי הנתונים של Binance Futures עבור סימבול נתון.
    אם אין נתונים – מחזיר ברירות מחדל.
    """
    try:
        info = client.futures_exchange_info()
        for s in info["symbols"]:
            if s["symbol"] == symbol:
                step_size = 0.01
                min_qty = 0.0
                for f in s["filters"]:
                    if f["filterType"] == "LOT_SIZE":
                        step_size = float(f["stepSize"])
                        min_qty = float(f["minQty"])
                        break
                return step_size, min_qty
    except Exception as e:
        logging.error(f"[precision_utils] שגיאה ב־get_precision_info: {e}")
    return 0.01, 0.0

