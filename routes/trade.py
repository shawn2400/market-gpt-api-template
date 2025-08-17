from typing import Literal, Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from utils.auth import require_bearer_token
from utils.metrics import metrics_tracker
from utils.ws_fallback import get_price
from utils.sl_tp_utils import calculate_sl_tp
from utils.trade_executor import execute_trade_live

router = APIRouter()

class TradeRequest(BaseModel):
    symbol: str
    side: Literal["LONG", "SHORT"]
    budget: float = 30
    leverage: int = 10
    entry: Optional[float] = None
    sl: Optional[float] = None
    tp: Optional[float] = None
    atr: Optional[float] = None
    dry_run: bool = True

@router.post(
    "/execute",
    tags=["Trades"],
    operation_id="postTradeExecute",
    summary="Execute trade (dry-run by default)",
)
async def execute_trade(
    trade: TradeRequest,
    _: None = Depends(require_bearer_token),
):
    try:
        price = trade.entry or await get_price(trade.symbol)

        # חישוב SL/TP אם לא הועברו
        sl, tp = trade.sl, trade.tp
        if sl is None or tp is None:
            auto_sl, auto_tp = calculate_sl_tp(
                entry_price=price,
                direction=trade.side,
                atr=trade.atr,
            )
            sl = sl if sl is not None else auto_sl
            tp = tp if tp is not None else auto_tp

        result = await execute_trade_live(
            symbol=trade.symbol,
            side=trade.side,
            budget=trade.budget,
            leverage=trade.leverage,
            entry=price,
            sl=sl,
            tp=tp,
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
    atr: Optional[float] = None

class SLTP3Response(BaseModel):
    symbol: str
    direction: str
    sl: float
    tp1: float
    tp2: float

@router.post(
    "/sltp",
    tags=["Trades"],
    operation_id="postTradeSltp",
    response_model=SLTP3Response,
    summary="Suggest SL/TP (ATR-aware)",
)
async def suggest_sltp(
    req: SLTPRequest,
    _: None = Depends(require_bearer_token),
):
    try:
        sl, tp1 = calculate_sl_tp(
            entry_price=req.entry,
            direction=req.direction,
            atr=req.atr,
        )
        if req.direction == "LONG":
            tp2 = req.entry + (tp1 - req.entry) * 1.8
        else:
            tp2 = req.entry - (req.entry - tp1) * 1.8
        return SLTP3Response(
            symbol=req.symbol,
            direction=req.direction,
            sl=round(sl, 6),
            tp1=round(tp1, 6),
            tp2=round(tp2, 6),
        )
    except Exception as e:
        metrics_tracker.record_error()
        raise HTTPException(status_code=500, detail=str(e))






































































































































































































































































































