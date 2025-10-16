# utils/order_hygiene.py
from __future__ import annotations
import logging
from typing import Dict, Any, Tuple, List

from utils.binance_client import (
    futures_create_order,
    futures_cancel_all_orders,
    get_symbol_info,
    get_price,
    DEFAULT_MIN_NOTIONAL,
)

logger = logging.getLogger("algogpt.order_hygiene")


def _extract_filters(info: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {f.get("filterType", ""): f for f in (info or {}).get("filters", [])}


def _min_checks(symbol: str, qty: float, price: float) -> Tuple[bool, str]:
    try:
        info = get_symbol_info(symbol) or {}
        f = _extract_filters(info)
        min_qty = float(f.get("LOT_SIZE", {}).get("minQty", 0.0))
        min_notional = float(f.get("MIN_NOTIONAL", {}).get("notional", DEFAULT_MIN_NOTIONAL))
    except Exception:
        min_qty = 0.0
        min_notional = DEFAULT_MIN_NOTIONAL

    if qty <= 0:
        return False, "qty<=0"
    if min_qty and qty < min_qty:
        return False, f"qty<{min_qty}"
    notion = qty * max(1e-12, price)
    if notion < min_notional:
        return False, f"notional<{min_notional}"
    return True, "ok"


def check_minimums(symbol: str, qty: float) -> bool:
    """
    בדיקת minQty/minNotional מול Binance עם fallback למחיר חי.
    לוגים רכים, בלי חריגות חוסמות.
    """
    try:
        try:
            px = float(get_price(symbol) or 0.0)
        except Exception as e:
            logger.warning("[order_hygiene] get_price failed for %s: %s", symbol, e)
            px = 0.0
        # אם אין מחיר – נשתמש ב-minNotional כדי לייצר אומדן
        if px <= 0:
            info = get_symbol_info(symbol) or {}
            f = _extract_filters(info)
            min_notional = float(f.get("MIN_NOTIONAL", {}).get("notional", DEFAULT_MIN_NOTIONAL))
            px = max(1e-12, min_notional / max(qty, 1e-12))

        ok, reason = _min_checks(symbol, float(qty), float(px))
        if not ok:
            logger.warning("[order_hygiene] min_check_failed %s qty=%.12f price=%.12f (%s)", symbol, qty, px, reason)
        return bool(ok)
    except Exception as e:
        logger.error("[order_hygiene] check_minimums error: %s", e)
        return False


def cancel_if_conflict(symbol: str, side: str) -> None:
    """
    ביטול כל ההזמנות הפתוחות לסימבול—פשוט ובטוח.
    """
    try:
        res = futures_cancel_all_orders(symbol=symbol)
        if isinstance(res, dict) and res.get("ok"):
            logger.info("[order_hygiene] cancelled existing orders for %s side=%s", symbol, side)
        else:
            logger.warning("[order_hygiene] cancel_if_conflict returned: %s", res)
    except Exception as e:
        logger.warning("[order_hygiene] cancel_if_conflict error: %s", e)


def place_limit_order_safe(
    *, symbol: str, side: str, quantity: str, price: str, reduce_only: bool = False, position_side: str = "BOTH"
) -> Dict[str, Any]:
    try:
        return futures_create_order(
            symbol=symbol.upper(),
            side=side.upper(),
            type="LIMIT",
            quantity=quantity,
            price=price,
            timeInForce="GTC",
            reduceOnly=bool(reduce_only),
            positionSide=position_side,
        )
    except Exception as e:
        logger.error("[order_hygiene] limit order failed: %s", e)
        return {"ok": False, "error": str(e)}


def place_stop_market_safe(
    *, symbol: str, side: str, quantity: str, stop_price: str, reduce_only: bool = True, position_side: str = "BOTH"
) -> Dict[str, Any]:
    try:
        # ב־Futures עדיף STOP רגיל עם price=stopPrice (חלק מהספריות)
        return futures_create_order(
            symbol=symbol.upper(),
            side=side.upper(),
            type="STOP",
            quantity=quantity,
            stopPrice=stop_price,
            price=stop_price,
            timeInForce="GTC",
            reduceOnly=bool(reduce_only),
            positionSide=position_side,
        )
    except Exception as e:
        logger.error("[order_hygiene] stop-market failed: %s", e)
        return {"ok": False, "error": str(e)}


def place_take_profit_safe(
    *, symbol: str, side: str, quantity: str, tp_price: str, reduce_only: bool = True, position_side: str = "BOTH"
) -> Dict[str, Any]:
    try:
        return futures_create_order(
            symbol=symbol.upper(),
            side=side.upper(),
            type="TAKE_PROFIT",
            quantity=quantity,
            stopPrice=tp_price,
            price=tp_price,
            timeInForce="GTC",
            reduceOnly=bool(reduce_only),
            positionSide=position_side,
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















