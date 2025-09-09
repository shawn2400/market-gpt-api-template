# utils/trade_executor.py
from __future__ import annotations
import math, logging
from typing import Optional, Dict, Any
from utils.binance_client import (
    futures_mark_price, set_leverage, futures_create_order, get_symbol_filters
)
from utils.ws_fallback import get_price  # מחיר חי עם fallback
log = logging.getLogger("algogpt.trade_executor")

def _round_step(x: float, step: float) -> float:
    if step <= 0: return x
    return math.floor(x / step) * step

def _ensure_min_notional(qty: float, price: float, min_notional: float, step: float) -> float:
    if min_notional and price * qty < min_notional:
        target = (min_notional / price) * 1.001
        qty = _round_step(target, step)
    return qty

async def execute_trade_live(
    symbol: str,
    side: str,
    budget: Optional[float] = None,
    leverage: int = 5,
    dry_run: bool = True,
    quantity: Optional[float] = None,   # ← NEW: תואם ל־router
    **kwargs: Any,                      # ← סופג שדות נוספים קדימה/אחורה
) -> Dict[str, Any]:
    """
    אם quantity סופקה – משתמשים בה.
    אם לא – מחשבים כמות לפי budget*leverage/price עם עיגול ל־stepSize ועמידה ב־minNotional/minQty.
    """
    symbol = symbol.upper().strip()
    side = side.upper().strip()
    if side not in {"BUY","SELL"}:
        raise ValueError(f"Invalid side: {side}")

    # מחיר חי
    price = await get_price(symbol)  # float
    if price is None or price <= 0:
        # fallback ל־mark
        mp = futures_mark_price(symbol)
        price = float(mp.get("markPrice", 0.0))
    if price <= 0:
        raise RuntimeError(f"Cannot fetch price for {symbol}")

    # פילטרים
    f = get_symbol_filters(symbol, futures=True)
    step = float(f.get("stepSize", "0.001"))
    min_qty = float(f.get("minQty", "0.0"))
    min_notional = float(f.get("minNotional", "0.0"))

    # חישוב כמות (אם לא נמסרה)
    if quantity is None:
        if not budget or budget <= 0:
            raise ValueError("Either quantity or positive budget must be provided")
        usd = float(budget) * float(leverage)
        raw_qty = usd / price
        qty = max(_round_step(raw_qty, step), min_qty)
        qty = _ensure_min_notional(qty, price, min_notional, step)
    else:
        qty = float(quantity)
        if qty < min_qty:
            qty = min_qty
        qty = _ensure_min_notional(qty, price, min_notional, step)

    payload = {
        "symbol": symbol,
        "side": side,
        "price": price,
        "qty": qty,
        "leverage": leverage,
        "dry_run": dry_run,
    }

    if dry_run:
        log.info("[DRY] %s", payload)
        return {"ok": True, "dry_run": True, **payload}

    # בפועל
    set_leverage(symbol, leverage)
    resp = futures_create_order(symbol=symbol, side=side, quantity=qty, type="MARKET")  # או LIMIT/STOP בהתאם למדיניות
    return {"ok": True, "dry_run": False, "order": resp, **payload}


































