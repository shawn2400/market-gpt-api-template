# utils/trade_validator.py
from __future__ import annotations
import os
from typing import Dict, Any

def _f(x):
    try: return float(x)
    except Exception: return None

def _clip(v, lo, hi):
    try:
        v = float(v)
        return max(lo, min(hi, v))
    except Exception:
        return lo

_MIN_RR_HARD   = float(os.getenv("VALIDATOR_MIN_RR_HARD", "1.1"))
_MIN_RR_WARN   = float(os.getenv("VALIDATOR_MIN_RR_WARN", "1.5"))
_MAX_LEV_HARD  = int(os.getenv("VALIDATOR_MAX_LEVERAGE", "50"))
_MAX_GAP_PCT   = float(os.getenv("VALIDATOR_MAX_ENTRY_GAP_PCT", "1.5"))  # % מהמחיר הנוכחי
_REQ_SIDE      = os.getenv("VALIDATOR_REQUIRE_SIDE","1").lower() in ("1","true","yes")

async def validate_proposal(p: Dict[str, Any], *, interval: str = "15m", market: str = "futures") -> Dict[str, Any]:
    """
    מחזיר: {"ok": bool, "errors": [..], "warnings": [..]}
    """
    errors, warns = [], []

    side = str(p.get("side") or "").upper()
    entry = _f(p.get("entry"))
    sl    = _f(p.get("sl"))
    tp1   = _f(p.get("tp1"))
    lev   = int(p.get("leverage") or 1)
    cur   = _f(p.get("current_price"))
    sp    = _f(p.get("success_pct"))

    if _REQ_SIDE and side not in ("LONG","SHORT"):
        errors.append("side must be LONG/SHORT")

    if entry is None or sl is None or tp1 is None:
        errors.append("missing numeric: entry/sl/tp1")

    if lev < 1 or lev > _MAX_LEV_HARD:
        errors.append(f"leverage out of bounds (1..{_MAX_LEV_HARD})")

    if sp is not None and not (0.0 <= sp <= 100.0):
        warns.append("success_pct should be in 0..100")

    if not errors and side in ("LONG","SHORT"):
        # יחסי SL/TP
        if side == "LONG":
            if sl >= entry:
                errors.append("SL must be below entry for LONG")
            if tp1 <= entry:
                errors.append("TP1 must be above entry for LONG")
        else:
            if sl <= entry:
                errors.append("SL must be above entry for SHORT")
            if tp1 >= entry:
                errors.append("TP1 must be below entry for SHORT")

        # RR
        if not errors:
            risk = abs(entry - sl)
            reward = abs(tp1 - entry)
            rr = (reward / risk) if (risk and risk > 0) else None
            if rr is None:
                errors.append("invalid RR (risk=0)")
            else:
                if rr < _MIN_RR_HARD:
                    errors.append(f"RR too low (<{_MIN_RR_HARD:.2f})")
                elif rr < _MIN_RR_WARN:
                    warns.append(f"RR suboptimal (<{_MIN_RR_WARN:.2f})")

        # מרחק מהמחיר
        if cur and entry:
            gap_pct = abs(entry - cur) / cur * 100.0
            if gap_pct > _MAX_GAP_PCT:
                warns.append(f"entry far from current ({gap_pct:.2f}% > {_MAX_GAP_PCT:.2f}%)")

    return {"ok": len(errors)==0, "errors": errors, "warnings": warns}

