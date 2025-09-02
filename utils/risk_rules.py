# utils/risk_rules.py
from __future__ import annotations
from typing import Dict, Any, Optional, Tuple
import os

from utils.watchlist_utils import get_symbol_prefs

ENTRY_GAP_MAX_PCT   = float(os.getenv("ENTRY_GAP_MAX_PCT", "0.80"))
ENTRY_GAP_WARN_PCT  = float(os.getenv("ENTRY_GAP_WARN_PCT", "0.50"))
RR_MIN_LOW_VOL      = float(os.getenv("RR_MIN_LOW_VOL",  "1.5"))
RR_MIN_MID_VOL      = float(os.getenv("RR_MIN_MID_VOL",  "1.6"))
RR_MIN_HIGH_VOL     = float(os.getenv("RR_MIN_HIGH_VOL", "1.8"))
LEV_HARD_CAP        = int(os.getenv("LEV_HARD_CAP", "50"))
SUCCESS_WARN_PCT    = float(os.getenv("SUCCESS_WARN_PCT", "60"))

def rr_from_levels(entry: float, sl: float, tp1: float) -> Optional[float]:
    try:
        entry = float(entry); sl = float(sl); tp1 = float(tp1)
        risk = abs(entry - sl); reward = abs(tp1 - entry)
        if risk <= 0: return None
        return reward / risk
    except Exception:
        return None

def entry_gap_ok(price: Optional[float], entry: Optional[float], max_gap_pct: Optional[float] = None) -> bool:
    if price is None or entry is None: return False
    try:
        price = float(price); entry = float(entry)
        if price <= 0: return False
        thr = float(max_gap_pct if max_gap_pct is not None else ENTRY_GAP_MAX_PCT)
        gap = abs(entry - price) / price * 100.0
        return gap <= thr
    except Exception:
        return False

def _rr_threshold(vol_regime: str, symbol: str) -> float:
    prefs = get_symbol_prefs(symbol)
    base_min = prefs.get("min_rr", None)
    if isinstance(base_min, (int, float)): return float(base_min)
    v = (vol_regime or "mid").lower()
    if v.startswith("low"):  return RR_MIN_LOW_VOL
    if v.startswith("high"): return RR_MIN_HIGH_VOL
    return RR_MIN_MID_VOL

def _lev_cap(symbol: str) -> int:
    prefs = get_symbol_prefs(symbol)
    m = prefs.get("max_leverage", None)
    try: m = int(m) if m is not None else LEV_HARD_CAP
    except Exception: m = LEV_HARD_CAP
    return max(1, int(m))

def _side_ok(side: str) -> bool:
    return (side or "").upper() in ("LONG", "SHORT")

def _levels_monotonic(side: str, entry: float, sl: float, tp1: float) -> bool:
    if side.upper() == "LONG": return sl < entry < tp1
    return sl > entry > tp1

def gate_trade(
    symbol: str,
    side: str,
    price: Optional[float],
    entry: Optional[float],
    sl: Optional[float],
    tp1: Optional[float],
    *,
    vol_regime: str = "mid",
    success_pct: Optional[float] = None,
    leverage: Optional[int] = None,
) -> Dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    if not _side_ok(side):
        errors.append("invalid side")
        return {"ok": False, "errors": errors, "warnings": warnings}

    if entry is None or sl is None or tp1 is None:
        errors.append("missing required levels (entry/sl/tp1)")
        return {"ok": False, "errors": errors, "warnings": warnings}

    try:
        e = float(entry); s = float(sl); t1 = float(tp1)
    except Exception:
        errors.append("bad numeric levels")
        return {"ok": False, "errors": errors, "warnings": warnings}

    if not _levels_monotonic(side, e, s, t1):
        errors.append("levels order invalid for side")
        return {"ok": False, "errors": errors, "warnings": warnings}

    if price is None:
        warnings.append("missing current price; skip entry gap check")
    else:
        if not entry_gap_ok(price, e, ENTRY_GAP_MAX_PCT):
            errors.append(f"entry too far from price (> {ENTRY_GAP_MAX_PCT:.2f}%)")
        else:
            gap = abs(e - float(price)) / float(price) * 100.0
            if gap > ENTRY_GAP_WARN_PCT:
                warnings.append(f"entry somewhat far from price (~{gap:.2f}%)")

    rr = rr_from_levels(e, s, t1)
    if rr is None:
        errors.append("rr can't be computed")
    else:
        rr_min = _rr_threshold(vol_regime, symbol)
        if rr < rr_min:
            errors.append(f"rr too low: {rr:.2f} < {rr_min:.2f}")

    if leverage is not None:
        lev_cap = _lev_cap(symbol)
        if leverage > lev_cap:
            errors.append(f"leverage {leverage} exceeds cap {lev_cap}")
        elif leverage > 0.8 * lev_cap:
            warnings.append(f"high leverage near cap (>{0.8*lev_cap:.0f})")
        if leverage > LEV_HARD_CAP:
            errors.append(f"leverage {leverage} exceeds hard cap {LEV_HARD_CAP}")

    if success_pct is not None and success_pct < SUCCESS_WARN_PCT:
        warnings.append(f"low success_pct ~{success_pct:.1f}%")

    return {"ok": len(errors) == 0, "errors": errors, "warnings": warnings}


