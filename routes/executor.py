# routes/executor.py
from __future__ import annotations
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
import httpx

from utils.auth import require_api_key
from utils.binance_trade import plan_and_execute
from utils.telegram_notify import send_audit

router = APIRouter(prefix="/executor", tags=["executor"])

@router.get("/status")
def executor_status() -> Dict[str, Any]:
    import time
    return {"ok": True, "status": "running", "ts": int(time.time()*1000)}

@router.post("/trade")
async def trade(
    symbol: str = Query(..., min_length=1, max_length=32),
    side: str = Query(..., pattern=r"(?i)^(BUY|SELL)$"),
    budget: float = Query(..., gt=0.0, description="Budget in USD"),
    leverage: int = Query(..., ge=1, le=125),
    dry_run: bool = Query(False),
    _token: str = Depends(require_api_key),
) -> Dict[str, Any]:
    try:
        res = await plan_and_execute(
            symbol=symbol, side=side, leverage=leverage, budget_usd=float(budget),
            tp_targets=None, tp_splits=None, sl_price=None, dry_run=bool(dry_run),
        )
        # אודיט
        plan = (res.get("plan") or {})
        tp = plan.get("tp") or []
        sl = plan.get("sl") or {}
        await send_audit("EXECUTOR TRADE", {
            "symbol": plan.get("symbol"),
            "side": plan.get("side"),
            "lev": plan.get("leverage"),
            "qty": plan.get("qty"),
            "price": round(float(plan.get("entry_price", 0.0)), 2),
            "tp": "; ".join([f"{round(l['stopPrice'],2)}@{l['qty']}" for l in tp]) if tp else "—",
            "sl": round(float(sl.get("stopPrice", 0.0)), 2) if sl else "—",
            "dry": dry_run,
        })
        return {"ok": True, "result": res}
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=[{"type":"value_error","loc":["query"],"msg":str(ve)}])
    except httpx.HTTPStatusError as he:
        raise HTTPException(status_code=502, detail={"error":"binance_http", "status": he.response.status_code, "body": he.response.text})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))














