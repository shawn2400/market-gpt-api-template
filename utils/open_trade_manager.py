# utils/open_trade_manager.py
from __future__ import annotations
import logging
from typing import Any, Dict, List

from utils.order_hygiene import (
    place_limit_order_safe,
    place_stop_market_safe,
    place_take_profit_safe,
    cancel_if_conflict,
    check_minimums,
)

logger = logging.getLogger("algogpt.open_trade_manager")


# ===================== Core Trade Management =====================
def manage_open_trades(
    symbol: str,
    side: str,
    qty: float,
    entry_price: float,
    sl_price: float,
    tp_price: float,
    *,
    leverage: int = 10,
    position_side: str = "BOTH",
) -> Dict[str, Any]:
    """
    מנהל פתיחת טרייד עם SL ו־TP אוטומטיים.
    """
    logger.info(
        "[open_trade_manager] Starting manage_open_trades: %s side=%s qty=%s entry=%s SL=%s TP=%s lev=%s",
        symbol,
        side,
        qty,
        entry_price,
        sl_price,
        tp_price,
        leverage,
    )

    # ביטול קונפליקטים
    cancel_if_conflict(symbol, side)

    # בדיקה מול מינימום ביננס
    if not check_minimums(symbol, qty):
        return {"ok": False, "error": "below_minimum_notional_or_qty"}

    # 1. פקודת Limit לכניסה
    entry = place_limit_order_safe(
        symbol=symbol,
        side=side,
        quantity=str(qty),
        price=str(entry_price),
        reduce_only=False,
        position_side=position_side,
    )
    if not entry.get("ok"):
        return {"ok": False, "error": f"entry_failed: {entry.get('error')}"}

    # 2. פקודת Stop-Market ל־SL
    sl = place_stop_market_safe(
        symbol=symbol,
        side="SELL" if side.upper() == "BUY" else "BUY",
        quantity=str(qty),
        stop_price=str(sl_price),
        reduce_only=True,
        position_side=position_side,
    )
    if not sl.get("ok"):
        return {"ok": False, "error": f"sl_failed: {sl.get('error')}"}

    # 3. פקודת Take-Profit ל־TP
    tp = place_take_profit_safe(
        symbol=symbol,
        side="SELL" if side.upper() == "BUY" else "BUY",
        quantity=str(qty),
        tp_price=str(tp_price),
        reduce_only=True,
        position_side=position_side,
    )
    if not tp.get("ok"):
        return {"ok": False, "error": f"tp_failed: {tp.get('error')}"}

    return {
        "ok": True,
        "entry": entry,
        "sl": sl,
        "tp": tp,
    }


# ===================== Batch Manager =====================
def bulk_manage_trades(trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    מנהל מספר טריידים ברצף (batch).
    """
    results = []
    for t in trades:
        try:
            res = manage_open_trades(
                t["symbol"],
                t["side"],
                float(t["qty"]),
                float(t["entry_price"]),
                float(t["sl_price"]),
                float(t["tp_price"]),
                leverage=int(t.get("leverage", 10)),
                position_side=t.get("position_side", "BOTH"),
            )
            results.append(res)
        except Exception as e:
            logger.error("bulk_manage_trades error on %s: %s", t, e)
            results.append({"ok": False, "error": str(e), "trade": t})
    return results


__all__ = [
    "manage_open_trades",
    "bulk_manage_trades",
]









