# utils/quantity_utils.py

import math
import logging
from utils.calculate_quantity import get_precision_info

def round_step(quantity: float, step: float) -> float:
    """
    עיגול כמות לפי stepSize
    """
    try:
        return math.floor(quantity / step) * step
    except Exception as e:
        logging.error(f"[!] שגיאה בעיגול כמות: {e}")
        return 0.0

def auto_risk_allocation(entry_price: float, stop_price: float, total_budget: float, risk_percent: float = 2.0, leverage: float = 1, symbol: str = None) -> float:
    """
    מחשב כמות חוזים לפי סיכון מוגדר ו־SL
    """
    try:
        risk_amount = total_budget * (risk_percent / 100)
        risk_per_unit = abs(entry_price - stop_price)
        if risk_per_unit == 0:
            raise ValueError("⚠️ Entry ו־Stop שווים – לא ניתן לחשב סיכון")

        raw_qty = risk_amount / risk_per_unit
        capital_required = raw_qty * entry_price

        if symbol:
            precision = get_precision_info(symbol)
            step = precision.get("stepSize", 0.01)
            qty = round_step(raw_qty, step)
        else:
            qty = round(raw_qty, 3)

        return qty
    except Exception as e:
        logging.error(f"[!] שגיאה ב־auto_risk_allocation: {e}")
        return 0.0

def generate_grid_levels_with_sl(entry_price: float, tp_price: float, sl_price: float, levels: int = 3) -> dict:
    """
    מחלק טווח רווח/הפסד לרמות TP ו־SL לגריד
    """
    try:
        tp_diff = tp_price - entry_price
        sl_diff = entry_price - sl_price

        tp_levels = [round(entry_price + (tp_diff * i / levels), 4) for i in range(1, levels + 1)]
        sl_levels = [round(entry_price - (sl_diff * i / levels), 4) for i in range(1, levels + 1)]

        return {
            "tp_levels": tp_levels,
            "sl_levels": sl_levels
        }
    except Exception as e:
        logging.error(f"[!] שגיאה ביצירת רמות גריד: {e}")
        return {
            "tp_levels": [],
            "sl_levels": []
        }

def apply_precision(symbol: str, quantity: float) -> float:
    """
    מחזיר כמות מעוגלת לפי stepSize של הסימבול
    """
    try:
        precision = get_precision_info(symbol)
        step = precision.get("stepSize", 0.01)
        return round_step(quantity, step)
    except Exception as e:
        logging.error(f"[!] שגיאה ב־apply_precision: {e}")
        return 0.0




