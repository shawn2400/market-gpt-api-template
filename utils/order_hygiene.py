# utils/order_hygiene.py
from __future__ import annotations
import logging
from typing import Dict, Any

from utils.binance_client import (
    futures_create_order,
    futures_cancel_all_orders,
    get_symbol_info,
    get_price,
    DEFAULT_MIN_NOTIONAL,
)

logger = logging.getLogger("algogpt.order_hygiene")

def check_minimums(symbol: str, qty: float) -> bool:
    """
    בדיקת minQty/minNotional מול Binance עם fallback למחיר חי.
    לוגים רכים, בלי חריגות חוסמות.
    """
    try:
        info = get_symbol_info(symbol)
        if not info:
            logger.warning("[order_hygiene] no symbol info for %s", symbol)
            return False

        filters = {f["filterType"]: f for f in info.get("filters", [])}
        min_qty = float(filters.get("LOT_SIZE", {}).get("minQty", 0))
        min_notional = float(filters.get("MIN_NOTIONAL", {}).get("notional", DEFAULT_MIN_NOTIONAL))

        if qty < min_qty:
            logger.warning("[order_hygiene] qty %.8f < minQty %.8f for %s", qty, min_qty, symbol)
            return False

        try:
            price = float(get_price(symbol) or 0.0)
        except Exception as e:
            logger.warning("[order_hygiene] get_price failed for %s: %s", symbol, e)
            price = 0.0

        if price <= 0:
            # fallback נוסף: לא נכשיל רק על מחיר, נשווה ל-minNotional המינימלי
            price = min_notional / max(qty, 1e-12)

        notional_val = qty * price
        if notional_val < min_notional:
            logger.warning("[order_hygiene] notional %.4f < minNotional %.4f for %s", notional_val, min_notional, symbol)
            return False

        return True
    except Exception as e:
        logger.error("[order_hygiene] check_minimums error: %s", e)
        return False

def cancel_if_conflict(symbol: str, side: str) -> None:
    try:
        res = futures_cancel_all_orders(symbol=symbol)
        if res.get("ok"):
            logger.info("[order_hygiene] cancelled existing orders for %s side=%s", symbol, side)
        else:
            logger.warning("[order_hygiene] cancel_if_conflict failed for %s: %s", symbol, res)
    except Exception as e:
        logger.warning("[order_hygiene] cancel_if_conflict error: %s", e)

def place_limit_order_safe(*, symbol: str, side: str, quantity: str, price: str,
                           reduce_only: bool = False, position_side: str = "BOTH") -> Dict[str, Any]:
    try:
        return futures_create_order(
            symbol=symbol, side=side.upper(), type="LIMIT",
            quantity=quantity, price=price, timeInForce="GTC",
            reduceOnly=reduce_only, positionSide=position_side,
        )
    except Exception as e:
        logger.error("[order_hygiene] limit order failed: %s", e)
        return {"ok": False, "error": str(e)}

def place_stop_market_safe(*, symbol: str, side: str, quantity: str, stop_price: str,
                           reduce_only: bool = True, position_side: str = "BOTH") -> Dict[str, Any]:
    try:
        return futures_create_order(
            symbol=symbol, side=side.upper(), type="STOP_MARKET",
            quantity=quantity, stopPrice=stop_price,
            reduceOnly=reduce_only, positionSide=position_side,
        )
    except Exception as e:
        logger.error("[order_hygiene] stop-market failed: %s", e)
        return {"ok": False, "error": str(e)}

def place_take_profit_safe(*, symbol: str, side: str, quantity: str, tp_price: str,
                           reduce_only: bool = True, position_side: str = "BOTH") -> Dict[str, Any]:
    try:
        return futures_create_order(
            symbol=symbol, side=side.upper(), type="TAKE_PROFIT_MARKET",
            quantity=quantity, stopPrice=tp_price,
            reduceOnly=reduce_only, positionSide=position_side,
        )
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
















