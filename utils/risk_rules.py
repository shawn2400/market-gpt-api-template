# utils/risk_rules.py
from __future__ import annotations

from typing import Dict, Any, Optional, Tuple, List
import os
from utils.watchlist_utils import get_symbol_prefs

ENTRY_GAP_MAX_PCT      = float(os.getenv("ENTRY_GAP_MAX_PCT", "2.5"))  # הרחבתי מ-0.8% ל-2.5%
ENTRY_GAP_WARN_PCT     = float(os.getenv("ENTRY_GAP_WARN_PCT", "1.5"))  # הרחבתי מ-0.5% ל-1.5%

RR_MIN_LOW_VOL         = float(os.getenv("RR_MIN_LOW_VOL",  "1.01"))
RR_MIN_MID_VOL         = float(os.getenv("RR_MIN_MID_VOL",  "1.01"))
RR_MIN_HIGH_VOL        = float(os.getenv("RR_MIN_HIGH_VOL", "1.01"))

LEV_HARD_CAP           = int(os.getenv("LEV_HARD_CAP", "50"))
SUCCESS_WARN_PCT       = float(os.getenv("SUCCESS_WARN_PCT", "60"))

MIN_ABS_RISK_BPS_DEF   = float(os.getenv("MIN_ABS_RISK_BPS",   "0"))
MIN_ABS_REWARD_BPS_DEF = float(os.getenv("MIN_ABS_REWARD_BPS", "0"))


def rr_from_levels(entry: float, sl: float, tp1: float) -> Optional[float]:
    try:
        entry = float(entry); sl = float(sl); tp1 = float(tp1)
        risk = abs(entry - sl); reward = abs(tp1 - entry)
        if risk <= 0:
            return None
        return reward / risk
    except Exception:
        return None


def entry_gap_ok(price: Optional[float], entry: Optional[float], max_gap_pct: Optional[float] = None) -> bool:
    if price is None or entry is None:
        return False
    try:
        price = float(price); entry = float(entry)
        if price <= 0:
            return False
        thr = float(max_gap_pct if max_gap_pct is not None else ENTRY_GAP_MAX_PCT)
        gap = abs(entry - price) / price * 100.0
        return gap <= thr
    except Exception:
        return False


def _rr_threshold(vol_regime: str, symbol: str) -> float:
    prefs = get_symbol_prefs(symbol) or {}
    base_min = prefs.get("min_rr", None)
    if isinstance(base_min, (int, float)):
        return float(base_min)
    v = (vol_regime or "mid").lower()
    if v.startswith("low"):
        return RR_MIN_LOW_VOL
    if v.startswith("high"):
        return RR_MIN_HIGH_VOL
    return RR_MIN_MID_VOL


def _lev_cap(symbol: str) -> int:
    prefs = get_symbol_prefs(symbol) or {}
    m = prefs.get("max_leverage", None)
    try:
        m = int(m) if m is not None else LEV_HARD_CAP
    except Exception:
        m = LEV_HARD_CAP
    return max(1, int(m))


def _side_ok(side: str) -> bool:
    return (side or "").upper() in ("LONG", "SHORT", "BUY", "SELL")


def _norm_side(side: str) -> str:
    s = (side or "").upper()
    if s == "BUY":
        return "LONG"
    if s == "SELL":
        return "SHORT"
    return s


def _levels_monotonic(side: str, entry: float, sl: float, tp1: float) -> bool:
    side = _norm_side(side)
    if side == "LONG":
        return sl < entry < tp1
    return sl > entry > tp1


def _bps_from_entry(a: float, b: float) -> float:
    try:
        a = float(a); b = float(b)
        if a <= 0:
            return 0.0
        return abs(b - a) / a * 10000.0
    except Exception:
        return 0.0


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
    min_rr_override: Optional[float] = None,
) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []

    if not _side_ok(side):
        errors.append("invalid side")
        return {"ok": False, "errors": errors, "warnings": warnings}

    side_n = _norm_side(side)

    if entry is None or sl is None or tp1 is None:
        errors.append("missing required levels (entry/sl/tp1)")
        return {"ok": False, "errors": errors, "warnings": warnings}

    try:
        e = float(entry); s = float(sl); t1 = float(tp1)
    except Exception:
        errors.append("bad numeric levels")
        return {"ok": False, "errors": errors, "warnings": warnings}

    if not _levels_monotonic(side_n, e, s, t1):
        errors.append("levels order invalid for side")
        return {"ok": False, "errors": errors, "warnings": warnings}

    gap_pct = None
    if price is None:
        warnings.append("missing current price; skip entry gap check")
    else:
        try:
            mk = float(price)
            gap_pct = abs(e - mk) / max(mk, 1e-9) * 100.0
            max_gap = ENTRY_GAP_MAX_PCT
            prefs = get_symbol_prefs(symbol) or {}
            if isinstance(prefs.get("entry_gap_max_pct"), (int, float)):
                max_gap = float(prefs["entry_gap_max_pct"])
            if gap_pct > max_gap:
                errors.append(f"entry too far from price (> {max_gap:.2f}%)")
            elif gap_pct > ENTRY_GAP_WARN_PCT:
                warnings.append(f"entry somewhat far from price (~{gap_pct:.2f}%)")
        except Exception:
            warnings.append("entry gap check failed")

    rr = rr_from_levels(e, s, t1)
    if rr is None:
        errors.append("rr can't be computed")
    else:
        rr_min = float(min_rr_override) if isinstance(min_rr_override, (int, float)) else _rr_threshold(vol_regime, symbol)
        if rr < rr_min:
            errors.append(f"rr too low: {rr:.2f} < {rr_min:.2f}")

    prefs = get_symbol_prefs(symbol) or {}
    
    # Safely coerce min_abs_risk_bps and min_abs_reward_bps to float, handling None
    try:
        risk_val = prefs.get("min_abs_risk_bps", MIN_ABS_RISK_BPS_DEF)
        min_risk_bps = float(risk_val) if risk_val is not None else 0.0
    except (TypeError, ValueError):
        min_risk_bps = 0.0
    
    try:
        reward_val = prefs.get("min_abs_reward_bps", MIN_ABS_REWARD_BPS_DEF)
        min_reward_bps = float(reward_val) if reward_val is not None else 0.0
    except (TypeError, ValueError):
        min_reward_bps = 0.0
    
    if min_risk_bps > 0:
        risk_bps = _bps_from_entry(e, s)
        if risk_bps < min_risk_bps:
            errors.append(f"risk too tight (< {min_risk_bps:.0f}bps)")
    if min_reward_bps > 0:
        reward_bps = _bps_from_entry(e, t1)
        if reward_bps < min_reward_bps:
            errors.append(f"reward too tight (< {min_reward_bps:.0f}bps)")

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

    return {
        "ok": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "metrics": {
            "gap_pct": gap_pct,
            "rr": rr,
            "min_rr": (float(min_rr_override) if isinstance(min_rr_override, (int, float)) else _rr_threshold(vol_regime, symbol)),
            "min_abs_risk_bps": min_risk_bps,
            "min_abs_reward_bps": min_reward_bps,
        }
    }



