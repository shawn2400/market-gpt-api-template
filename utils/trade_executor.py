# utils/trade_executor.py
from __future__ import annotations

import os
import logging
from typing import Any, Dict, Optional

from utils.binance_client import (
    futures_mark_price,
    set_leverage,
    place_limit_order,
)
from utils.precision_utils import (
    apply_price_tick_side,
    calc_quantity_from_budget,
)

logger = logging.getLogger("algogpt.trade_executor")

# הפעלה בפועל או Dry-Run
EXECUTE_TRADES = str(os.getenv("EXECUTE_TRADES", "false")).lower() in ("1", "true", "yes", "on")

# אופציונלית: שימוש במימוש ההיסטורי (אם תרצה להכריח: export USE_BINANCE_TRADER=true)
_USE_BINANCE_TRADER = str(os.getenv("USE_BINANCE_TRADER", "false")).lower() in ("1", "true", "yes", "on")
_binance_trader_available = False
try:
    from utils.binance_trader import binance_futures_trade  # type: ignore
    _binance_trader_available = True
except Exception:
    _binance_trader_available = False


def _safe_mark_or_entry(symbol: str, entry_price: Optional[float]) -> float:
    px = float(entry_price) if (entry_price and entry_price > 0) else (futures_mark_price(symbol) or 0.0)
    if px <= 0:
        raise RuntimeError(f"Price unavailable for {symbol}")
    return px


async def execute_trade_live(
    *,
    symbol: str,
    side: str,
    budget: float,
    leverage: int,
    entry: float,
    sl: float,
    tp: float,
    dry_run: bool = True,
    quantity: Optional[float] = None,
) -> Dict[str, Any]:
    """
    מבצע טרייד FUTURES:
      - אם dry_run או EXECUTE_TRADES=false → החזרת תוצאה סימולטיבית (עם כמות מחושבת אם לא נמסרה).
      - אחרת → קובע מינוף (Best-effort), ומבצע הזמנת LIMIT-IOC (Market-like עם דיוק מלא).
    """
    sym = (symbol or "").strip().upper()
    side_up = (side or "").strip().upper()
    if side_up not in ("BUY", "SELL"):
        return {"ok": False, "error": "side must be BUY or SELL"}

    # מחיר בסיס (entry או Mark) → עיגון לפי כיוון
    try:
        base_px = _safe_mark_or_entry(sym, entry)
    except Exception as e:
        return {"ok": False, "error": str(e)}

    px_aligned, _ = apply_price_tick_side(base_px, sym, side_up)

    # כמות: אם לא סופקה → חישוב מתקציב×מינוף עם אכיפת מינימוםים
    qty_calc: Optional[float] = quantity
    if qty_calc is None:
        q = calc_quantity_from_budget(sym, price=px_aligned, budget_usd=float(budget), leverage=float(leverage))
        if not q.get("ok"):
            return {
                "mode": "dry_run" if (dry_run or not EXECUTE_TRADES) else "live_failed",
                "ok": False,
                "symbol": sym,
                "side": side_up,
                "entry": float(px_aligned),
                "sl": float(sl),
                "tp": float(tp),
                "leverage": int(leverage),
                "budget": float(budget),
                "quantity": None,
                "error": q.get("reason") or "quantity_calc_failed",
                "hint": q.get("min_notional"),
            }
        qty_calc = float(q["qty"])

    # DRY-RUN → נחזיר חיווי מלא
    if dry_run or not EXECUTE_TRADES:
        return {
            "mode": "dry_run",
            "symbol": sym,
            "side": side_up,
            "entry": float(px_aligned),
            "sl": float(sl),
            "tp": float(tp),
            "leverage": int(leverage),
            "budget": float(budget),
            "quantity": float(qty_calc) if qty_calc is not None else None,
            "ok": True,
        }

    # LIVE: שימוש ב-Legacy אם הופעל
    if _USE_BINANCE_TRADER and _binance_trader_available:
        try:
            res = await binance_futures_trade(  # type: ignore
                symbol=sym,
                side=side_up,
                budget=float(budget),
                leverage=int(leverage),
                dry_run=False,
            )
            return {"mode": "live_legacy", "ok": True, **res}
        except Exception as e:
            logger.exception("legacy binance_futures_trade failed")
            return {"mode": "live_legacy", "ok": False, "error": str(e)}

    # LIVE: ביצוע ישיר דרך הלקוח (LIMIT-IOC) עם יישור Precision
    try:
        # סט לוורידג' (Best effort)
        try:
            set_leverage(sym, int(leverage))
        except Exception as e:
            logger.debug(f"set_leverage({sym},{leverage}) failed: {e}")

        order = place_limit_order(
            symbol=sym,
            side=side_up,
            quantity=float(qty_calc),
            price=float(px_aligned),
            time_in_force="IOC",
            post_only=False,
            reduce_only=False,
            position_side=None,
            new_order_resp_type="RESULT",
        )
        return {
            "mode": "live_direct",
            "ok": True,
            "symbol": sym,
            "side": side_up,
            "entry": float(px_aligned),
            "sl": float(sl),
            "tp": float(tp),
            "leverage": int(leverage),
            "budget": float(budget),
            "quantity": float(qty_calc),
            "order": order,
        }
    except Exception as e:
        logger.exception("place_limit_order failed")
        return {
            "mode": "live_direct",
            "ok": False,
            "symbol": sym,
            "side": side_up,
            "entry": float(px_aligned),
            "sl": float(sl),
            "tp": float(tp),
            "leverage": int(leverage),
            "budget": float(budget),
            "quantity": float(qty_calc) if qty_calc is not None else None,
            "error": str(e),
        }
























































