# utils/quantity_utils.py

import math
from utils.sl_tp_utils import get_symbol_precision

def round_step(quantity, step):
    """
    עיגול כמות לפי stepSize
    """
    return math.floor(quantity / step) * step

def calculate_quantity(budget_usd, entry_price, leverage, step_size=0.01):
    """
    מחשב כמות (quantity) עם עיגול לפי stepSize
    """
    try:
        raw_qty = (budget_usd * leverage) / entry_price
        qty = round_step(raw_qty, step_size)
        return round(qty, 6)
    except Exception as e:
        print(f"[!] שגיאה בחישוב כמות: {e}")
        return 0

def auto_risk_allocation(entry_price, stop_price, total_budget, risk_percent=2, leverage=1, symbol=None):
    """
    מחשב תקציב ו־כמות לפי סיכון אחוזי והפרש כניסה-סטופ
    """
    try:
        risk_per_trade = total_budget * (risk_percent / 100)
        risk_per_unit = abs(entry_price - stop_price)
        if risk_per_unit == 0:
            raise ValueError("Stop price and entry price זהים — אי אפשר לחשב סיכון")

        raw_qty = risk_per_trade / risk_per_unit
        capital_required = raw_qty * entry_price

        # עיגול לפי stepSize אם יש סימבול
        if symbol:
            step = float(get_symbol_precision(symbol).get("stepSize", 0.01))
            qty = round_step(raw_qty, step)
        else:
            qty = round(raw_qty, 3)

        return {
            "capital_required": min(capital_required, total_budget),
            "quantity": qty
        }

    except Exception as e:
        print(f"[!] שגיאה בחישוב סיכון: {e}")
        return {
            "capital_required": total_budget,
            "quantity": 0
        }

def generate_grid_levels_with_sl(entry_price, tp_price, sl_price, levels=3):
    """
    מחלק את הטווח TP ו־SL לגריד מדורג לשני הצדדים
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
        print(f"[!] שגיאה ביצירת רמות גריד: {e}")
        return {
            "tp_levels": [],
            "sl_levels": []
        }



