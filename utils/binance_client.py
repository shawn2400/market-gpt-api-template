# routes/risk.py
from __future__ import annotations
from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException, Body

try:
    from utils.auth import require_bearer_token
except Exception:
    async def require_bearer_token():
        raise HTTPException(status_code=401, detail="Unauthorized")

router = APIRouter(prefix="/risk", tags=["Risk"], dependencies=[Depends(require_bearer_token)])

def _fallback_suggest_risk(**payload) -> Dict[str, Any]:
    """
    Fallback פשוט כאשר utils.risk לא קיים.
    לוגיקה: תקציב = min(max_budget_usdt, equity*RISK%); מינוף <= max_leverage;
    כמות = budget * leverage / entry.
    """
    import os
    sym = str(payload.get("symbol", ""))
    side = str(payload.get("side", "")).upper()
    entry = float(payload.get("entry", 0) or 0)
    sl    = float(payload.get("sl", 0) or 0)
    tp    = payload.get("tp")

    equity   = float(payload.get("equity_usdt") or 0.0)
    max_bu   = float(payload.get("max_budget_usdt") or float(os.getenv("MAX_TRADE_BUDGET", "100")))
    max_lev  = int(payload.get("max_leverage") or int(os.getenv("MAX_LEVERAGE", "35")))
    risk_pct = float(os.getenv("RISK_PER_TRADE_PCT", "1.0"))

    if not sym or side not in ("LONG", "SHORT") or entry <= 0 or sl <= 0:
        return {"ok": False, "suggested": {}, "inputs": payload, "note": "invalid inputs"}

    # תקציב מוצע
    budget_risk = equity * (risk_pct / 100.0) if equity > 0 else max_bu
    budget = min(max_bu, budget_risk) if budget_risk > 0 else max_bu
    budget = max(5.0, float(budget))  # רצפה קטנה

    leverage = max(1, min(max_lev, 20))
    qty = (budget * leverage) / entry

    suggested = {
        "symbol": sym,
        "side": side,
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "budget_usdt": round(budget, 2),
        "leverage": leverage,
        "quantity": round(qty, 6),
    }
    return {"ok": True, "suggested": suggested, "inputs": payload, "constraints": None, "note": "fallback-risk"}

@router.post("/suggest", summary="Suggest budget/leverage/qty from risk engine", operation_id="postRiskSuggest")
async def post_risk_suggest(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    try:
        from utils.risk import suggest_risk  # type: ignore
        result = suggest_risk(**payload)  # type: ignore
        if not isinstance(result, dict):
            return {"ok": False, "suggested": {}, "inputs": payload, "note": "invalid risk output"}
        result.setdefault("ok", True)
        return result
    except Exception:
        # אין מודול risk → fallback
        return _fallback_suggest_risk(**payload)





























