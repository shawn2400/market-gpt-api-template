# routes/trade.py
from __future__ import annotations
from fastapi import APIRouter, Depends, Body, HTTPException
from pydantic import BaseModel, Field
from decimal import Decimal
from typing import Optional, Dict, Any

from utils.auth import require_api_key
from utils.ws_fallback import get_price
from utils.binance_client import (
    futures_mark_price,
    get_symbol_filters,
    set_leverage,
    place_limit_order,
)

router = APIRouter(prefix="/trade", tags=["Trades"], dependencies=[Depends(require_api_key)])

class TradeRequest(BaseModel):
    symbol: str
    side: str = Field(..., pattern="^(BUY|SELL)$")
    budget: float = Field(..., gt=0)
    leverage: int = Field(10, ge=1, le=125)
    dry_run: bool = False

class TradeResponse(BaseModel):
    ok: bool
    symbol: str
    side: str
    qty: float
    entry: float
    leverage: int
    order: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

def _d(x) -> Decimal:
    return Decimal(str(x))

@router.post("/execute", response_model=TradeResponse)
def execute_trade(payload: TradeRequest = Body(...)) -> TradeResponse:
    sym = payload.symbol.strip().upper()
    side = payload.side.strip().upper()

    # מחיר כניסה: Mark Price (fallback ל-cache)
    px = futures_mark_price(sym) or get_price(sym)
    if not px or px <= 0:
        raise HTTPException(status_code=503, detail=f"Price unavailable for {sym}")
    entry = float(px)

    # פילטרים: tickSize/stepSize → עיגון דיוק למניעת -1111
    f = get_symbol_filters(sym)
    step_str = f.get("stepSizeStr", "0.001")
    tick_str = f.get("tickSizeStr", "0.1")

    # חישוב כמות לפי תקציב ולוורידג'
    notional = payload.budget * payload.leverage
    qty = _d(notional) / _d(entry)

    # רצפה ל-step (מסתמך על binance_client ל-FLOOR ול-quantize)
    from utils.binance_client import _floor_to_step_dec, _to_plain_str  # קיימים אצלך
    qty_dec = _floor_to_step_dec(qty, step_str)
    px_dec  = _floor_to_step_dec(entry, tick_str)
    qty_f   = float(qty_dec)
    px_f    = float(px_dec)

    if qty_f <= 0:
        return TradeResponse(ok=False, symbol=sym, side=side, qty=0.0, entry=px_f, leverage=payload.leverage,
                             error="Calculated quantity is zero after step rounding")

    # סט לוורידג' (שקט אם נכשל)
    try:
        set_leverage(sym, payload.leverage)
    except Exception:
        pass

    if payload.dry_run:
        return TradeResponse(ok=True, symbol=sym, side=side, qty=qty_f, entry=px_f, leverage=payload.leverage, order=None)

    # הזמנה LIMIT-IOC (מתנהגת כ-MARKET עם דיוק תקין)
    try:
        order = place_limit_order(
            symbol=sym,
            side=side,
            quantity=qty_f,
            price=px_f,
            time_in_force="IOC",
            post_only=False,
            reduce_only=False,
            position_side=None,
            new_order_resp_type="RESULT",
        )
        return TradeResponse(ok=True, symbol=sym, side=side, qty=qty_f, entry=px_f, leverage=payload.leverage, order=order)
    except Exception as e:
        return TradeResponse(ok=False, symbol=sym, side=side, qty=qty_f, entry=px_f, leverage=payload.leverage, order=None, error=str(e))


















































































































































































































































































































































































































































































































































































































































