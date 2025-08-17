from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
import logging

# אימות
from utils.auth import require_bearer_token

# פונקציות
from utils.ws_fallback import get_price
from utils.trade_executor import execute_trade_live
from utils.sl_tp_utils import predict_optimal_sl_tp
from utils.metrics import metrics_tracker

router = APIRouter()
logger = logging.getLogger(__name__)


class TradeRequest(BaseModel):
    symbol: str
    side: str  # "LONG" or "SHORT"
    entry: Optional[float] = None
    sl: Optional[float] = None
    tp: Optional[float] = None
    leverage: Optional[int] = 10
    budget: Optional[float] = 50.0
    dry_run: Optional[bool] = False


@router.get("/price")
async def price(symbol: str, _: str = Depends(require_bearer_token)):
    try:
        price = await get_price(symbol)
        return {"symbol": symbol, "price": price}
    except Exception as e:
        logger.error(f"[Price] Failed to get price for {symbol}: {e}")
        metrics_tracker.record_error()
        raise HTTPException(status_code=500, detail="Failed to fetch price")


@router.post("/sltp")
async def get_sltp(trade: TradeRequest, _: str = Depends(require_bearer_token)):
    try:
        sl, tp = await predict_optimal_sl_tp(
            symbol=trade.symbol,
            direction=trade.side,
            entry=trade.entry,
        )
        return {"symbol": trade.symbol, "side": trade.side, "sl": sl, "tp": tp}
    except Exception as e:
        logger.error(f"[SLTP] Error predicting SL/TP: {e}")
        metrics_tracker.record_error()
        raise HTTPException(status_code=500, detail="Failed to predict SL/TP")


@router.post("/execute-trade")
async def execute(trade: TradeRequest, _: str = Depends(require_bearer_token)):
    try:
        result = await execute_trade_live(trade.dict())
        pnl = result.get("pnl", 0)
        metrics_tracker.record_trade(pnl)
        return result
    except Exception as e:
        logger.error(f"[TRADE] Execution failed: {e}")
        metrics_tracker.record_error()
        raise HTTPException(status_code=500, detail="Trade execution failed")








