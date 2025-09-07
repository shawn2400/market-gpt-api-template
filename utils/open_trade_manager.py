# utils/open_trade_manager.py
from __future__ import annotations
import logging
from typing import Any, Dict, List, Tuple

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
    ניהול טרייד פתוח כולל Entry + SL + TP
    עם בדיקות מינימום וניקוי קונפליקטים קיימים.
    """
    logger.info(
        {
            "event": "manage_open_trades_start",
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "entry": entry_price,
            "sl": sl_price,
            "tp": tp_price,
            "leverage": leverage,
        }
    )

    # ביטול פקודות קודמות לאותו סימבול
    cancel_if_conflict(symbol, side)

    # בדיקת מינימום Binance
    ok, reason = check_minimums(symbol, qty)
    if not ok:
        msg = f"min_check_failed: {reason}"
        logger.warning({"event": "trade_rejected", "reason": msg})
        return {"ok": False, "error": msg}

    # שלב 1: Limit Entry
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

    # שלב 2: Stop-Market (SL)
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

    # שלב 3: Take-Profit (TP)
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

    logger.info(
        {"event": "manage_open_trades_success", "symbol": symbol, "entry_id": entry.get("orderId")}
    )
    return {
        "ok": True,
        "entry": entry,
        "sl": sl,
        "tp": tp,
    }


# ===================== Batch Manager =====================
def bulk_manage_trades(trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    ניהול מספר טריידים ברצף (batch).
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
            logger.error({"event": "bulk_manage_error", "trade": t, "error": str(e)})
            results.append({"ok": False, "error": str(e), "trade": t})
    return results


__all__ = [
    "manage_open_trades",
    "bulk_manage_trades",
]









