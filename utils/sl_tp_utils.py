# utils/sl_tp_utils.py
from typing import Tuple, Optional

MIN_PCT_FLOOR = 0.003   # 0.3% מינימום מרחק ל-SL
TP_PCT_FLOOR  = 0.006   # 0.6% מינימום מרחק ל-TP
ATR_SL_MULT   = 1.5
ATR_TP_MULT   = 2.5

def _to_float(x, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return float(default)

def calculate_sl_tp(entry_price: float, direction: str, atr: Optional[float] = None) -> Tuple[float, float]:
    """
    חישוב SL/TP דטרמיניסטי:
      - עם ATR: SL=ATR*1.5, TP=ATR*2.5
      - בלי ATR: רצפה באחוזים (0.3% / 0.6%)
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

    # בטיחות
    if d == "LONG" and not (sl < entry < tp):
        if sl >= entry: sl = entry * (1 - MIN_PCT_FLOOR)
        if tp <= entry: tp = entry * (1 + TP_PCT_FLOOR)
    if d == "SHORT" and not (tp < entry < sl):
        if sl <= entry: sl = entry * (1 + MIN_PCT_FLOOR)
        if tp >= entry: tp = entry * (1 - TP_PCT_FLOOR)

    return (round(float(sl), 6), round(float(tp), 6))



       






