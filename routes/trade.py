# routes/trade.py
from __future__ import annotations

import os, math, logging
from typing import Optional, Dict, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from utils.binance_client import (
    futures_mark_price,
    get_symbol_filters,
    place_limit_order,
    set_leverage,
)
from utils.orders_manager import record_simulated_order, record_order

router = APIRouter(prefix="/trade", tags=["Trade"])
log = logging.getLogger("algogpt.trade")

def _to_bool(v: str | None, default: bool = False) -> bool:
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "on")

def _floor_to_step(x: float, step: float) -> float:
    return x if step <= 0 else (math.floor(x / step) * step)

def _floor_to_tick(px: float, tick: float) -> float:
    return px if tick <= 0 else (math.floor(px / tick) * tick)

MIN_NOTIONAL_USDT = float(os.getenv("MIN_NOTIONAL_USDT", "5"))

class TradeRequest(BaseModel):
    symbol: str = Field(..., description="למשל BTCUSDT")
    side: str = Field(..., description="BUY או SELL")
    budget: float = Field(..., gt=0, description="תקציב USDT (מרג'ין)")
    leverage: Optional[int] = Field(10, ge=1, le=125)
    price: Optional[float] = Field(None, description="מחיר כניסה אופציונלי; אם ריק נשתמש ב-Mark Price")
    dry_run: bool = Field(True, description="ברירת מחדל DRY-RUN")
    post_only: bool = Field(False, description="אם True נשתמש ב-GTX (Post Only)")
    reduce_only: bool = Field(False, description="להזמנת ReduceOnly")
    position_side: Optional[str] = Field(None, description="Hedge Mode: LONG/SHORT (לא חובה)")

class TradeResponse(BaseModel):
    ok: bool
    symbol: str
    side: str
    qty: float
    entry: float
    leverage: Optional[int] = None
    order: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

@router.post("/execute", response_model=TradeResponse)
async def execute_trade(req: TradeRequest):
    sym = req.symbol.strip().upper()
    sdir = req.side.strip().upper()
    if sdir not in ("BUY", "SELL"):
        raise HTTPException(400, "side must be BUY or SELL")

    # פילטרים (stepSize/tickSize)
    try:
        f = get_symbol_filters(sym)
        tick = float(f.get("tickSize", 0.1))
        step = float(f.get("stepSize", 0.001))
    except Exception as e:
        log.warning({"event": "filters_fallback", "error": str(e)})
        tick, step = 0.1, 0.001

    # מחיר כניסה: נתעדף Mark Price אם לא סופק
    px = None
    if req.price and req.price > 0:
        px = float(req.price)
    else:
        px = futures_mark_price(sym)
    if not px or px <= 0:
        return TradeResponse(
            ok=False, symbol=sym, side=sdir, qty=0.0, entry=0.0, leverage=req.leverage,
            error="mark price unavailable"
        )
    entry = _floor_to_tick(px, tick)

    # חישוב כמות: כמו בלוגים שלך — על בסיס budget בלבד, מינימום step
    # אם budget קטן מדי, נרים ל-step
    qty_raw = req.budget / entry
    qty = max(_floor_to_step(qty_raw, step), step)

    # דרישת מינימום נומינלית (אופציונלי)
    if (qty * entry) < max(0.0, MIN_NOTIONAL_USDT):
        # עדיין נרשום DRY-RUN עם הכמות המינימלית, כדי שתראה בהיסטוריה
        qty = step

    if req.dry_run:
        # רישום להיסטוריה כ-SIMULATED
        try:
            record_simulated_order(symbol=sym, side=sdir, qty=qty, price=entry, leverage=req.leverage)
        except Exception as e:
            log.warning({"event": "record_simulated_failed", "error": str(e)})
        return TradeResponse(ok=True, symbol=sym, side=sdir, qty=qty, entry=entry, leverage=req.leverage, error=None)

    # מסחר חי?
    if not _to_bool(os.getenv("EXECUTE_TRADES", "0"), False):
        return TradeResponse(
            ok=False, symbol=sym, side=sdir, qty=qty, entry=entry, leverage=req.leverage,
            error="live trading disabled (EXECUTE_TRADES=0)"
        )

    # סט לֶוֶורֵג' (לא חובה אבל מומלץ)
    try:
        if req.leverage:
            set_leverage(sym, int(req.leverage))
    except Exception as e:
        log.warning({"event": "set_leverage_failed", "symbol": sym, "error": str(e)})

    # שליחת הזמנה LIMIT (GTX אם post_only=True)
    try:
        order = place_limit_order(
            symbol=sym,
            side=sdir,
            quantity=qty,
            price=entry,
            post_only=bool(req.post_only),
            reduce_only=bool(req.reduce_only),
            position_side=(req.position_side or None),
            time_in_force=None,  # ייקבע ל-GTC או GTX בפונקציה
            new_order_resp_type="RESULT",
        )
        # כתיבה להיסטוריה כ-"NEW"/"OPEN"
        try:
            status = str(order.get("status") or "NEW")
            client_id = order.get("clientOrderId") or None
            record_order(
                symbol=sym, side=sdir, qty=qty, price=entry,
                leverage=req.leverage, status=status, client_order_id=client_id
            )
        except Exception:
            pass

        return TradeResponse(ok=True, symbol=sym, side=sdir, qty=qty, entry=entry, leverage=req.leverage, order=order)
    except Exception as e:
        return TradeResponse(
            ok=False, symbol=sym, side=sdir, qty=qty, entry=entry, leverage=req.leverage, error=str(e)
        )

















































































































































































































































































































































































































































































































































































































































