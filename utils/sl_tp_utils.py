# utils/sl_tp_utils.py
from typing import Tuple, Optional

# רצפות שמרניות לברירת מחדל (אפשר לכוונן לפי טעם)
MIN_PCT_FLOOR = 0.003   # 0.3% מינימום מרחק ל-SL
TP_PCT_FLOOR  = 0.006   # 0.6% מינימום מרחק ל-TP
ATR_SL_MULT   = 1.5
ATR_TP_MULT   = 2.5

def _to_float(x, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return float(default)

def _normalize_direction(direction: Optional[str]) -> str:
    """
    ממפה ערכי כיוון נפוצים לתקן LONG/SHORT.
    כל מה שלא LONG/BUY יטופל כ-SHORT לשמירה על תאימות אחורה.
    """
    d = (direction or "").strip().upper()
    if d in ("LONG", "BUY"):
        return "LONG"
    return "SHORT"

def calculate_sl_tp(entry_price: float, direction: str, atr: Optional[float] = None) -> Tuple[float, float]:
    """
    חישוב SL/TP דטרמיניסטי:
      - אם קיים ATR חיובי: SL = ATR*1.5, TP = ATR*2.5 (עם רצפת אחוזים).
      - אם אין ATR/לא תקין: משתמשים רק ברצפות אחוזיות (0.3% / 0.6%).
    מחזיר תמיד (SL, TP) כמספרים חיוביים כשהיחסים תקינים עבור הכיוון.
    הערה: העיגול לפי tick/step נעשה בשכבת ה-Binance Trader.
    """
    entry = _to_float(entry_price)
    if entry <= 0:
        raise ValueError("entry_price must be positive")

    dirn = _normalize_direction(direction)

    # ATR חייב להיות חיובי כדי להילקח בחשבון
    atr_val = _to_float(atr, 0.0) if atr is not None else 0.0
    if atr_val > 0:
        sl_off = max(atr_val * ATR_SL_MULT, entry * MIN_PCT_FLOOR)
        tp_off = max(atr_val * ATR_TP_MULT, entry * TP_PCT_FLOOR)
    else:
        sl_off = entry * MIN_PCT_FLOOR
        tp_off = entry * TP_PCT_FLOOR

    if dirn == "LONG":
        sl = entry - sl_off
        tp = entry + tp_off
        # בטיחות: ודא יחס נכון במקרה קצה
        if not (sl < entry < tp):
            if sl >= entry:
                sl = entry * (1 - MIN_PCT_FLOOR)
            if tp <= entry:
                tp = entry * (1 + TP_PCT_FLOOR)
    else:  # SHORT
        sl = entry + sl_off
        tp = entry - tp_off
        if not (tp < entry < sl):
            if sl <= entry:
                sl = entry * (1 + MIN_PCT_FLOOR)
            if tp >= entry:
                tp = entry * (1 - TP_PCT_FLOOR)

    return round(float(sl), 6), round(float(tp), 6)




       






