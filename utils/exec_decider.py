# utils/exec_decider.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Dict, Any, Optional
import os

# שליטה בסיסית דרך ENV
def _envf(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default

def _envi(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default

def _envb(name: str, default: bool) -> bool:
    return (os.getenv(name, "1" if default else "0").lower() in ("1","true","yes","on"))

def decide_execution_mode(
    ticket: Dict[str, Any],
    indicators: Dict[str, float],
    *,
    slip_estimate_bps: Optional[float] = None,
    spread_pct: Optional[float] = None,
) -> Dict[str, Any]:
    """
    מחזיר:
      { "mode": "MARKET"|"HYBRID",
        "reason": "<text>",
        "hints": { ... } }

    לוגיקה רזה (ברירת מחדל, בטוחה):
      - אם אומדן סליפאג' <= IMPACT_SLIP_BPS_MAX  → HYBRID (armed) מועדף
      - אם Spread/ATR% חריגים → MARKET (פחות חכמות בפתיחה)
      - אם QUOTE קטן מאוד (notional < MIN_NOTIONAL_USDT) → MARKET
    """
    adx = float(indicators.get("adx", 0.0) or 0.0)
    atr_pct = float(indicators.get("atr_pct", 0.0) or 0.0)  # צפוי באחוזים (e.g. 0.8 => 0.8%)
    px = float(indicators.get("price", 0.0) or 0.0)
    notional = float(indicators.get("notional", 0.0) or 0.0)

    # קונטרולרים מהסביבה
    slip_cap_bps = _envf("IMPACT_SLIP_BPS_MAX", 25.0)
    atr_soft_cap = _envf("VOLATILITY_GATE_ATRPCT", 1.2)        # % ATR שבו נעדיף פחות “תחכום”
    spread_soft  = _envf("SPREAD_SOFT_PCT", 0.05)               # 0.05% ברירת מחדל
    min_notional = _envf("MIN_NOTIONAL_USDT", 25.0)
    prefer_hybrid_default = _envb("PREFER_HYBRID_DEFAULT", True)

    s_bps = float(slip_estimate_bps or 1e9)
    sp = float(spread_pct or 0.0)

    # חיתוך ראשוני: נוטיונל קטן מאוד → MARKET
    if notional > 0 and notional < min_notional:
        return {"mode": "MARKET", "reason": f"small_notional<{min_notional}", "hints": {"notional": notional}}

    # רגישות וולאטיליות/ספרד
    if atr_pct >= atr_soft_cap or sp >= spread_soft:
        # אם סליפ אומדן נמוך מאוד אפשר עדיין להישאר HYBRID, אחרת MARKET
        if s_bps <= min(slip_cap_bps, 12.0):
            return {"mode": "HYBRID", "reason": "high_vol_or_spread_but_low_slip_est", "hints": {"atr_pct": atr_pct, "spread_pct": sp, "slip_bps": s_bps}}
        return {"mode": "MARKET", "reason": "high_vol_or_spread", "hints": {"atr_pct": atr_pct, "spread_pct": sp}}

    # החלטה לפי סליפאג'
    if s_bps <= slip_cap_bps:
        return {"mode": "HYBRID", "reason": "slip_est_under_cap", "hints": {"slip_bps": s_bps, "cap": slip_cap_bps}}

    # דיפולט
    return {"mode": ("HYBRID" if prefer_hybrid_default else "MARKET"),
            "reason": "default_pref",
            "hints": {"slip_bps": s_bps, "cap": slip_cap_bps, "adx": adx, "atr_pct": atr_pct, "price": px}}
