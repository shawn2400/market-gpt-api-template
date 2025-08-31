# utils/risk_rules.py
from __future__ import annotations
import os
from typing import Dict, Any, Optional

# --------- ENV thresholds (override via .env) ---------
RR_MIN_LOW  = float(os.getenv("RR_MIN_LOW",  "1.50"))
RR_MIN_MID  = float(os.getenv("RR_MIN_MID",  "1.60"))
RR_MIN_HIGH = float(os.getenv("RR_MIN_HIGH", "1.80"))

LEV_MAX_LOW  = int(os.getenv("LEV_MAX_LOW",  "25"))
LEV_MAX_MID  = int(os.getenv("LEV_MAX_MID",  "20"))
LEV_MAX_HIGH = int(os.getenv("LEV_MAX_HIGH", "15"))

ENTRY_GAP_MAX_PCT = float(os.getenv("ENTRY_GAP_MAX_PCT", "1.50"))  # מרחק מקסימלי מהמחיר (%)
MIN_STOP_PCT      = float(os.getenv("MIN_STOP_PCT", "0.05"))       # 0.05% מגודל המחיר – כדי להימנע מ־risk=0

def _f(x) -> Optional[float]:
    try:
        v = float(x)
        if v == v:
            return v
    except Exception:
        pass
    return None

def rr_from_levels(entry: float, sl: float, tp1: float) -> Optional[float]:
    """ מחשב RR בסיסי בין entry-sl ל־tp1-entry """
    e = _f(entry); s = _f(sl); t = _f(tp1)
    if e is None or s is None or t is None:
        return None
    risk = abs(e - s)
    reward = abs(t - e)
    if risk <= 0:
        return None
    return reward / risk

def entry_gap_ok(current_price: float, entry: float, *, max_gap_pct: float = None) -> bool:
    """ אל תרדוף – מרחק כניסה מהמחיר לא יחרוג מהסף. """
    cp = _f(current_price); e = _f(entry)
    if cp is None or e is None or cp <= 0:
        return False
    mx = float(max_gap_pct if max_gap_pct is not None else ENTRY_GAP_MAX_PCT)
    gap = abs(e - cp) / cp * 100.0
    return gap <= mx

def _min_rr_for_vol(vol_regime: str) -> float:
    v = (vol_regime or "mid").lower()
    if v.startswith("low"):
        return RR_MIN_LOW
    if v.startswith("high"):
        return RR_MIN_HIGH
    return RR_MIN_MID

def _max_lev_for_vol(vol_regime: str) -> int:
    v = (vol_regime or "mid").lower()
    if v.startswith("low"):
        return LEV_MAX_LOW
    if v.startswith("high"):
        return LEV_MAX_HIGH
    return LEV_MAX_MID

def gate_trade(
    symbol: str,
    side: str,
    current_price: float,
    entry: float,
    sl: float,
    tp1: float,
    *,
    vol_regime: str = "mid",
    success_pct: Optional[float] = None,
    leverage: Optional[int] = None,
) -> Dict[str, Any]:
    """
    ולידציה קשיחה/רכה להצעת טרייד:
      - חוקי כיוונים (SL/TP ביחס ל־entry)
      - RR מזערי לפי vol_regime
      - מינוף מירבי לפי vol_regime
      - entry לא רחוק מדי מהמחיר
    """
    errors: list[str] = []
    warns: list[str]  = []

    s = (side or "").upper()
    e = _f(entry); sL = _f(sl); t1 = _f(tp1); cp = _f(current_price)
    if s not in ("LONG","SHORT"):
        errors.append("invalid side")
        return {"ok": False, "errors": errors, "warnings": warns}

    if e is None or sL is None or t1 is None:
        errors.append("missing numeric fields: entry/sl/tp1")
        return {"ok": False, "errors": errors, "warnings": warns}

    if cp is not None and not entry_gap_ok(cp, e):
        warns.append("entry far from current price")

    # מינימום מרחק סטופ (מונע risk=0)
    if cp:
        min_stop = abs(cp) * (MIN_STOP_PCT / 100.0)
        if abs(e - sL) < min_stop:
            errors.append(f"stop too tight (<{MIN_STOP_PCT:.3f}% of price)")

    # בדיקת הגיון SL/TP לפי צד
    if s == "LONG":
        if sL >= e:
            errors.append("SL must be below entry for LONG")
        if t1 <= e:
            errors.append("TP1 must be above entry for LONG")
    else:
        if sL <= e:
            errors.append("SL must be above entry for SHORT")
        if t1 >= e:
            errors.append("TP1 must be below entry for SHORT")

    # RR מזערי
    rr = rr_from_levels(e, sL, t1)
    min_rr = _min_rr_for_vol(vol_regime)
    if rr is None:
        errors.append("invalid RR")
    elif rr < min_rr:
        errors.append(f"RR too low (<{min_rr:.2f})")

    # מינוף מירבי
    if leverage is not None:
        lev = int(leverage)
        max_lev = _max_lev_for_vol(vol_regime)
        if lev < 1 or lev > max_lev:
            errors.append(f"leverage out of bounds for {vol_regime} (<= {max_lev}x)")

    # הערת הצלחה – אזהרה בלבד (הסף הקשיח מטופל חיצונית ע״י ה־worker)
    if success_pct is not None and (success_pct < 0 or success_pct > 100):
        warns.append("success_pct should be within 0..100")

    return {"ok": len(errors) == 0, "errors": errors, "warnings": warns}

