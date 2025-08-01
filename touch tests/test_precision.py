# utils/precision_utils.py

import logging
from math import floor
from utils.binance_client import client
from decimal import Decimal

def get_precision_info(symbol: str) -> dict:
    """
    שולף מידע על דיוקים של סימבול: stepSize (כמות), minQty (כמות מינימלית), tickSize (מחיר).
    נתמך רק על Binance Futures.
    """
    try:
        info = client.futures_exchange_info()
        for s in info.get("symbols", []):
            if s["symbol"] == symbol:
                data = {}
                for f in s.get("filters", []):
                    if f["filterType"] == "LOT_SIZE":
                        data["stepSize"] = float(f["stepSize"])
                        data["minQty"] = float(f["minQty"])
                    elif f["filterType"] == "PRICE_FILTER":
                        data["tickSize"] = float(f["tickSize"])
                return {
                    "stepSize": data.get("stepSize", 0.01),
                    "minQty": data.get("minQty", 0.0),
                    "tickSize": data.get("tickSize", 0.01)
                }
    except Exception as e:
        logging.error(f"[!] שגיאה ב־get_precision_info עבור {symbol}: {e}")
    return {"stepSize": 0.01, "minQty": 0.0, "tickSize": 0.01}

def round_step(value: float, step: float) -> float:
    """
    עיגול כלפי מטה לערך הקרוב לפי step חוקי (למשל stepSize לכמות).
    """
    try:
        return floor(value / step) * step
    except Exception as e:
        logging.error(f"[!] שגיאה ב־round_step: {e}")
        return 0.0

def round_tick(price: float, tick_size: float) -> float:
    """
    עיגול מחיר לפי tickSize חוקי (למשל למחיר limit).
    """
    try:
        return floor(price / tick_size) * tick_size
    except Exception as e:
        logging.error(f"[!] שגיאה ב־round_tick: {e}")
        return price

def get_step_decimal_places(step: float) -> int:
    """
    מחשב כמה ספרות אחרי הנקודה יש ל־step – לדוגמה 0.001 → 3 ספרות.
    """
    try:
        return abs(Decimal(str(step)).as_tuple().exponent)
    except Exception:
        return 2  # ברירת מחדל













