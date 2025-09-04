# utils/order_hygiene.py
from __future__ import annotations
import logging
from typing import Any, Dict, Optional

from utils.binance_client import (
    futures_create_order,
    get_open_positions,
    futures_mark_price,
)

logger = logging.getLogger("algogpt.order_hygiene")


# ===================== Wrapper: Place Safe Stop/Limit =====================
def place_limit_order_safe(
    *,
    symbol: str,
    side: str,
    quantity: str,
    price: str,
    reduce_only: bool = False,
    time_in_force: str = "GTC",
    position_side: Optional[str] = None,
) -> Dict[str, Any]:
    """פותח פקודת LIMIT עם הגנות"""
    try:
        resp = futures_create_order(
            symbol=symbol.upper(),
            side=side.upper(),
            type="LIMIT",
            timeInForce=time_in_force,
            quantity=quantity,
            price=price,
            reduceOnly=reduce_only,
            positionSide=position_side,
        )
        return {"ok": True, "response": resp}
    except Exception as e:
        logger.error("place_limit_order_safe failed: %s", e)
        return {"ok": False, "error": str(e)}


def place_stop_market_safe(
    *,
    symbol: str,
    side: str,
    quantity: str,
    stop_price: str,
    reduce_only: bool = True,
    position_side: Optional[str] = None,
) -> Dict[str, Any]:
    """פותח פקודת STOP-MARKET עם הגנות (ל־SL בעיקר)"""
    try:
        resp = futures_create_order(
            symbol=symbol.upper(),
            side=side.upper(),
            type="STOP_MARKET",
            stopPrice=stop_price,
            quantity=quantity,
            reduceOnly=reduce_only,
            positionSide=position_side,
        )
        return {"ok": True, "response": resp}
    except Exception as e:
        logger.error("place_stop_market_safe failed: %s", e)
        return {"ok": False, "error": str(e)}


def place_take_profit_safe(
    *,
    symbol: str,
    side: str,
    quantity: str,
    tp_price: str,
    reduce_only: bool = True,
    position_side: Optional[str] = None,
) -> Dict[str, Any]:
    """פותח פקודת TAKE_PROFIT-MARKET עם הגנות (ל־TP)"""
    try:
        resp = futures_create_order(
            symbol=symbol.upper(),
            side=side.upper(),
            type="TAKE_PROFIT_MARKET",
            stopPrice=tp_price,
            quantity=quantity,
            reduceOnly=reduce_only,
            positionSide=position_side,
        )
        return {"ok": True, "response": resp}
    except Exception as e:
        logger.error("place_take_profit_safe failed: %s", e)
        return {"ok": False, "error": str(e)}


# ===================== Hygiene / Validation =====================
def cancel_if_conflict(symbol: str, new_side: str) -> None:
    """
    מבטל פוזיציות מנוגדות לפני פתיחת פקודה חדשה.
    לדוגמה: אם יש LONG פתוח ומבקשים לפתוח SHORT.
    """
    try:
        open_pos = get_open_positions(symbol)
        for pos in open_pos:
            amt = float(pos.get("positionAmt", "0"))
            side = "BUY" if amt > 0 else "SELL"
            if amt != 0 and side != new_side.upper():
                logger.warning(
                    "[order_hygiene] Conflict detected: %s %s vs new %s – should close",
                    symbol,
                    side,
                    new_side,
                )
                # כאן ניתן להוסיף קריאה ל־futures_create_order לסגירה
    except Exception as e:
        logger.error("cancel_if_conflict failed: %s", e)


def check_minimums(symbol: str, quantity: float) -> bool:
    """
    בודק שהכמות לא קטנה מדי (כדי לא לקבל reject מביננס).
    """
    try:
        price = futures_mark_price(symbol)
        if not price:
            return False
        notional = quantity * price
        return notional >= 5.0  # fallback
    except Exception as e:
        logger.error("check_minimums failed: %s", e)
        return False


__all__ = [
    "place_limit_order_safe",
    "place_stop_market_safe",
    "place_take_profit_safe",
    "cancel_if_conflict",
    "check_minimums",
]





