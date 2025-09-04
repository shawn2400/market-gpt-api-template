# routes/executor.py
from __future__ import annotations
import logging
from typing import Dict, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from utils.auth import require_api_key
from utils.open_trade_manager import manage_open_trades, bulk_manage_trades

logger = logging.getLogger("algogpt.executor")

router = APIRouter(
    prefix="/executor",
    tags=["Executor"],
    dependencies=[Depends(require_api_key)],
)


# ===================== Models =====================
class TradeRequest(BaseModel):
    symbol: str = Field(..., description="Trading symbol, e.g., BTCUSDT")
    side: str = Field(..., description="BUY or SELL")
    qty: float = Field(..., gt=0, description="Quantity in contracts")
    entry_price: float = Field(..., gt=0, description="Entry limit price")
    sl_price: float = Field(..., gt=0, description="Stop-loss price")
    tp_price: float = Field(..., gt=0, description="Take-profit price")
    leverage: int = Field(10, description="Leverage for the trade")
    position_side: str = Field("BOTH", description="BOTH | LONG | SHORT")


class BulkTradeRequest(BaseModel):
    trades: list[TradeRequest]


# ===================== Endpoints =====================
@router.post("/trade", summary="Open trade with SL/TP")
async def open_trade(req: TradeRequest, _: Any = Depends(require_api_key)) -> Dict[str, Any]:
    """
    פותח טרייד כולל Limit כניסה + Stop-Loss + Take-Profit.
    """
    try:
        logger.info("[executor] trade request: %s", req.dict())
        result = manage_open_trades(
            symbol=req.symbol,
            side=req.side,
            qty=req.qty,
            entry_price=req.entry_price,
            sl_price=req.sl_price,
            tp_price=req.tp_price,
            leverage=req.leverage,
            position_side=req.position_side,
        )
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result)
        return result
    except Exception as e:
        logger.exception("[executor] trade error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/bulk", summary="Open multiple trades")
async def open_bulk(req: BulkTradeRequest, _: Any = Depends(require_api_key)) -> Dict[str, Any]:
    """
    פותח מספר טריידים ברצף.
    """
    try:
        trades = [t.dict() for t in req.trades]
        logger.info("[executor] bulk request: %s", trades)
        results = bulk_manage_trades(trades)
        return {"ok": True, "results": results}
    except Exception as e:
        logger.exception("[executor] bulk error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status", summary="Executor status")
async def executor_status(_: Any = Depends(require_api_key)) -> Dict[str, Any]:
    """
    מחזיר סטטוס בסיסי של ה־Executor (חי).
    """
    return {"ok": True, "status": "running"}































