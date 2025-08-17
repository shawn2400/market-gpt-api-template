from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
from typing import Literal
from utils.auth import require_bearer_token
from utils.trade_executor import execute_trade_live
from utils.sl_tp_utils import predict_sltp_levels
from utils.ws_fallback import get_price
from utils.metrics import metrics_tracker

router = APIRouter()

class TradeRequest(BaseModel):
    symbol: str
    side: Literal["LONG", "SHORT"]
    budget: float = 30
    leverage: int = 10
    entry: float | None = None
    sl: float | None = None
    tp: float | None = None
    dry_run: bool = True

@router.post("/execute", tags=["Trade"])
async def execute_trade(
    trade: TradeRequest, 
    request: Request = Depends(require_bearer_token)
):
    try:
        price = trade.entry or await get_price(trade.symbol)
        result = await execute_trade_live(
            symbol=trade.symbol,
            side=trade.side,
            budget=trade.budget,
            leverage=trade.leverage,
            entry=price,
            sl=trade.sl,
            tp=trade.tp,
            dry_run=trade.dry_run,
        )
        return {"status": "ok", "result": result}
    except Exception as e:
        metrics_tracker.record_error()
        raise HTTPException(status_code=500, detail=str(e))

class SLTPRequest(BaseModel):
    symbol: str
    direction: Literal["LONG", "SHORT"]
    entry: float

@router.post("/sltp", tags=["Trade"])
async def suggest_sltp(
    req: SLTPRequest,
    request: Request = Depends(require_bearer_token),
):
    try:
        sl, tp1, tp2 = await predict_sltp_levels(
            symbol=req.symbol, 
            entry=req.entry, 
            direction=req.direction
        )
        return {"sl": sl, "tp1": tp1, "tp2": tp2}
    except Exception as e:
        metrics_tracker.record_error()
        raise HTTPException(status_code=500, detail=str(e))










