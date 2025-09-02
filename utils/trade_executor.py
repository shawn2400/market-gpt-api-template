# utils/trade_executor.py
from __future__ import annotations
import os
import logging
from typing import Any, Dict, Optional

from utils.binance_client import (
    futures_mark_price,
    set_leverage,
    place_limit_order,
    place_stop_market,
    place_take_profit_market,
)
from utils.precision_utils import apply_price_tick_side, calc_quantity_from_budget

logger = logging.getLogger("algogpt.trade_executor")

EXECUTE_TRADES = str(os.getenv("EXECUTE_TRADES", "false")).lower() in ("1", "true", "yes", "on")

def _safe_mark_or_entry(symbol: str, entry_price: Optional[float]) -> float:
    px = float(entry_price) if (entry_price and entry_price > 0) else (futures_mark_price(symbol) or 0.0)
    if px <= 0:
        raise RuntimeError(f"Price unavailable for {symbol}")
    return px

def _close_side(side: str) -> str:
    return "SELL" if side.upper() == "LONG" or side.upper() == "BUY" else "BUY"

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
    חובה SL/TP. אם חסר – לא מבצעים.
    LIVE: אחרי שהכניסה בוצעה (IOC) – מצמידים מייד SL/TP כ-Reduce-Only.
    אם יצירת ה-SL/TP נכשלת → סגירה מיידית של הכמות שנכנסה (Fail-Safe) והחזרת error.
    """
    sym = (symbol or "").strip().upper()
    side_up = (side or "").strip().upper()

    # חובה רמות
    if sl is None or tp is None:
        return {"ok": False, "error": "missing SL/TP (hard requirement)"}
    if side_up not in ("BUY", "SELL", "LONG", "SHORT"):
        return {"ok": False, "error": "side must be LONG/SHORT (or BUY/SELL)"}

    # מחיר בסיס → יישור ל-tick לפי כיוון
    try:
        base_px = _safe_mark_or_entry(sym, entry)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    px_aligned, _ = apply_price_tick_side(base_px, sym, "BUY" if side_up in ("BUY", "LONG") else "SELL")

    # כמות
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

    # DRY-RUN
    if dry_run or not EXECUTE_TRADES:
        return {
            "mode": "dry_run",
            "ok": True,
            "symbol": sym,
            "side": side_up,
            "entry": float(px_aligned),
            "sl": float(sl),
            "tp": float(tp),
            "leverage": int(leverage),
            "budget": float(budget),
            "quantity": float(qty_calc),
        }

    # LIVE
    try:
        try:
            set_leverage(sym, int(leverage))
        except Exception as e:
            logger.debug(f"set_leverage({sym},{leverage}) failed: {e}")

        # 1) כניסה IOC (market-like)
        order = place_limit_order(
            symbol=sym,
            side="BUY" if side_up in ("BUY", "LONG") else "SELL",
            quantity=float(qty_calc),
            price=float(px_aligned),
            time_in_force="IOC",
            post_only=False,
            reduce_only=False,
            position_side=None,
            new_order_resp_type="RESULT",
        )

        status = (order or {}).get("status", "").upper()
        filled = float(order.get("executedQty") or order.get("cumQty") or 0.0)
        px_fill = float(order.get("avgPrice") or order.get("price") or px_aligned)

        if filled <= 0.0 or status in ("EXPIRED", "CANCELED", "REJECTED"):
            # לא נכנס כלום → אין מה להצמיד
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
                "quantity": float(qty_calc),
                "order": order,
                "error": f"entry not filled (status={status}, filled={filled})",
            }

        # 2) מצמידים ברקט (Reduce-Only) על הכמות שנכנסה בפועל
        try:
            close_side = _close_side(side_up)
            # SL
            place_stop_market(sym, close_side, float(sl), float(filled), reduce_only=True)
            # TP
            place_take_profit_market(sym, close_side, float(tp), float(filled), reduce_only=True)

        except Exception as e_bracket:
            logger.exception("failed to attach SL/TP, trying to fail-safe close")
            # Fail-Safe: אם לא הצליח להצמיד SL/TP – נסגור מיד את הכמות
            try:
                # סוגרים בכיוון ההפוך ב-IOC אגרסיבי (מחוץ לספר) כדי להתאפס
                from utils.binance_trader import force_close_position  # אם קיים
                force_close_position(sym)
            except Exception:
                pass
            return {
                "mode": "live_direct",
                "ok": False,
                "symbol": sym,
                "side": side_up,
                "entry": float(px_fill),
                "sl": float(sl),
                "tp": float(tp),
                "leverage": int(leverage),
                "budget": float(budget),
                "filledQty": float(filled),
                "order": order,
                "error": f"failed to attach SL/TP: {e_bracket}",
            }

        # הצליח הכול
        return {
            "mode": "live_direct",
            "ok": True,
            "symbol": sym,
            "side": side_up,
            "entry": float(px_fill),
            "sl": float(sl),
            "tp": float(tp),
            "leverage": int(leverage),
            "budget": float(budget),
            "filledQty": float(filled),
            "order": order,
            "bracket": {"reduce_only": True, "workingType": "MARK_PRICE"},
        }

    except Exception as e:
        logger.exception("execute_trade_live failed")
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

























































