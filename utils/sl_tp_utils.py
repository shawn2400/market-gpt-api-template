# utils/sl_tp_utils.py

import numpy as np
import logging
from typing import Tuple

def calculate_sl_tp(
    entry_price: float,
    direction: str,
    atr: float = None,
    risk_reward: float = 2.0,
    sl_pct: float = 0.7,
    tp_pct: float = 1.4
) -> Tuple[float, float]:
    """
    חישוב SL ו-TP לטרייד, לפי ATR או אחוזים.
    - direction: 'long' או 'short'
    - atr: סטיית טווח ממוצעת (אם קיים)
    - risk_reward: יחס סיכוי/סיכון (ברירת מחדל 2)
    - sl_pct/tp_pct: אחוז מהמחיר לסטופ/טייק, אם אין ATR
    """
    if direction.lower() not in ['long', 'short']:
        raise ValueError("Direction must be 'long' or 'short'")

    try:
        if atr and atr > 0:
            sl_distance = atr * sl_pct
            tp_distance = atr * tp_pct * risk_reward
        else:
            sl_distance = entry_price * 0.0035 * sl_pct  # ברירת מחדל 0.35%
            tp_distance = entry_price * 0.0035 * tp_pct * risk_reward

        if direction.lower() == 'long':
            sl = round(entry_price - sl_distance, 6)
            tp = round(entry_price + tp_distance, 6)
        else:
            sl = round(entry_price + sl_distance, 6)
            tp = round(entry_price - tp_distance, 6)

        return sl, tp
    except Exception as e:
        logging.error(f"[!] שגיאה בחישוב SL/TP: {e}")
        raise

def trailing_stop(
    entry_price: float,
    direction: str,
    atr: float = None,
    trailing_pct: float = 0.5
) -> float:
    """
    מחשב Trailing Stop לפי ATR או אחוז מהמחיר.
    - direction: 'long' או 'short'
    """
    try:
        if atr and atr > 0:
            trailing_distance = atr * trailing_pct
        else:
            trailing_distance = entry_price * 0.003 * trailing_pct  # ברירת מחדל 0.15%

        if direction.lower() == 'long':
            trailing = round(entry_price - trailing_distance, 6)
        else:
            trailing = round(entry_price + trailing_distance, 6)

        return trailing
    except Exception as e:
        logging.error(f"[!] שגיאה בחישוב Trailing Stop: {e}")
        raise

def validate_sl_tp(
    entry_price: float,
    sl: float,
    tp: float,
    direction: str
) -> bool:
    """
    ולידציה ש-SL/TP נכונים ביחס לכניסה וכיוון.
    """
    if direction.lower() == 'long':
        return sl < entry_price < tp
    else:
        return tp < entry_price < sl





