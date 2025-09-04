# utils/trade_executor.py
from __future__ import annotations
import logging
from typing import Dict, Any, Optional

from utils.binance_client import (
    futures_create_order,
    futures_mark_price,
    set_leverage,
)

logger = logging.getLogger("algogpt.trade_executor")


# ===================== Live Trade Execution =====================
def execute_trade_live(
    *,
    symbol: str,
    side: str,
    budget: float,
    leverage: int = 10,
    sl: Optional[float] = None,
    tp: Optional[float] = None,
    position_side: str = "BOTH",
    reduce_only: bool = False,
) -> Dict[str, Any]:
    """
    פותח טרייד אמיתי ב־Binance Futures כולל SL/TP אם מוגדרים.
    """

    try:
        # 1. מחיר עדכני
        mark = futures_mark_price(symbol)
        if not mark:
            return {"ok": False, "error": f"mark_price_unavailable for {symbol}"}

        # 2. חישוב כמות
        qty = round((budget * leverage) / mark, 6)  # נשתמש בדיוק עד 6 ספרות

        # 3. עדכון מינוף
        lev_res = set_leverage(symbol, leverage)
        if not lev_res.get("ok"):
            logger.warning("[trade_executor] leverage set failed: %s", lev_res)

        # 4. פקודת Market לכניסה
        entry = futures_create_order(
            symbol=symbol,
            side=side.upper(),
            type="MARKET",
            quantity=str(qty),
            reduceOnly=reduce_only,
            positionSide=position_side,
        )
        if not entry.get("ok", True):  # אם יש עטיפה עם {"ok": False}
            return {"ok": False, "error": entry.get("error", "entry_failed")}

        order_id = entry.get("orderId")

        result = {
            "ok": True,
            "symbol": symbol,
            "side": side.upper(),
            "entry": entry,
            "qty": qty,
            "price": mark,
            "sl": None,
            "tp": None,
        }

        # 5. פקודת Stop-Loss
        if sl:
            sl_order = futures_create_order(
                symbol=symbol,
                side="SELL" if side.upper() == "BUY" else "BUY",
                type="STOP_MARKET",
                quantity=str(qty),
                stopPrice=str(sl),
                reduceOnly=True,
                positionSide=position_side,
            )
            result["sl"] = sl_order

        # 6. פקודת Take-Profit
        if tp:
            tp_order = futures_create_order(
                symbol=symbol,
                side="SELL" if side.upper() == "BUY" else "BUY",
                type="TAKE_PROFIT_MARKET",
                quantity=str(qty),
                stopPrice=str(tp),
                reduceOnly=True,
                positionSide=position_side,
            )
            result["tp"] = tp_order

        logger.info("[trade_executor] executed trade: %s", result)
        return result

    except Exception as e:
        logger.error("[trade_executor] execution error: %s", e)
        return {"ok": False, "error": str(e)}


__all__ = [
    "execute_trade_live",
]




























































