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
    place_stop_market_order,
    place_take_profit_market,
    _quantize_multiple,
)
from utils.sltp import calc_sl_tp_for_symbol  # מחשב ומעגן SL/TP לפי tick

router = APIRouter(prefix="/trade", tags=["Trades"], dependencies=[Depends(require_api_key)])

class TradeRequest(BaseModel):
    symbol: str
    side: str = Field(..., pattern="^(BUY|SELL)$")
    budget: float = Field(..., gt=0)
    leverage: int = Field(10, ge=1, le=125)
    dry_run: bool = False
    # Bracket (אופציונלי)
    bracket: bool = False
    exit_qty: Optional[float] = None   # אם לא צוין → נשתמש בכמות הפתיחה
    bracket_close_position: bool = False  # ← חדש: אם true נשתמש closePosition=true במקום quantity
    position_side: Optional[str] = Field(None, pattern="^(LONG|SHORT)$")  # Hedge mode אופציונלי
    # SL/TP/ATR
    sl: Optional[float] = None
    tp: Optional[float] = None
    atr: Optional[float] = None
    atr_mult: float = 1.5

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
    sl_price: Optional[float] = None
    tp_price: Optional[float] = None
    sl_order: Optional[Dict[str, Any]] = None
    tp_order: Optional[Dict[str, Any]] = None

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

    # חישוב כמות לפי תקציב×מינוף
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
            need_notional = float(min_qty_dec * px_dec)
            need_budget = need_notional / max(1, payload.leverage)
            return TradeResponse(
                ok=False, symbol=sym, side=side, qty=float(qty_dec), entry=float(px_dec),
                leverage=payload.leverage, order=None,
                error="Quantity below minQty after precision rounding.",
                hint=f"Increase budget to ≥ ~{need_budget:.6f} USDT (at leverage {payload.leverage}×).",
                sl_price=None, tp_price=None
            )
        qty_dec = min_qty_dec if qty_dec < min_qty_dec else qty_dec

    # בדיקת MIN_NOTIONAL
    final_notional = float(qty_dec * px_dec)
    if final_notional < float(min_notional):
        need_budget = float(min_notional) / max(1, payload.leverage)
        return TradeResponse(
            ok=False, symbol=sym, side=side, qty=float(qty_dec), entry=float(px_dec),
            leverage=payload.leverage, order=None,
            error=f"MIN_NOTIONAL not met (have {final_notional:.8f} < need {min_notional:.8f}).",
            hint=f"Increase budget to ≥ ~{need_budget:.6f} USDT (at leverage {payload.leverage}×).",
            sl_price=None, tp_price=None
        )

    qty_f = float(qty_dec)
    px_f  = float(px_dec)

    # SL/TP מחושבים ומעוגנים ל-tick
    sl_price, tp_price = None, None
    try:
        sl_price, tp_price = calc_sl_tp_for_symbol(
            symbol=sym,
            entry=px_f,
            side=("LONG" if side == "BUY" else "SHORT"),
            sl=payload.sl,
            tp=payload.tp,
            atr=payload.atr,
            atr_mult=payload.atr_mult,
        )
    except Exception:
        sl_price, tp_price = None, None

    if qty_f <= 0:
        return TradeResponse(
            ok=False, symbol=sym, side=side, qty=0.0, entry=px_f, leverage=payload.leverage,
            error="Calculated quantity is zero after step rounding",
            sl_price=sl_price, tp_price=tp_price
        )

    # סט לוורידג' (שקט אם נכשל)
    try:
        set_leverage(sym, payload.leverage)
    except Exception:
        pass

    # Dry-run
    if payload.dry_run:
        return TradeResponse(
            ok=True, symbol=sym, side=side, qty=qty_f, entry=px_f, leverage=payload.leverage, order=None,
            sl_price=sl_price, tp_price=tp_price
        )

    # LIMIT-IOC לפתיחת פוזיציה
    try:
        order = place_limit_order(
            symbol=sym,
            side=side,
            quantity=qty_f,
            price=px_f,
            time_in_force="IOC",
            post_only=False,
            reduce_only=False,
            position_side=payload.position_side,
            new_order_resp_type="RESULT",
        )
    except Exception as e:
        return TradeResponse(
            ok=False, symbol=sym, side=side, qty=qty_f, entry=px_f, leverage=payload.leverage,
            order=None, error=str(e),
            sl_price=sl_price, tp_price=tp_price
        )

    sl_order_resp: Optional[Dict[str, Any]] = None
    tp_order_resp: Optional[Dict[str, Any]] = None

    # BRACKET אופציונלי
    if payload.bracket:
        exit_side = "SELL" if side == "BUY" else "BUY"
        # אם bracket_close_position=True → quantity=None (סגור הכול)
        if payload.bracket_close_position:
            exit_qty_for_orders = None
            reduce_only_flag = False  # closePosition לא צריך/מתעלם מ-reduceOnly
        else:
            exit_qty_for_orders = float(payload.exit_qty) if payload.exit_qty is not None else qty_f
            reduce_only_flag = True

        # SL
        if sl_price is not None:
            try:
                sl_order_resp = place_stop_market_order(
                    symbol=sym,
                    side=exit_side,
                    stop_price=float(sl_price),
                    quantity=exit_qty_for_orders,      # None → closePosition=true
                    reduce_only=reduce_only_flag,
                    position_side=payload.position_side,
                    working_type=None,                 # מה-ENV (MARK_PRICE ברירת מחדל)
                    price_protect=None,                # מה-ENV
                    new_order_resp_type="RESULT",
                )
            except Exception as e:
                sl_order_resp = {"error": str(e)}

        # TP
        if tp_price is not None:
            try:
                tp_order_resp = place_take_profit_market(
                    symbol=sym,
                    side=exit_side,
                    stop_price=float(tp_price),
                    quantity=exit_qty_for_orders,      # None → closePosition=true
                    reduce_only=reduce_only_flag,
                    position_side=payload.position_side,
                    working_type=None,
                    price_protect=None,
                    new_order_resp_type="RESULT",
                )
            except Exception as e:
                tp_order_resp = {"error": str(e)}

    return TradeResponse(
        ok=True,
        symbol=sym,
        side=side,
        qty=qty_f,
        entry=px_f,
        leverage=payload.leverage,
        order=order,
        sl_price=sl_price,
        tp_price=tp_price,
        sl_order=sl_order_resp,
        tp_order=tp_order_resp,
    )




















































































































































































































































































































































































































































































































































































































































