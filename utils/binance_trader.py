# utils/binance_trader.py
from __future__ import annotations
import logging
import time
from typing import Dict, Any, Optional

from utils.binance_client import (
    futures_mark_price,
    set_leverage,
    place_limit_order,
    futures_open_positions,
)
from utils.orders_manager import record_order

logger = logging.getLogger("algogpt.binance.trader")

def _calc_entry_price(side: str, mark: float) -> float:
    # BUY מעט מתחת, SELL מעט מעל כדי לא לחצות ספר (Post-Only)
    return mark * (0.998 if side == "BUY" else 1.002)

async def binance_futures_trade(
    symbol: str,
    side: str,
    budget: float,
    leverage: int = 10,
    dry_run: bool = False,
) -> Dict[str, Any]:
    symbol = symbol.upper().strip()
    side = side.upper().strip()
    if side not in ("BUY", "SELL"):
        raise ValueError("side must be BUY or SELL")

    mark = futures_mark_price(symbol)
    if mark is None:
        raise RuntimeError(f"Mark price unavailable for {symbol}")

    qty = budget / mark
    entry_price = _calc_entry_price(side, mark)

    if dry_run:
        logger.info(f"[DRY RUN] {side} {symbol} budget={budget} qty≈{qty:.8f} lev={leverage} limit={entry_price:.8f}")
        # נשמור ללוג אם מוגדר ORDERS_RECORD_DRYRUN=1
        record_order(
            symbol=symbol, side=side, qty=qty, price=entry_price,
            status="DRY_RUN", dry_run=True, extra={"leverage": leverage, "mark": mark}
        )
        return {
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "entry": entry_price,
            "leverage": leverage,
            "dry_run": True,
            "error": None,
        }

    # שינוי מינוף (לא מפילים על כישלון)
    try:
        set_leverage(symbol, leverage)
    except Exception as e:
        logger.error(f"[Leverage] failed for {symbol}: {e}")

    order = place_limit_order(
        symbol=symbol,
        side=side,
        quantity=qty,
        price=entry_price,
        post_only=True,          # GTX
        reduce_only=False,
        position_side=None,      # Hedge? -> LONG/SHORT
        time_in_force=None,      # GTX
    )

    out = {
        "symbol": symbol,
        "side": side,
        "qty": qty,
        "entry": entry_price,
        "leverage": leverage,
        "order": {k: order.get(k) for k in ("orderId", "clientOrderId", "status", "price", "origQty")},
        "error": None,
    }

    try:
        record_order(
            order_id=order.get("orderId"),
            client_id=order.get("clientOrderId"),
            symbol=symbol,
            side=side,
            qty=float(order.get("origQty") or qty),
            price=float(order.get("price") or entry_price),
            status=str(order.get("status") or "NEW"),
            extra={"leverage": leverage, "mark": mark, "tif": "GTX"},
        )
    except Exception as e:
        logger.warning(f"[Orders] record failed: {e}")

    logger.info(f"[New LIMIT GTX] {out}")
    return out

def force_close_position(symbol: str) -> Dict[str, Any]:
    symbol = symbol.upper().strip()
    positions = futures_open_positions() or []
    pos = next((p for p in positions if p.get("symbol") == symbol), None)
    if not pos:
        return {"symbol": symbol, "closedAmt": 0.0, "message": "no position for symbol"}

    amt = float(pos.get("positionAmt") or 0.0)
    if amt == 0.0:
        return {"symbol": symbol, "closedAmt": 0.0, "message": "no open amount"}

    mark = futures_mark_price(symbol)
    if mark is None:
        raise RuntimeError(f"Mark price unavailable for {symbol}")

    if amt > 0:
        side = "SELL"; limit_px = mark * 0.98
    else:
        side = "BUY";  limit_px = mark * 1.02

    from utils.binance_client import place_limit_order as _place
    r = _place(
        symbol=symbol,
        side=side,
        quantity=abs(amt),
        price=limit_px,
        post_only=False,
        reduce_only=True,
        position_side=None,
        time_in_force="IOC",
    )
    try:
        record_order(
            order_id=r.get("orderId"),
            client_id=r.get("clientOrderId"),
            symbol=symbol,
            side=side,
            qty=float(abs(amt)),
            price=float(limit_px),
            status=str(r.get("status") or "NEW"),
            extra={"reduce_only": True, "tif": "IOC", "mark": mark},
        )
    except Exception:
        pass

    logger.info(f"[Force Close IOC] {symbol} amt={amt} -> {side} limit={limit_px} resp={r.get('orderId')}")
    return {"symbol": symbol, "closedAmt": amt, "side": side, "orderId": r.get("orderId"), "status": r.get("status")}





































