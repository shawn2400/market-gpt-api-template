# routes/trade.py
from __future__ import annotations
from fastapi import APIRouter, Depends, Body, HTTPException
from pydantic import BaseModel, Field
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from typing import Optional, Dict, Any

from utils.auth import require_api_key
from utils.ws_fallback import get_price
from utils.binance_client import (
    futures_mark_price,
    get_symbol_filters,
    set_leverage,
    place_limit_order,
    _quantize_multiple,
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
    hint: Optional[str] = None

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

    # פילטרים בטוחים
    f = get_symbol_filters(sym)
    step_str = f.get("stepSizeStr", "0.001")
    tick_str = f.get("tickSizeStr", "0.1")
    min_qty = f.get("minQty")
    min_notional = f.get("minNotional") or 5.0  # ברירת מחדל אם אין

    # חישוב כמות לפי תקציב×לבורג'
    notional = payload.budget * payload.leverage
    qty_raw = _d(notional) / _d(entry)

    # עיגון כמות/מחיר לפי step/tick
    qty_dec = _quantize_multiple(qty_raw, step_str, rounding=ROUND_DOWN)
    if side == "SELL":
        px_dec = _quantize_multiple(entry, tick_str, rounding=ROUND_UP)
    else:
        px_dec = _quantize_multiple(entry, tick_str, rounding=ROUND_DOWN)

    # אכיפת minQty
    if isinstance(min_qty, (int, float)) and min_qty is not None:
        min_qty_dec = _quantize_multiple(Decimal(str(min_qty)), step_str, rounding=ROUND_UP)
        if qty_dec < min_qty_dec:
            # אם הכמות המינימלית גדולה ממה שהתקציב מאפשר → נחזיר שגיאה עם רמז
            need_notional = float(min_qty_dec * px_dec)
            need_budget = need_notional / max(1, payload.leverage)
            return TradeResponse(
                ok=False, symbol=sym, side=side, qty=float(qty_dec), entry=float(px_dec),
                leverage=payload.leverage, order=None,
                error="Quantity below minQty after precision rounding.",
                hint=f"Increase budget to ≥ ~{need_budget:.6f} USDT (at leverage {payload.leverage}×)."
            )
        # אחרת נרים ל-minQty
        qty_dec = min_qty_dec if qty_dec < min_qty_dec else qty_dec

    # בדיקת MIN_NOTIONAL
    final_notional = float(qty_dec * px_dec)
    if final_notional < float(min_notional):
        need_budget = float(min_notional) / max(1, payload.leverage)
        return TradeResponse(
            ok=False, symbol=sym, side=side, qty=float(qty_dec), entry=float(px_dec),
            leverage=payload.leverage, order=None,
            error=f"MIN_NOTIONAL not met (have {final_notional:.8f} < need {min_notional:.8f}).",
            hint=f"Increase budget to ≥ ~{need_budget:.6f} USDT (at leverage {payload.leverage}×)."
        )

    qty_f = float(qty_dec)
    px_f  = float(px_dec)

    if qty_f <= 0:
        return TradeResponse(
            ok=False, symbol=sym, side=side, qty=0.0, entry=px_f, leverage=payload.leverage,
            error="Calculated quantity is zero after step rounding"
        )

    # סט לוורידג' (שקט אם נכשל)
    try:
        set_leverage(sym, payload.leverage)
    except Exception:
        pass

    if payload.dry_run:
        return TradeResponse(ok=True, symbol=sym, side=side, qty=qty_f, entry=px_f, leverage=payload.leverage, order=None)

    # הזמנת LIMIT-IOC (כמו Market אך מדויקת)
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
        return TradeResponse(
            ok=False, symbol=sym, side=side, qty=qty_f, entry=px_f, leverage=payload.leverage,
            order=None, error=str(e)
        )


















































































































































































































































































































































































































































































































































































































































