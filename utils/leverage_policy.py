# utils/leverage_policy.py
from __future__ import annotations
import os
from typing import Optional

_DEGRADE_CAP = int(os.getenv("OPS_DEGRADE_MAX_LEVERAGE", "12"))
_ADX_SAFETY_CAP = int(os.getenv("OPS_ADX_SAFETY_MAX_LEVERAGE", "15"))
_ADX_CUTOFFS = tuple(int(x) for x in os.getenv("OPS_ADX_LEVERAGE_CUTOFFS", "20,25,30").split(",") if x.strip().isdigit())

def _cap_by_adx(adx: float, lev: int) -> int:
    """מגביל מינוף לפי ADX כדי לא להיות אגרסיבי כשאין מומנטום חזק מספיק."""
    if not isinstance(adx, (int, float)):
        return lev
    capped = lev
    if adx < _ADX_CUTOFFS[0]:
        capped = min(capped, max(7, _ADX_SAFETY_CAP - 6))
    elif adx < _ADX_CUTOFFS[1]:
        capped = min(capped, max(9, _ADX_SAFETY_CAP - 4))
    elif adx < _ADX_CUTOFFS[2]:
        capped = min(capped, max(12, _ADX_SAFETY_CAP - 2))
    else:
        capped = min(capped, _ADX_SAFETY_CAP)
    return int(max(1, capped))

def adjust_leverage(adx: float, proposed_leverage: int) -> int:
    """
    מחזיר מינוף לאחר מדיניות:
    1) אם מצב Degrade פעיל → cap ל־OPS_DEGRADE_MAX_LEVERAGE (ברירת מחדל 12).
    2) בכל מקרה → מגביל לפי ADX (OPS_ADX_SAFETY_MAX_LEVERAGE).
    """
    try:
        from utils import runtime_counters as rc
        degraded = bool(rc.ops_is_degraded())
    except Exception:
        degraded = False

    lev = int(proposed_leverage)
    if degraded:
        lev = min(lev, _DEGRADE_CAP)

    lev = _cap_by_adx(float(adx or 0.0), lev)
    return int(max(1, lev))
