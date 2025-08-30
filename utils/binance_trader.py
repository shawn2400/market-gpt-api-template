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
    """
    בוחר מחיר Limit שמבטיח Post-Only (לא יחצה את הספר).
    BUY → מעט מתחת ל-Mark, SELL → מעט מעל.
    """
    if side == "BUY":
        return mark * 0.998  # ~0.2% מתחת ל-Mark
    else:
        return mark * 1.002  # ~0.2% מעל ה-Mark

async def binance_futures_trade(
    symbol: str,
    side: str,
    budget: float,
    leverage: int = 10,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    הזמנה ל-Binance Futures.
    - Limit Post-Only (GTX) כברירת מחדל.
    - שינוי מינוף לפני שליחה (best-effort).
    - qty = budget / mark.
    - רישום ל-orders_manager גם ב-dry-run (status=SIMULATED).
    """
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
        # רישום הזמנה מדומה (לא פעילה באמת מול Binance)
        oid = f"DRY-{int(time.time()*1000)}"
        record_order(
            symbol=symbol,
            side=side,
            qty=qty,
            price=entry_price,
            status="SIMULATED",
            order_id=oid,
            client_id=None,
            dry_run=True,
            tif="GTX",
        )
        logger.info(f"[DRY RUN] {side} {symbol} budget={budget} qty≈{qty:.8f} lev={leverage} limit={entry_price:.8f}")
        return {
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "entry": entry_price,
            "leverage": leverage,
            "dry_run": True,
        }

    # שינוי מינוף (best-effort)
    try:
        set_leverage(symbol, leverage)
    except Exception as e:
        logger.error(f"[Leverage] failed for {symbol}: {e}")

    # שליחת LIMIT GTX (Post-Only)
    resp = place_limit_order(
        symbol=symbol,
        side=side,
        quantity=qty,
        price=entry_price,
        post_only=True,          # GTX
        reduce_only=False,
        position_side=None,
        time_in_force=None,      # GTX יתועד כ-timeInForce
    )

    # רישום ב-local orders log
    order_id: Optional[str] = str(resp.get("orderId")) if "orderId" in resp else None
    client_id: Optional[str] = resp.get("clientOrderId") or resp.get("newClientOrderId")
    status = (resp.get("status") or "NEW").upper()
    tif = (resp.get("timeInForce") or "GTX").upper()

    record_order(
        symbol=symbol,
        side=side,
        qty=float(resp.get("origQty") or qty),
        price=float(resp.get("price") or entry_price),
        status=status,
        order_id=order_id or f"LOC-{int(time.time()*1000)}",
        client_id=client_id,
        dry_run=False,
        tif=tif,
    )

    out = {
        "symbol": symbol,
        "side": side,
        "qty": float(resp.get("origQty") or qty),
        "entry": float(resp.get("price") or entry_price),
        "leverage": leverage,
        "order": {k: resp.get(k) for k in ("orderId", "clientOrderId", "status", "price", "origQty", "timeInForce")},
    }
    logger.info(f"[New LIMIT GTX] {out}")
    return out

def force_close_position(symbol: str) -> Dict[str, Any]:
    """
    סגירת פוזיציה קיימת ב-Reduce-Only עם LIMIT+IOC אגרסיבי (ללא Market).
    LONG → SELL IOC נמוך מה-Mark; SHORT → BUY IOC גבוה מה-Mark.
    """
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
        side = "SELL"
        limit_px = mark * 0.98
    else:
        side = "BUY"
        limit_px = mark * 1.02

    from utils.binance_client import place_limit_order as _place
    resp = _place(
        symbol=symbol,
        side=side,
        quantity=abs(amt),
        price=limit_px,
        post_only=False,
        reduce_only=True,
        position_side=None,
        time_in_force="IOC",
    )
    return {
        "symbol": symbol,
        "closedAmt": amt,
        "side": side,
        "orderId": resp.get("orderId"),
        "status": resp.get("status"),
    }






































