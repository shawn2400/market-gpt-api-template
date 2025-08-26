# utils/grid_builder.py
from __future__ import annotations
from typing import Dict, Any, Optional
import os

# פרמטרים בסיסיים לפי משטר תנודתיות
GRID_LEVELS_LOW  = int(os.getenv("GRID_LEVELS_LOW","8"))
GRID_LEVELS_MID  = int(os.getenv("GRID_LEVELS_MID","6"))
GRID_LEVELS_HIGH = int(os.getenv("GRID_LEVELS_HIGH","4"))

STEP_PCT_LOW  = float(os.getenv("GRID_STEP_PCT_LOW","0.50"))   # %
STEP_PCT_MID  = float(os.getenv("GRID_STEP_PCT_MID","0.80"))
STEP_PCT_HIGH = float(os.getenv("GRID_STEP_PCT_HIGH","1.20"))

TP_PER_FILL_PCT = float(os.getenv("GRID_TP_PER_FILL_PCT","0.35"))  # יעד קטן לכל מילוי
RANGE_MULT = float(os.getenv("GRID_RANGE_MULT","1.05"))            # טווח סביב המחיר

def _pick_by_vol(vol_regime: str) -> (int, float):
    v = (vol_regime or "mid").lower()
    if v == "low":
        return GRID_LEVELS_LOW, STEP_PCT_LOW
    if v == "high":
        return GRID_LEVELS_HIGH, STEP_PCT_HIGH
    return GRID_LEVELS_MID, STEP_PCT_MID

def build_grid_plan(*, symbol: str, price: Optional[float], flags: Dict[str, Any], budget_usd: float) -> Optional[Dict[str, Any]]:
    if not price or price <= 0:
        return None
    vol = (flags or {}).get("vol_regime","mid").lower()
    trending_up = (flags or {}).get("trending_up", False)
    trending_dn = (flags or {}).get("trending_down", False)
    chop = (flags or {}).get("danger_chop", False)

    # עדיף גריד כשאין טרנד ברור או כשיש chop; אם טרנד חזק — לא נקים גריד
    if trending_up or trending_dn:
        return None

    levels, step_pct = _pick_by_vol(vol)
    half_range_pct = step_pct * (levels - 1) / 100.0 * RANGE_MULT
    gmin = price * (1.0 - half_range_pct)
    gmax = price * (1.0 + half_range_pct)

    return {
        "symbol": symbol,
        "grid_min": gmin,
        "grid_max": gmax,
        "grid_levels": levels,
        "grid_step_pct": step_pct,
        "grid_take_profit_pct": TP_PER_FILL_PCT,
        "grid_side": "LONG",  # ברירת מחדל: קנייה נמוכה/מכירה גבוהה
        "reason": f"grid by vol={vol}, levels={levels}, step={step_pct:.2f}%, chop={chop}",
    }
