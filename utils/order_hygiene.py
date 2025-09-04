# utils/order_hygiene.py
from __future__ import annotations
import logging
from typing import Dict, Any

from utils.binance_client import (
    futures_create_order,
    futures_cancel_all_orders,
    get_symbol_info,
    futures_mark_price,
    DEFAULT_MIN_NOTIONAL,
)

logger = logging.getLogger("algogpt.order_hygiene")


# ===================== בדיקת מינימוםים =====================
def check_minimums(symbol: str, qty: float) -> tuple[bool, str]:
    """
    בדיקה אם הכמות עומדת בדרישות Binance (minQty, minNotional).
    מחזיר (True/False, reason).
    """
    try:
        info = get_symbol_info(symbol)
        if not info:
            return False, f"no_symbol_info:{symbol}"

        filters = {f["filterType"]: f for f in info.get("filters", [])}

        # --- מינימום כמות ---
        min_qty = float(filters.get("LOT_SIZE", {}).get("minQty", 0))
        if qty < min_qty:
            return False, f"qty {qty} < minQty {min_qty}"

        # --- מינימום ערך עסקה ---
        min_notional = float(filters.get("MIN_NOTIONAL", {}).get("notional", DEFAULT_MIN_NOTIONAL))
        price = futures_mark_price(symbol) or 0.0
        notional_val = qty * price

        if notional_val < min_notional:
            return False, f"notional {notional_val:.4f} < minNotional {min_notional}"

        return True, "ok"
    except Exception as e:
        logger.error("[order_hygiene] check_minimums error: %s", e)
        return False, f"exception:{e}"


# ===================== ביטול קונפליקטים =====================
def cancel_if_conflict(symbol: str, side: str) -> None:
    """
    מבטל הוראות פתוחות קודמות שיכולות להתנגש בכניסה החדשה.
    """
    try:
        res = futures_cancel_all_orders(symbol=symbol)
        if res.get("ok"):
            logger.info("[order_hygiene] cancelled existing orders for %s side=%s", symbol, side)
        else:
            logger.warning("[order_hygiene] cancel_if_conflict failed for %s: %s", symbol, res)
    except Exception as e:
        logger.warning("[order_hygiene] cancel_if_conflict error: %s", e)


# ===================== Limit Order =====================
def place_limit_order_safe(
    *, symbol: str, side: str, quantity: str, price: str,
    reduce_only: bool = False, position_side: str = "BOTH"
) -> Dict[str, Any]:
    try:
        return futures_create_order(
            symbol=symbol,
            side=side.upper(),
            type="LIMIT",
            quantity=quantity,
            price=price,
            timeInForce="GTC",
            reduceOnly=reduce_only,
            positionSide=position_side,
        )
    except Exception as e:
        logger.error("[order_hygiene] limit order failed: %s", e)
        return {"ok": False, "error": str(e)}


# ===================== Stop-Market (SL) =====================
def place_stop_market_safe(
    *, symbol: str, side: str, quantity: str, stop_price: str,
    reduce_only: bool = True, position_side: str = "BOTH"
) -> Dict[str, Any]:
    try:
        return futures_create_order(
            symbol=symbol,
            side=side.upper(),
            type="STOP_MARKET",
            quantity=quantity,
            stopPrice=stop_price,
            reduceOnly=reduce_only,
            positionSide=position_side,
        )
    except Exception as e:
        logger.error("[order_hygiene] stop-market failed: %s", e)
        return {"ok": False, "error": str(e)}


# ===================== Take-Profit =====================
def place_take_profit_safe(
    *, symbol: str, side: str, quantity: str, tp_price: str,
    reduce_only: bool = True, position_side: str = "BOTH"
) -> Dict[str, Any]:
    try:
        return futures_create_order(
            symbol=symbol,
            side=side.upper(),
            type="TAKE_PROFIT_MARKET",
            quantity=quantity,
            stopPrice=tp_price,
            reduceOnly=reduce_only,
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














