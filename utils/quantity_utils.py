# utils/quantity_utils.py

import math
import logging
from utils.calculate_quantity import get_precision_info

def round_step(quantity: float, step: float) -> float:
    """עיגול כמות לפי stepSize."""
    try:
        return math.floor(quantity / step) * step
    except Exception as e:
        logging.error(f"[!] שגיאה בעיגול כמות: {e}")
        return 0.0

def auto_risk_allocation(entry_price: float, stop_price: float, total_budget: float, risk_percent: float = 2.0, leverage: float = 1, symbol: str = None) -> float:
    """
    מחשב כמות חוזים לפי סיכון (Risk %) וה־SL בפועל.
    """
    try:
        risk_amount = total_budget * (risk_percent / 100)
        risk_per_unit = abs(entry_price - stop_price)
        if risk_per_unit == 0:
            raise ValueError("⚠️ Entry ו־Stop שווים – לא ניתן לחשב סיכון")

        raw_qty = risk_amount / risk_per_unit
        if symbol:
            precision = get_precision_info(symbol)
            step = precision.get("stepSize", 0.01)
            min_qty = precision.get("minQty", 0.0)
            qty = round_step(raw_qty, step)
            if qty < min_qty:
                logging.warning(f"[!] כמות נמוכה מהמינימום: {qty} < {min_qty} (symbol={symbol})")
                return 0.0
        else:
            qty = round(raw_qty, 3)

        return qty
    except Exception as e:
        logging.error(f"[!] שגיאה ב־auto_risk_allocation: {e}")
        return 0.0

def apply_precision(symbol: str, quantity: float) -> float:
    """
    מחזיר כמות מעוגלת לפי stepSize ומינימום.
    """
    try:
        precision = get_precision_info(symbol)
        step = precision.get("stepSize", 0.01)
        min_qty = precision.get("minQty", 0.0)
        qty = round_step(quantity, step)
        return qty if qty >= min_qty else 0.0
    except Exception as e:
        logging.error(f"[!] שגיאה ב־apply_precision: {e}")
        return 0.0




