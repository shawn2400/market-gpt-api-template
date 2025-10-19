# utils/quantity_utils.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Dict, Any

def round_step(value: float, step: float) -> float:
    """
    עיגול ערך לפי stepSize (LOT_SIZE) של הסימבול.
    שומר יציבות נקודת ציפה ועוקף שגיאות קירוב.
    """
    if not step:
        return float(value)
    v = float(value)
    s = float(step)
    n = round(v / s)
    return round(n * s, 12)

# ---- get_precision_info shim (נסגר אזהרת import בלוג) -----------------------
try:
    from utils.precision_utils import get_precision_info as _get_precision_info  # type: ignore
except Exception:
    _get_precision_info = None  # type: ignore

def get_precision_info(symbol: str) -> Dict[str, Any]:
    """
    מחזיר דיוק/מינונים למסחר. אם קיים מודול מדויק — ישתמש בו.
    אחרת יחזיר ערכי דיפולט שמרניים.
    """
    if _get_precision_info is not None:
        return _get_precision_info(symbol)
    return {
        "symbol": symbol.upper(),
        "price_precision": 2,
        "quantity_precision": 3,
        "min_qty": 0.001,
        "min_notional": 5.0,
        "step_size": 0.001,
        "tick_size": 0.01,
    }

__all__ = ["round_step", "get_precision_info"]














