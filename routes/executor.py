# /app/routes/executor.py
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, HTTPException

from utils.auth import require_api_key

router = APIRouter(prefix="/executor", tags=["executor"])


# ---------- Public: health / status ----------

@router.get("/status")
def executor_status() -> Dict[str, Any]:
    """Public liveness endpoint (מוגדר כ-public ב-SECURITY_PUBLIC_PATHS)."""
    return {
        "ok": True,
        "status": "running",
        "ts": int(time.time() * 1000),
    }


# ---------- Protected endpoints (need API key) ----------

@router.get("/positions")
def get_positions(_: str = Depends(require_api_key)) -> Dict[str, Any]:
    """
    Return current positions list.
    NOTE: לוגיקה אמיתית של ברוקר/בורסה צריכה להיות כאן. כרגע מחזיר ריק.
    """
    return {"ok": True, "positions": []}


@router.get("/balance")
def get_balance(_: str = Depends(require_api_key)) -> Dict[str, Any]:
    """
    Return wallet / margin balances.
    NOTE: החלף בלוגיקה האמיתית שלכם.
    """
    return {"ok": True, "balances": []}


@router.post("/trade")
def trade(
    symbol: str = Query(..., min_length=1, max_length=32),
    side: str = Query(..., regex=r"^(?i)(BUY|SELL)$"),
    budget: float = Query(0.0, ge=0.0, description="Notional budget in quote currency"),
    leverage: int = Query(1, ge=1, le=125),
    dry_run: bool = Query(True),
    _token: str = Depends(require_api_key),
) -> Dict[str, Any]:
    """
    Place (or simulate) an order.
    NOTE: זהו מימוש דמה לשמירה על API יציב. החלף למימוש המסחר האמיתי.
    """
    side_up = side.upper()
    if side_up not in ("BUY", "SELL"):
        raise HTTPException(status_code=400, detail="side must be BUY or SELL")

    base_price = 0.0  # אפשר להביא ממנוע המחירים הפנימי /price/<symbol>
    result = {
        "ok": True,
        "symbol": symbol,
        "side": side_up,
        "leverage": leverage,
        "base_price": base_price,
        "dry_run": dry_run,
        "entry_policy": "MARKET_ESCALATION",
        "gate": {"enter_ok": True, "score": 0.0, "reasons": [], "metrics": {}},
        "risk": {"ok": True, "score": 100.0, "reasons": [], "metrics": {}, "symbol": symbol, "side": side_up, "lev": leverage},
        "alloc_ok": True,
        "alloc_error": None,
        "guards": {"percent_price_bps": 0.0, "slippage_guard_bps": 80.0},
        "position_side": "BOTH",
        "reduce_only": False,
        "budget_used": float(budget),
        "quality": 0.0,
        "adx": 0.0,
        "qty": 0.0,
        "tp_orders": [],
        "sl_orders": [],
        "entry_simulation": {"allow_market_entry": True},
    }
    return {"ok": True, "result": result}















