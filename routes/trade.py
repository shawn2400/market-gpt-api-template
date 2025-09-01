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
    _floor_to_step_dec,
    _floor_to_tick_dec,
    _ceil_to_tick_dec,
    _to_plain_str,
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

    # פילטרים: tickSize/stepSize כדי לדעת איך להציג בדוח (העגינה בפועל תתבצע שוב ב-binance_client)
    f = get_symbol_filters(sym)
    step_str = f.get("stepSizeStr", "0.001")
    tick_str = f.get("tickSizeStr", "0.1")

    # חישוב כמות לפי תקציב ולוורידג' (לפני עיגון סופי)
    notional = payload.budget * payload.leverage
    raw_qty = _d(notional) / _d(entry)

    # לעדכון התשובה למשתמש (dry run/echo) נעשה עיגון ידידותי לתצוגה:
    qty_dec_preview = _floor_to_step_dec(raw_qty, step_str)
    if side == "SELL":
        px_dec_preview = _ceil_to_tick_dec(entry, tick_str)
    else:
        px_dec_preview = _floor_to_tick_dec(entry, tick_str)

    qty_f_preview = float(qty_dec_preview)
    px_f_preview  = float(px_dec_preview)

    if qty_f_preview <= 0:
        return TradeResponse(
            ok=False, symbol=sym, side=side, qty=0.0, entry=px_f_preview, leverage=payload.leverage,
            error="Calculated quantity is zero after step rounding"
        )

    # סט לוורידג' (שקט אם נכשל)
    try:
        set_leverage(sym, payload.leverage)
    except Exception:
        pass

    if payload.dry_run:
        # לא שולחים הזמנה – רק מחזירים איך זה יראה לאחר עיגון ראשוני
        return TradeResponse(ok=True, symbol=sym, side=side, qty=qty_f_preview, entry=px_f_preview,
                             leverage=payload.leverage, order=None)

    # הזמנה LIMIT-IOC (מתנהגת כ-MARKET עם דיוק תקין) — העיגון המחמיר קורה בתוך place_limit_order
    try:
        order = place_limit_order(
            symbol=sym,
            side=side,
            quantity=float(raw_qty),  # נעביר את ה־raw; place_limit_order יכפה step/minNotional וכו'
            price=float(entry),
            time_in_force="IOC",
            post_only=False,
            reduce_only=False,
            position_side=None,
            new_order_resp_type="RESULT",
        )
        # מחזירים את הערכים כפי שחישבנו בתצוגה – ההזמנה בפועל עשויה להיות בכמות מעט שונה אם הופעל MIN_NOTIONAL
        return TradeResponse(ok=True, symbol=sym, side=side, qty=qty_f_preview, entry=px_f_preview,
                             leverage=payload.leverage, order=order)
    except Exception as e:
        return TradeResponse(ok=False, symbol=sym, side=side, qty=qty_f_preview, entry=px_f_preview,
                             leverage=payload.leverage, order=None, error=str(e))

















































































































































































































































































































































































































































































































































































































































