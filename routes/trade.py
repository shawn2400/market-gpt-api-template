# routes/trade.py
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Literal, Optional
from utils.auth import require_bearer_token
from utils.sl_tp_utils import calculate_sl_tp
from utils.metrics import metrics_tracker
from utils.scanner_utils import fetch_ohlcv

# אופציונלי למסחר חי (יופעל רק אם dry_run=False וה־ENV מאפשר)
try:
    from utils.binance_trader import binance_futures_trade
except Exception:
    binance_futures_trade = None  # type: ignore

router = APIRouter()

class TradeRequest(BaseModel):
    symbol: str
    side: Literal["LONG", "SHORT"]
    budget: float = 30
    leverage: int = 10
    entry: Optional[float] = None
    sl: Optional[float] = None
    tp: Optional[float] = None
    dry_run: bool = True

class SLTPRequest(BaseModel):
    symbol: str
    direction: Literal["LONG", "SHORT"]
    entry: float
    atr: Optional[float] = None

@router.post("/sltp", tags=["Trades"], operation_id="postTradeSltp")
async def suggest_sltp(
    req: SLTPRequest,
    _: None = Depends(require_bearer_token),
):
    try:
        sl, tp = calculate_sl_tp(entry_price=req.entry, direction=req.direction, atr=req.atr)
        # נגזרת TP2 פשוטה: הגדלת המרחק ב~1.8×
        tp2 = (req.entry + (tp - req.entry) * 1.8) if req.direction == "LONG" else (req.entry - (req.entry - tp) * 1.8)
        return {"sl": round(sl, 6), "tp1": round(tp, 6), "tp2": round(tp2, 6)}
    except Exception as e:
        metrics_tracker.record_error()
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/execute", tags=["Trades"], operation_id="postTradeExecute")
async def execute_trade(
    trade: TradeRequest,
    _: None = Depends(require_bearer_token),
):
    try:
        # אם לא סופקה כניסה – נביא קלוז אחרון מה־Futures
        entry = trade.entry
        if entry is None:
            df = await fetch_ohlcv(trade.symbol, interval="1m", limit=2)
            if df.empty:
                raise HTTPException(status_code=400, detail="לא ניתן להביא מחיר חי")
            entry = float(df["close"].iloc[-1])

        # חישוב SL/TP אם לא ניתנו
        if trade.sl is None or trade.tp is None:
            sl, tp = calculate_sl_tp(entry_price=entry, direction=trade.side)
        else:
            sl, tp = trade.sl, trade.tp

        plan = {
            "symbol": trade.symbol.upper(),
            "side": trade.side,
            "budget": trade.budget,
            "leverage": trade.leverage,
            "entry": float(entry),
            "sl": float(sl),
            "tp": float(tp),
            "dry_run": trade.dry_run,
        }

        if trade.dry_run or binance_futures_trade is None:
            return {"status": "ok", "result": {"mode": "dry_run", **plan}}

        # מסחר חי (יתכשל אם ENV חוסם שינויי חשבון)
        placed = await binance_futures_trade(
            symbol=trade.symbol, side=trade.side, entry=entry,
            sl=sl, tp=tp, leverage=trade.leverage, budget=trade.budget
        )
        return {"status": "ok", "result": placed}

    except HTTPException:
        raise
    except Exception as e:
        metrics_tracker.record_error()
        raise HTTPException(status_code=500, detail=str(e))










