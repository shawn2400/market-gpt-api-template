# routes/trade.py
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Literal, Optional

from utils.auth import require_bearer_token
from utils.ws_fallback import get_price
from utils.sl_tp_utils import calculate_sl_tp
from utils.trade_executor import execute_trade_live
from utils.metrics import metrics_tracker

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

@router.post("/execute", tags=["Trades"], dependencies=[Depends(require_bearer_token)])
async def execute_trade(trade: TradeRequest):
    try:
        price = trade.entry or await get_price(trade.symbol)

        # אם לא נשלחו sl/tp – נחשב אוטומטית (כולל ATR אם קיים)
        sl = trade.sl
        tp = trade.tp
        if sl is None or tp is None:
            sl, tp = calculate_sl_tp(price, trade.side, atr=trade.atr)

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

@router.post("/sltp", tags=["Trades"], dependencies=[Depends(require_bearer_token)])
async def suggest_sltp(req: SLTPRequest):
    try:
        sl, tp1 = calculate_sl_tp(req.entry, req.direction, atr=req.atr)
        # TP2: מרחק גדול ב־50% מ־TP1 (פשוט ושקוף)
        if req.direction == "LONG":
            tp2 = req.entry + (tp1 - req.entry) * 1.5
        else:
            tp2 = req.entry - (req.entry - tp1) * 1.5
        return {
            "symbol": req.symbol,
            "direction": req.direction,
            "sl": round(sl, 6),
            "tp1": round(tp1, 6),
            "tp2": round(tp2, 6),
        }
    except Exception as e:
        metrics_tracker.record_error()
        raise HTTPException(status_code=500, detail=str(e))





































































































































































































































































































