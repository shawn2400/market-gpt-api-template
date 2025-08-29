from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import os

from utils.trade_manager import get_open_trades, get_trade_history, add_trade
from utils.auth import require_api_key
from utils.binance_trader import binance_futures_trade

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
    """ביצוע טרייד בפועל או Dry-Run עם Fail-Safe סביבתי."""
    s = (req.symbol or "").strip().upper()
    if not s or not s.endswith("USDT"):
        raise HTTPException(status_code=400, detail="Invalid symbol (expecting e.g. BTCUSDT)")
    if not (1 <= int(req.leverage) <= 125):
        raise HTTPException(status_code=400, detail="Invalid leverage (1..125)")
    if float(req.budget) <= 0:
        raise HTTPException(status_code=400, detail="Invalid budget (>0)")

    exec_env = os.getenv("EXECUTE_TRADES","true").lower() in ("1","true","yes")
    dry_run = req.dry_run or (not exec_env)
    if not exec_env and not req.dry_run:
        return ExecuteTradeResponse(
            ok=False, symbol=s, side=req.side, leverage=req.leverage,
            error="Trading disabled by EXECUTE_TRADES=false (dry-run enforced)"
        )

    try:
        result: Dict[str, Any] = await binance_futures_trade(
            symbol=s,
            side=req.side,
            budget=req.budget,
            leverage=req.leverage,
            dry_run=dry_run,
        )
        if not dry_run:
            add_trade(s, req.side, result["entry"], result["qty"])
        return ExecuteTradeResponse(ok=True, **result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Trade execution failed: {str(e)}")












































































































































































































































































































































































































































































































































































































































