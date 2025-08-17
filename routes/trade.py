# routes/trade.py
from __future__ import annotations

import logging
from typing import Optional, Literal, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Body
from pydantic import BaseModel, Field

from utils.auth import require_bearer_token
from utils.sl_tp_utils import calculate_sl_tp
from utils.binance_trader import binance_futures_trade

logger = logging.getLogger(__name__)

# ✅ אימות ברמת ה־router (ללא prefix לשמירה על תאימות למסלולים /sltp ו-/execute)
router = APIRouter(
    tags=["Trades"],
    dependencies=[Depends(require_bearer_token)],
)

SideLiteral = Literal["LONG", "SHORT"]

# ---------- Models ----------

class SLTPRequest(BaseModel):
    symbol: str = Field(..., example="BTCUSDT")
    direction: SideLiteral
    entry: float = Field(..., gt=0, example=65000)
    atr: Optional[float] = Field(
        None, gt=0, description="Optional ATR to refine SL/TP"
    )

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
    dry_run: bool = Field(True, description="Default: simulate only (no live orders)")

class TradeExecuteResponse(BaseModel):
    status: str = Field(default="ok", description="ok / error")
    result: Dict[str, Any]

class ErrorResponse(BaseModel):
    detail: str

# ---------- Endpoints ----------

@router.post(
    "/sltp",
    operation_id="postTradeSltp",
    response_model=SLTP3Response,
    responses={
        400: {"model": ErrorResponse, "description": "Bad Request"},
        401: {"model": ErrorResponse, "description": "Unauthorized"},
    },
)
async def post_sltp(payload: SLTPRequest = Body(...)) -> SLTP3Response:
    """
    Compute SL/TP from entry & direction (optionally ATR).
    """
    sl, tp1 = calculate_sl_tp(
        entry_price=payload.entry,
        direction=payload.direction,
        atr=payload.atr,
    )

    # tp2: הרחבה של יעד ראשון (40% מהמרחק entry→tp1)
    if payload.direction == "LONG":
        tp2 = round(tp1 + (tp1 - payload.entry) * 0.4, 6)
    else:
        tp2 = round(tp1 - (payload.entry - tp1) * 0.4, 6)

    return SLTP3Response(
        symbol=payload.symbol.upper(),
        direction=payload.direction,
        sl=sl,
        tp1=tp1,
        tp2=tp2,
    )

@router.post(
    "/execute",
    operation_id="postTradeExecute",
    response_model=TradeExecuteResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Bad Request"},
        401: {"model": ErrorResponse, "description": "Unauthorized"},
    },
)
async def post_execute(payload: TradeExecuteRequest = Body(...)) -> TradeExecuteResponse:
    """
    Execute a Futures trade.
    - If SL/TP missing and entry provided → auto-calc via calculate_sl_tp.
    - dry_run=True → simulation only (no live orders).
    """
    symbol = payload.symbol.upper()
    side = payload.side
    entry = payload.entry
    sl = payload.sl
    tp = payload.tp

    # Auto-calc SL/TP if missing (requires entry)
    if (sl is None or tp is None):
        if entry is None:
            raise HTTPException(status_code=400, detail="entry is required when auto-calculating SL/TP")
        sl_auto, tp_auto = calculate_sl_tp(entry_price=entry, direction=side, atr=payload.atr)
        sl = sl if sl is not None else sl_auto
        tp = tp if tp is not None else tp_auto

    # Dry-run
    if payload.dry_run:
        result = {
            "dry_run": True,
            "symbol": symbol,
            "side": side,
            "entry": float(entry) if entry is not None else None,
            "sl": float(sl) if sl is not None else None,
            "tp": float(tp) if tp is not None else None,
            "budget": float(payload.budget),
            "leverage": int(payload.leverage),
            "note": "No orders sent (dry_run=true).",
        }
        return TradeExecuteResponse(status="ok", result=result)

    # Live
    try:
        trade_result = await binance_futures_trade(
            symbol=symbol,
            side=side,
            entry=float(entry) if entry is not None else None,
            sl=float(sl) if sl is not None else None,
            tp=float(tp) if tp is not None else None,
            leverage=int(payload.leverage),
            budget=float(payload.budget),
            quantity=None,
            market_type="futures",
            cid_prefix="algogpt",
        )
        return TradeExecuteResponse(status="ok", result=trade_result)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Trade execution failed")
        raise HTTPException(status_code=400, detail=f"trade failed: {e}")











































































































































































































































































































