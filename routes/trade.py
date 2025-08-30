# routes/trade.py
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone

from utils.trade_manager import get_open_trades, get_trade_history, add_trade
from utils.auth import require_api_key
from utils.binance_trader import binance_futures_trade
from utils.orders_manager import record_order  # ← חדש

router = APIRouter(
    prefix="/trade",
    tags=["Trade"],
    dependencies=[Depends(require_api_key)]
)

class TradeModel(BaseModel):
    id: str
    symbol: str
    side: str
    entry_price: float
    qty: float
    pnl: float
    status: str
    opened_at: str

class TradesSummary(BaseModel):
    ok: bool = True
    total: int
    returned: int
    items: List[TradeModel] = Field(default_factory=list)

@router.get("/open", response_model=TradesSummary)
async def list_open_trades():
    trades = get_open_trades()
    items = [TradeModel(**t) for t in trades]
    return TradesSummary(total=len(trades), returned=len(items), items=items)

@router.get("/history", response_model=TradesSummary)
async def trade_history(limit: int = 50):
    trades = get_trade_history(limit=limit)
    items = [TradeModel(**t) for t in trades[:limit]]
    return TradesSummary(total=len(trades), returned=len(items), items=items)

class ExecuteTradeRequest(BaseModel):
    symbol: str
    side: str
    budget: float
    leverage: int = 10
    dry_run: bool = False

class ExecuteTradeResponse(BaseModel):
    ok: bool
    symbol: str
    side: str
    qty: Optional[float] = None
    entry: Optional[float] = None
    leverage: Optional[int] = None
    error: Optional[str] = None

@router.post("/execute", response_model=ExecuteTradeResponse)
async def execute_trade(req: ExecuteTradeRequest):
    try:
        result: Dict[str, Any] = await binance_futures_trade(
            symbol=req.symbol,
            side=req.side,
            budget=req.budget,
            leverage=req.leverage,
            dry_run=req.dry_run,
        )

        # רישום היסטוריה להזמנות (כולל dry-run כסימולציה)
        created_at = datetime.now(timezone.utc).isoformat()
        order_payload = {
            "symbol": req.symbol.upper(),
            "side": req.side.upper(),
            "qty": float(result.get("qty") or 0.0),
            "price": float(result.get("entry") or 0.0),
            "status": "SIMULATED" if req.dry_run else (result.get("order", {}).get("status") or "NEW"),
            "created_at": created_at,
        }
        if isinstance(result.get("order"), dict):
            o = result["order"]
            if o.get("orderId"):
                order_payload["id"] = str(o["orderId"])
            if o.get("clientOrderId"):
                order_payload["clientOrderId"] = o["clientOrderId"]
        record_order(order_payload)

        if not req.dry_run:
            add_trade(req.symbol, req.side, result["entry"], result["qty"])

        return ExecuteTradeResponse(ok=True, **result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Trade execution failed: {e}")














































































































































































































































































































































































































































































































































































































































