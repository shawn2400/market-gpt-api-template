# utils/order_hygiene.py
from __future__ import annotations
import logging
from typing import Dict, Any, Optional, Tuple

from utils.binance_client import (
    get_symbol_filters,
    cancel_order,
    DEFAULT_MIN_NOTIONAL,
)

from utils.precision_utils import (
    apply_price_tick,
    apply_price_tick_side,
    apply_qty_step,
    calc_quantity_from_budget,
)

logger = logging.getLogger("algogpt.order_hygiene")

# ============================
# Order Validation & Cleanup
# ============================

def validate_order_payload(
    symbol: str,
    side: str,
    price: Optional[float],
    qty: Optional[float],
    budget_usd: Optional[float] = None,
    leverage: float = 1.0,
) -> Dict[str, Any]:
    """
    מבצע ניקוי ובדיקות ל־Order לפני שליחה ל־Binance.
    - מיישם tickSize/stepSize
    - מוודא MIN_NOTIONAL
    - מאפשר חישוב כמות מתוך budget
    """
    side = (side or "").upper()
    if side not in ("BUY", "SELL"):
        return {"ok": False, "reason": "bad_side", "side": side}

    filters = get_symbol_filters(symbol)
    if not filters:
        return {"ok": False, "reason": "no_filters"}

    # מחיר
    price_out, price_str = (None, None)
    if price is not None:
        if side == "BUY":
            price_out, price_str = apply_price_tick_side(price, symbol, "BUY")
        else:
            price_out, price_str = apply_price_tick_side(price, symbol, "SELL")

    # כמות
    qty_out, qty_str = (None, None)
    if qty is not None:
        qty_out, qty_str = apply_qty_step(qty, symbol)
    elif budget_usd is not None and price_out:
        qres = calc_quantity_from_budget(symbol, price=price_out, budget_usd=budget_usd, leverage=leverage)
        if not qres.get("ok"):
            return {"ok": False, "reason": qres.get("reason", "budget_fail")}
        qty_out, qty_str = qres["qty"], qres["qty_str"]

    if not qty_out or qty_out <= 0:
        return {"ok": False, "reason": "bad_qty"}

    # בדיקת מינימום notional
    notional = (price_out or 0) * qty_out
    min_notional = filters.get("min_notional") or DEFAULT_MIN_NOTIONAL
    if notional < min_notional:
        return {
            "ok": False,
            "reason": "below_min_notional",
            "notional": notional,
            "min_notional": min_notional,
        }

    return {
        "ok": True,
        "symbol": symbol,
        "side": side,
        "price": price_out,
        "price_str": price_str,
        "qty": qty_out,
        "qty_str": qty_str,
        "notional": notional,
    }

# ============================
# Cancel Helpers
# ============================

def safe_cancel(symbol: str, order_id: int) -> bool:
    """
    מנסה לבטל הזמנה, עם לוג.
    """
    try:
        return cancel_order(symbol, order_id)
    except Exception as e:
        logger.error(f"[order_hygiene] cancel failed {symbol} {order_id}: {e}")
        return False

# ============================
# Batch Validation
# ============================

def validate_orders_batch(orders: list[dict]) -> list[dict]:
    """
    מקבל רשימת payloads ומחזיר תוצאות אחרי וידוא.
    """
    results = []
    for o in orders:
        res = validate_order_payload(
            o.get("symbol"),
            o.get("side"),
            o.get("price"),
            o.get("qty"),
            o.get("budget_usd"),
            o.get("leverage", 1.0),
        )
        results.append(res)
    return results

__all__ = [
    "validate_order_payload",
    "validate_orders_batch",
    "safe_cancel",
]




