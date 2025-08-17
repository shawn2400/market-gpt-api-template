# routes/trade.py
from __future__ import annotations

import logging
from typing import Optional, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from utils.auth import require_bearer_token
from utils.sl_tp_utils import calculate_sl_tp
from utils.binance_trader import binance_futures_trade

logger = logging.getLogger(__name__)
router = APIRouter()

# ======== Pydantic models ========

SideLiteral = Literal["LONG", "SHORT"]
MarginLiteral = Literal["ISOLATED", "CROSSED"]

class SLTPRequest(BaseModel):
    symbol: str = Field(..., example="BTCUSDT")
    direction: SideLiteral
    entry: float = Field(..., gt=0, example=65000)
    atr: Optional[float] = Field(None, gt=0)

class SLTP3Response(BaseModel):
    symbol: str
    direction: SideLiteral
    sl: float
    tp1: float
    tp2: float

class TradeExecuteRequest(BaseModel):
    symbol: str = Field(..., example="BTCUSDT")
    side: SideLiteral
    budget: float = Field(..., gt=0, example=100)
    leverage: int = Field(..., ge=1, le=125, example=10)
    entry: Optional[float] = Field(None, gt=0)
    sl: Optional[float] = Field(None, gt=0)
    tp: Optional[float] = Field(None, gt=0)
    atr: Optional[float] = Field(None, gt=0, description="Optional ATR for SL/TP calculation")
    dry_run: bool = Field(True, description="By default we simulate only")
    margin_type: MarginLiteral = Field("ISOLATED", description="Futures margin mode to use")

class TradeExecuteResponse(BaseModel):
    status: str = "ok"
    result: dict

# ======== Routes ========

@router.post(
    "/sltp",
    tags=["Trades"],
    operation_id="postTradeSltp",
    dependencies=[Depends(require_bearer_token)],
    response_model=SLTP3Response,
)
async def post_sltp(payload: SLTPRequest):
    """
    החזרת SL/TP מוצעים (ATR-aware). בטוח – לא מבצע טרייד.
    """
    # חישוב SL/TP ראשי
    sl, tp = calculate_sl_tp(
        entry_price=payload.entry,
        direction=payload.direction,
        atr=payload.atr,
    )
    # שתי מטרות (tp1=tp, tp2 קצת רחוק יותר). כאן: +40% מהמרחק של tp1 מה־entry
    if payload.direction == "LONG":
        tp2 = round(tp + (tp - payload.entry) * 0.4, 6)
    else:
        tp2 = round(tp - (payload.entry - tp) * 0.4, 6)

    return SLTP3Response(
        symbol=payload.symbol.upper(),
        direction=payload.direction,
        sl=sl,
        tp1=tp,
        tp2=tp2,
    )


@router.post(
    "/execute",
    tags=["Trades"],
    operation_id="postTradeExecute",
    dependencies=[Depends(require_bearer_token)],
    response_model=TradeExecuteResponse,
)
async def post_execute(payload: TradeExecuteRequest):
    """
    ביצוע טרייד. כברירת מחדל dry_run=True (סימולציה בלבד).
    אם entry/sl/tp לא סופקו – נחשב אותם (לפי ATR אם קיים).
    """
    symbol = payload.symbol.upper()
    side = payload.side
    margin_type = payload.margin_type

    entry = payload.entry
    sl = payload.sl
    tp = payload.tp

    # אם חסר SL/TP – נחשב
    if entry is None or sl is None or tp is None:
        if entry is None:
            raise HTTPException(status_code=400, detail="entry is required when auto-calculating SL/TP")
        sl_auto, tp_auto = calculate_sl_tp(
            entry_price=entry,
            direction=side,
            atr=payload.atr,
        )
        sl = sl if sl is not None else sl_auto
        tp = tp if tp is not None else tp_auto

    # Dry run — לא נוגעים בחשבון
    if payload.dry_run:
        result = {
            "dry_run": True,
            "symbol": symbol,
            "side": side,
            "entry": entry,
            "sl": sl,
            "tp": tp,
            "budget": payload.budget,
            "leverage": payload.leverage,
            "margin_type": margin_type,
            "note": "No orders sent (dry_run=true).",
        }
        return TradeExecuteResponse(status="ok", result=result)

    # Live — מבצע דרך binance_futures_trade (יכשל אם EXECUTE_TRADES=false או SKIP_MUTATIONS=true)
    try:
        trade_result = await binance_futures_trade(
            symbol=symbol,
            side=side,
            entry=float(entry),
            sl=float(sl),
            tp=float(tp),
            leverage=int(payload.leverage),
            budget=float(payload.budget),
            quantity=None,
            market_type="futures",
            cid_prefix="algogpt",
            margin_type=margin_type,  # <<< חשוב
        )
        return TradeExecuteResponse(status="ok", result=trade_result)
    except Exception as e:
        logger.exception("Trade execution failed")
        raise HTTPException(status_code=400, detail=f"trade failed: {e}")








































































































































































































































































































