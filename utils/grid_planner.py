# utils/grid_planner.py
from __future__ import annotations
from typing import Dict, Any, List, Optional, Tuple
import os
from math import floor

from utils.grid_builder import (
    GRID_LEVELS_LOW, GRID_LEVELS_MID, GRID_LEVELS_HIGH,
    STEP_PCT_LOW, STEP_PCT_MID, STEP_PCT_HIGH,
    TP_PER_FILL_PCT, RANGE_MULT,
)

def _pick(vol: str) -> Tuple[int, float]:
    v = (vol or "mid").lower()
    if v == "low":  return GRID_LEVELS_LOW,  STEP_PCT_LOW
    if v == "high": return GRID_LEVELS_HIGH, STEP_PCT_HIGH
    return GRID_LEVELS_MID, STEP_PCT_MID

def _progressive_weights(n: int, side: str = "LONG") -> List[float]:
    """
    משקל פרוגרסיבי: ב-LONG משקל גבוה יותר בקומות התחתונות (קנייה נמוכה יותר).
    """
    if n <= 1:
        return [1.0]
    # 1..n
    seq = list(range(1, n + 1))
    if side.upper() == "LONG":
        # שכבות נמוכות → משקל גדול
        seq = list(reversed(seq))
    total = float(sum(seq))
    return [x / total for x in seq]

def _build_lines(price: float, levels: int, step_pct: float) -> List[float]:
    """
    בניית רמות סימטרית סביב המחיר הנוכחי (עם RANGE_MULT).
    """
    half_range_pct = step_pct * (levels - 1) / 100.0 * RANGE_MULT
    gmin = price * (1.0 - half_range_pct)
    gmax = price * (1.0 + half_range_pct)
    if levels <= 1:
        return [price]
    step_abs = (gmax - gmin) / (levels - 1)
    return [gmin + i * step_abs for i in range(levels)]

def plan_grid(*, symbol: str, price: Optional[float], flags: Dict[str, Any] | None,
              budget_usd: float, side: str = "LONG") -> Optional[Dict[str, Any]]:
    """
    מתכנן רשת LONG בלבד (כברירת מחדל). אם יש טרנד חזק — נימנע מגריד.
    """
    if not price or price <= 0:
        return None

    vol = (flags or {}).get("vol_regime", "mid").lower()
    trending_up = bool((flags or {}).get("trending_up", False))
    trending_dn = bool((flags or {}).get("trending_down", False))

    # גריד עדיף בלי טרנד חזק
    if trending_up or trending_dn:
        return None

    levels, step_pct = _pick(vol)
    lines = _build_lines(float(price), levels, step_pct)
    w = _progressive_weights(levels, side=side)
    allocs = [budget_usd * wi for wi in w]

    # עיגון קל לסכום (מניעת שאריות אגורות)
    s = sum(allocs)
    if s > 0:
        factor = budget_usd / s
        allocs = [a * factor for a in allocs]
    # נבצע ראונד ל-2 ספרות אחרי הנק' (USD)
    allocs = [floor(x * 100.0) / 100.0 for x in allocs]
    # תיקון אגורות אחרון
    diff = round(budget_usd - sum(allocs), 2)
    if diff != 0 and allocs:
        allocs[0] = round(allocs[0] + diff, 2)

    return {
        "symbol": symbol.upper(),
        "side": side.upper(),
        "price": float(price),
        "grid_min": float(min(lines)),
        "grid_max": float(max(lines)),
        "grid_levels": int(levels),
        "grid_step_pct": float(step_pct),
        "grid_take_profit_pct": float(TP_PER_FILL_PCT),
        "lines": [float(x) for x in lines],
        "allocations_usd": [float(x) for x in allocs],
        "vol_regime": vol,
        "reason": f"grid plan vol={vol} levels={levels} step={step_pct:.2f}%",
    }

