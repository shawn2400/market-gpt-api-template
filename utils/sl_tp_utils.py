# utils/sl_tp_utils.py
import logging
from typing import Tuple, Optional

MIN_PCT_FLOOR = 0.003   # 0.3% רצפה ל-SL
TP_PCT_FLOOR  = 0.006   # 0.6% רצפה ל-TP
ATR_SL_MULT   = 1.5
ATR_TP_MULT   = 2.5

def _to_float(x, default=0.0) -> float:
    try:
        return float(x)
    except Exception:
        return float(default)

def calculate_sl_tp(entry_price: float, direction: str, atr: Optional[float] = None) -> Tuple[float, float]:
    """
    חישוב SL/TP דטרמיניסטי:
    - אם יש ATR: משתמש ב-ATR*1.5 ל-SL ו-ATR*2.5 ל-TP
    - אחרת: אחוזים רצפה (0.3%/0.6%)
    מחזיר (SL, TP) תמיד.
    """
    entry = _to_float(entry_price)
    if entry <= 0:
        raise ValueError("entry_price must be positive")

    use_atr = _to_float(atr, 0.0) if atr is not None else 0.0
    if use_atr > 0:
        sl_off = max(use_atr * ATR_SL_MULT, entry * MIN_PCT_FLOOR)
        tp_off = max(use_atr * ATR_TP_MULT, entry * TP_PCT_FLOOR)
    else:
        sl_off = entry * MIN_PCT_FLOOR
        tp_off = entry * TP_PCT_FLOOR

    d = (direction or "").upper()
    if d == "LONG":
        sl = entry - sl_off
        tp = entry + tp_off
    else:
        sl = entry + sl_off
        tp = entry - tp_off

    # בטיחות מינימלית (למקרה קלטים חריגים)
    if d == "LONG" and not (sl < entry < tp):
        sl = min(sl, entry * (1 - MIN_PCT_FLOOR))
        tp = max(tp, entry * (1 + TP_PCT_FLOOR))
    if d == "SHORT" and not (tp < entry < sl):
        sl = max(sl, entry * (1 + MIN_PCT_FLOOR))
        tp = min(tp, entry * (1 - TP_PCT_FLOOR))

    return (round(float(sl), 6), round(float(tp), 6))



       






