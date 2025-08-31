# utils/grid_builder.py
from __future__ import annotations
from typing import Dict, Any, Optional, Tuple
import os

# פרמטרי גריד לפי משטר תנודתיות (ניתנים לשינוי ב־ENV)
GRID_LEVELS_LOW  = int(os.getenv("GRID_LEVELS_LOW",  "8"))
GRID_LEVELS_MID  = int(os.getenv("GRID_LEVELS_MID",  "6"))
GRID_LEVELS_HIGH = int(os.getenv("GRID_LEVELS_HIGH", "4"))

STEP_PCT_LOW  = float(os.getenv("GRID_STEP_PCT_LOW",  "0.50"))  # אחוז בין קווים
STEP_PCT_MID  = float(os.getenv("GRID_STEP_PCT_MID",  "0.80"))
STEP_PCT_HIGH = float(os.getenv("GRID_STEP_PCT_HIGH", "1.20"))

TP_PER_FILL_PCT = float(os.getenv("GRID_TP_PER_FILL_PCT", "0.35"))  # יעד חלקי לכל מילוי
RANGE_MULT      = float(os.getenv("GRID_RANGE_MULT",       "1.05"))  # כדי להרחיב מעט את הטווח מדדית

def _pick_by_vol(vol_regime: str) -> Tuple[int, float]:
    v = (vol_regime or "mid").lower()
    if v.startswith("low"):
        return GRID_LEVELS_LOW, STEP_PCT_LOW
    if v.startswith("high"):
        return GRID_LEVELS_HIGH, STEP_PCT_HIGH
    return GRID_LEVELS_MID, STEP_PCT_MID

def build_grid_plan(
    *,
    symbol: str,
    price: Optional[float],
    flags: Dict[str, Any],
    budget_usd: float
) -> Optional[Dict[str, Any]]:
    """
    בונה תוכנית גריד בסיסית סביב המחיר:
      - מתאים יותר כשאין טרנד ברור / chop (לא יפתח בטרנד חזק).
      - צד ברירת מחדל: LONG (קנייה נמוך/מכירה גבוה).
    """
    if not price or price <= 0:
        return None

    vol = (flags or {}).get("vol_regime", "mid").lower()
    trending_up = bool((flags or {}).get("trending_up", False))
    trending_dn = bool((flags or {}).get("trending_down", False))
    chop        = bool((flags or {}).get("danger_chop", False))

    # אם יש טרנד חזק — לא נקים גריד (נמנע ממלכודות)
    if trending_up or trending_dn:
        return None

    levels, step_pct = _pick_by_vol(vol)
    # חישוב טווח סימטרי סביב המחיר
    half_range_pct = (step_pct * (levels - 1)) / 100.0 * RANGE_MULT
    gmin = price * (1.0 - half_range_pct)
    gmax = price * (1.0 + half_range_pct)

    return {
        "symbol": symbol.upper(),
        "grid_min": float(gmin),
        "grid_max": float(gmax),
        "grid_levels": int(levels),
        "grid_step_pct": float(step_pct),
        "grid_take_profit_pct": float(TP_PER_FILL_PCT),
        "grid_side": "LONG",
        "reason": f"grid by vol={vol}, levels={levels}, step={step_pct:.2f}%, chop={chop}",
        "budget_usd": float(budget_usd),
    }

   
