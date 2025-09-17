from __future__ import annotations
import time
from typing import Any, Dict
from fastapi import APIRouter, Depends, Query, HTTPException
from utils.auth import require_api_key

router = APIRouter(prefix="/executor", tags=["executor"])

@router.get("/status")
def executor_status() -> Dict[str, Any]:
    return {"ok": True, "status": "running", "ts": int(time.time() * 1000)}

@router.get("/positions")
def get_positions(_: str = Depends(require_api_key)) -> Dict[str, Any]:
    return {"ok": True, "positions": []}

@router.get("/balance")
def get_balance(_: str = Depends(require_api_key)) -> Dict[str, Any]:
    return {"ok": True, "balances": []}

@router.post("/trade")
def trade(
    symbol: str = Query(..., min_length=1, max_length=32),
    side: str = Query(..., pattern=r"^(?i)(BUY|SELL)$"),
    budget: float = Query(0.0, ge=0.0, description="Notional budget in quote currency"),
    leverage: int = Query(1, ge=1, le=125),
    dry_run: bool = Query(True),
    _token: str = Depends(require_api_key),
) -> Dict[str, Any]:
    side_up = side.upper()
    if side_up not in ("BUY", "SELL"):
        raise HTTPException(status_code=400, detail="side must be BUY or SELL")
    result = {
        "ok": True,
        "symbol": symbol.upper(),
        "side": side_up,
        "leverage": leverage,
        "base_price": 0.0,
        "dry_run": dry_run,
        "entry_policy": "MARKET_ESCALATION",
        "gate": {"enter_ok": True, "score": 0.0, "reasons": [], "metrics": {}},
        "risk": {"ok": True, "score": 100.0, "reasons": [], "metrics": {},
                 "symbol": symbol.upper(), "side": side_up, "lev": leverage},
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















