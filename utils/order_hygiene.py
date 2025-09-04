# utils/order_hygiene.py
from __future__ import annotations
import logging
from typing import Dict, Any, Optional

from utils.binance_client import (
    futures_create_order,
    futures_cancel_all_orders,
    get_symbol_filters,
)

logger = logging.getLogger("algogpt.order_hygiene")


# ===================== מינימוםים =====================
def check_minimums(symbol: str, qty: float) -> bool:
    """
    בדיקה אם הכמות עומדת בדרישות Binance (minQty, minNotional).
    """
    try:
        flt = get_symbol_filters(symbol)
        if not flt:
            logger.warning("[order_hygiene] no filters for %s", symbol)
            return False

        min_qty = float(flt.get("minQty", 0))
        min_notional = float(flt.get("notional") or flt.get("minNotional", 0))
        tick_size = float(flt.get("tickSize", 0.0) or 0.0)

        if qty < min_qty:
            logger.warning("[order_hygiene] qty %s < minQty %s for %s", qty, min_qty, symbol)
            return False

        # אם יש דרישת notional – נחשב לפי מחיר ממוצע משוער
        if min_notional > 0 and (qty * tick_size) < min_notional:
            logger.warning(
                "[order_hygiene] notional %.4f < minNotional %.4f for %s",
                qty * tick_size,
                min_notional,
                symbol,
            )
            return False

        return True
    except Exception as e:
        logger.error("[order_hygiene] check_minimums error: %s", e)
        return False


# ===================== ביטול קונפליקטים =====================
def cancel_if_conflict(symbol: str, side: str) -> None:
    """
    מבטל הוראות פתוחות קודמות שיכולות להתנגש בכניסה החדשה.
    """
    try:
        futures_cancel_all_orders(symbol=symbol)
        logger.info("[order_hygiene] cancelled existing orders for %s side=%s", symbol, side)
    except Exception as e:
        logger.warning("[order_hygiene] cancel_if_conflict error: %s", e)


# ===================== Limit Order =====================
def place_limit_order_safe(
    *,
    symbol: str,
    side: str,
    quantity: str,
    price: str,
    reduce_only: bool = False,
    position_side: str = "BOTH",
) -> Dict[str, Any]:
    try:
        res = futures_create_order(
            symbol=symbol,
            side=side,
            type="LIMIT",
            quantity=quantity,
            price=price,
            timeInForce="GTC",
            reduceOnly=reduce_only,
            positionSide=position_side,
        )
        return {"ok": True, "data": res}
    except Exception as e:
        logger.error("[order_hygiene] limit order failed: %s", e)
        return {"ok": False, "error": str(e)}


# ===================== Stop-Market (SL) =====================
def place_stop_market_safe(
    *,
    symbol: str,
    side: str,
    quantity: str,
    stop_price: str,
    reduce_only: bool = True,
    position_side: str = "BOTH",
) -> Dict[str, Any]:
    try:
        res = futures_create_order(
            symbol=symbol,
            side=side,
            type="STOP_MARKET",
            quantity=quantity,
            stopPrice=stop_price,
            reduceOnly=reduce_only,
            positionSide=position_side,
        )
        return {"ok": True, "data": res}
    except Exception as e:
        logger.error("[order_hygiene] stop-market failed: %s", e)
        return {"ok": False, "error": str(e)}


# ===================== Take-Profit =====================
def place_take_profit_safe(
    *,
    symbol: str,
    side: str,
    quantity: str,
    tp_price: str,
    reduce_only: bool = True,
    position_side: str = "BOTH",
) -> Dict[str, Any]:
    try:
        res = futures_create_order(
            symbol=symbol,
            side=side,
            type="TAKE_PROFIT_MARKET",
            quantity=quantity,
            stopPrice=tp_price,
            reduceOnly=reduce_only,
            positionSide=position_side,
        )
        return {"ok": True, "data": res}
    except Exception as e:
        logger.error("[order_hygiene] take-profit failed: %s", e)
        return {"ok": False, "error": str(e)}


__all__ = [
    "check_minimums",
    "cancel_if_conflict",
    "place_limit_order_safe",
    "place_stop_market_safe",
    "place_take_profit_safe",
]






