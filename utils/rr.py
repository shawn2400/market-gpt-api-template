# utils/rr.py
from __future__ import annotations
from typing import Optional

def rr_now(side: str, entry: float, sl: float, tp: float, current: float) -> Optional[float]:
    """
    RR מיידי: (current-entry) / (entry-sl) ל-BUY, או (entry-current)/(sl-entry) ל-SELL.
    מחזיר None אם הקלט לא סביר.
    """
    try:
        s = side.upper()
        entry = float(entry); sl = float(sl); tp = float(tp); current = float(current)
        if entry <= 0 or tp <= 0 or sl <= 0 or current <= 0:
            return None
        if s == "BUY":
            denom = max(1e-12, entry - sl)
            return (current - entry) / denom
        elif s == "SELL":
            denom = max(1e-12, sl - entry)
            return (entry - current) / denom
        else:
            return None
    except Exception:
        return None
