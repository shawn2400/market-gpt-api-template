# utils/risk.py
from __future__ import annotations
from typing import Any, Dict, Optional
import math

try:
    from utils import config
except Exception:
    class _C:
        RISK_PER_TRADE_PCT = 1.0
        MAX_LEVERAGE = 35
        MAX_TRADE_BUDGET = 100.0
    config = _C()

def suggest_risk(
    symbol: str,
    side: str,
    entry: float,
    sl: float,
    tp: Optional[float] = None,
    atr: Optional[float] = None,
    equity_usdt: Optional[float] = None,
    confidence: Optional[float] = None,
    max_budget_usdt: Optional[float] = None,
    max_leverage: Optional[int] = None,
) -> Dict[str, Any]:
    """
    מחזיר הצעה ל- leverage/budget/qty תחת מגבלות ריסק.
    """
    if entry <= 0 or sl <= 0:
        raise ValueError("entry/sl must be > 0")

    risk_pct = float(getattr(config, "RISK_PER_TRADE_PCT", 1.0))
    max_lev = int(max_leverage or getattr(config, "MAX_LEVERAGE", 35))
    budget_cap = float(max_budget_usdt or getattr(config, "MAX_TRADE_BUDGET", 100.0))

    # כמה כסף מסכנים בטרייד (באחוז מההון או מתקרת התקציב אם equity לא ניתן)
    base_amount = equity_usdt if equity_usdt and equity_usdt > 0 else budget_cap
    risk_usd = base_amount * (risk_pct / 100.0)

    dist = abs(entry - sl)
    if dist <= 0:
        raise ValueError("entry/sl distance must be > 0")

    # גודל פוזיציה כך שהפסד עד SL ~ risk_usd
    qty = risk_usd / dist
    notion = qty * entry

    # לא לעבור תקרת תקציב
    if notion > budget_cap:
        scale = budget_cap / max(notion, 1e-9)
        qty *= scale
        notion = qty * entry

    # מינוף מומלץ (קירוב סביר)
    lev = max(1, math.floor(notion / max(risk_usd, 1e-9)))
    lev = min(lev, max_lev)

    rr = None
    if tp and tp > 0:
        reward = abs(tp - entry) * qty
        rr = reward / max(risk_usd, 1e-9)

    suggested = {
        "symbol": symbol,
        "side": side.upper(),
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "leverage": lev,
        "budget_usdt": round(notion, 2),
        "qty": float(qty),
        "risk_usd": round(risk_usd, 2),
        "rr": rr,
    }
    return {
        "ok": True,
        "suggested": suggested,
        "inputs": {
            "equity_usdt": equity_usdt,
            "risk_pct": risk_pct,
            "max_budget_usdt": budget_cap,
            "max_leverage": max_lev,
            "confidence": confidence,
            "atr": atr,
        },
    }

