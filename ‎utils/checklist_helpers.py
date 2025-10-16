# utils/checklist_helpers.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Any, Dict, List, Tuple, Optional
import os
import logging

from utils.pretrade_checklist import compute_pretrade_score

log = logging.getLogger("algogpt.checklist")

def _f(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default

ENTRY_SCORE_MIN = _f("ENTRY_SCORE_MIN", 0.0)

def eval_checklist(klines: List[List[Any]], *, adx: float = 22.0, atr_pct: float = 0.8) -> Dict[str, Any]:
    """
    מקבל klines בפורמט Binance (חייב לפחות close בעמדה [4]).
    מחזיר {"score": float, "features": {...}}
    """
    try:
        res = compute_pretrade_score(klines, adx=adx, atr_pct=atr_pct)
        return {"score": float(res.get("score", 0.0)), "features": res.get("features", {})}
    except Exception as e:
        log.debug("eval_checklist.failed: %s", e)
        return {"score": 0.0, "features": {}}

def gate_allowed(score: float) -> Tuple[bool, float]:
    """
    Gate בסיסי. אם ENTRY_SCORE_MIN<=0 – תמיד OK.
    """
    thr = ENTRY_SCORE_MIN
    if thr <= 0:
        return True, thr
    try:
        s = float(score)
    except Exception:
        s = 0.0
    return (s >= thr), thr
