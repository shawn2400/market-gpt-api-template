# utils/trade_executor.py
from __future__ import annotations

import os
import logging
from typing import Any, Dict, Optional
from decimal import Decimal, ROUND_DOWN, ROUND_UP

from utils.binance_client import (
    futures_mark_price,
    get_symbol_filters,
    set_leverage,
    place_limit_order,
    _quantize_multiple,
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


def _d(x) -> Decimal:
    return Decimal(str(x))


def _round_price_for_side(entry_price: float, tick_str: str, side: str) -> Decimal:
    """
    עיגון מחיר לפי tickSize:
      - BUY → ROUND_DOWN (מחיר לא גבוה מהמותר)
      - SELL → ROUND_UP   (מחיר לא נמוך מהמותר)
    """
    side_up = (side or "").strip().upper()
    if side_up == "SELL":
        return _quantize_multiple(entry_price, tick_str, rounding=ROUND_UP)
    return _quantize_multiple(entry_price, tick_str, rounding=ROUND_DOWN)


def _compute_qty_and_price(
    *,
    symbol: str,
    side: str,
    budget: float,
    leverage: int,
    entry_price: Optional[float],
) -> Dict[str, Any]:
    """
    מחזיר כמות ומחיר מעוגנים לפי filters, כולל עמידה ב-minQty/MIN_NOTIONAL והקפדה לא לחרוג מה-budget×leverage.
    """
    sym = (symbol or "").strip().upper()
    side_up = (side or "").strip().upper()
    if side_up not in ("BUY", "SELL"):
        return {"ok": False, "error": "side must be BUY or SELL"}

    # מחיר: Mark Price (fallback פנימי אם צריך)
    px = float(entry_price) if (entry_price and entry_price > 0) else (futures_mark_price(sym) or 0.0)
    if px <= 0:
        return {"ok": False, "error": f"Price unavailable for {sym}"}

    # פילטרים
    f = get_symbol_filters(sym)
    step_str = f.get("stepSizeStr", "0.001")
    tick_str = f.get("tickSizeStr", "0.1")
    min_qty = f.get("minQty")
    min_notional = f.get("minNotional") or 5.0  # Fallback שמרני

    # תקרה נומינלית לפי תקציב×מינוף (שומר משמעת סיכון)
    allowed_notional = float(budget) * float(leverage)

    # עיגון מחיר לכיוון
    px_dec = _round_price_for_side(px, tick_str, side_up)

    # חישוב כמות גולמית → רצפה ל-step
    qty_raw = _d(allowed_notional) / px_dec if allowed_notional > 0 else _d(0)
    qty_dec = _quantize_multiple(qty_raw, step_str, rounding=ROUND_DOWN)

    # אכיפת minQty אם קיים
    if isinstance(min_qty, (int, float)) and min_qty is not None:
        min_qty_dec = _quantize_multiple(Decimal(str(min_qty)), step_str, rounding=ROUND_UP)
        if qty_dec < min_qty_dec:
            # אם העלאה ל-minQty תחרוג מהתקרה המותרת, נחזיר הנחיה להעלות תקציב
            need_notional = float(min_qty_dec * px_dec)
            if need_notional > allowed_notional + 1e-9:
                need_budget = need_notional / max(1, leverage)
                return {
                    "ok": False,
                    "error": "Quantity below minQty and increases notional beyond budget.",
                    "hint": f"Increase budget to ≥ ~{need_budget:.6f} USDT (at leverage {leverage}×).",
                    "entry": float(px_dec),
                    "qty": float(qty_dec),
                }
            qty_dec = min_qty_dec  # אחרת נרים ל-minQty

    # בדיקת MIN_NOTIONAL: ננסה להעלות כמות (במסגרת התקציב×מינוף) כדי לעמוד בו
    final_notional = float(qty_dec * px_dec)
    if final_notional + 1e-9 < float(min_notional):
        needed_qty = _d(min_notional) / px_dec
        needed_qty_dec = _quantize_multiple(needed_qty, step_str, rounding=ROUND_UP)
        needed_notional = float(needed_qty_dec * px_dec)

        # תקרת כמות לפי התקציב × מינוף
        max_qty_by_budget = _quantize_multiple(_d(allowed_notional) / px_dec, step_str, rounding=ROUND_DOWN)

        if needed_qty_dec <= max_qty_by_budget:
            qty_dec = needed_qty_dec
            final_notional = float(qty_dec * px_dec)
        else:
            need_budget = needed_notional / max(1, leverage)
            return {
                "ok": False,
                "error": f"MIN_NOTIONAL not met (have {final_notional:.8f} < need {min_notional:.8f}).",
                "hint": f"Increase budget to ≥ ~{need_budget:.6f} USDT (at leverage {leverage}×).",
                "entry": float(px_dec),
                "qty": float(qty_dec),
            }

    if qty_dec <= 0:
        return {"ok": False, "error": "Calculated quantity is zero after step rounding", "entry": float(px_dec)}

    return {
        "ok": True,
        "entry": float(px_dec),
        "qty": float(qty_dec),
        "notional": float(qty_dec * px_dec),
        "stepSizeStr": step_str,
        "tickSizeStr": tick_str,
        "minQty": float(min_qty) if isinstance(min_qty, (int, float)) and min_qty is not None else None,
        "minNotional": float(min_notional) if min_notional is not None else None,
    }


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

    # חישוב/עיגון מחיר+כמות אם quantity לא סופקה מבחוץ
    qty_calc: Optional[float] = quantity
    entry_calc: Optional[float] = None

    if qty_calc is None:
        comp = _compute_qty_and_price(
            symbol=sym, side=side_up, budget=float(budget), leverage=int(leverage), entry_price=float(entry or 0)
        )
        if not comp.get("ok"):
            return {
                "mode": "dry_run" if (dry_run or not EXECUTE_TRADES) else "live_failed",
                "symbol": sym,
                "side": side_up,
                "entry": float(entry) if entry else None,
                "sl": float(sl),
                "tp": float(tp),
                "leverage": int(leverage),
                "budget": float(budget),
                "quantity": None,
                "ok": False,
                "error": comp.get("error"),
                "hint": comp.get("hint"),
            }
        qty_calc = float(comp["qty"])
        entry_calc = float(comp["entry"])
    else:
        # עגן מחיר לפי side (גם אם סופק מבחוץ)
        f = get_symbol_filters(sym)
        tick_str = f.get("tickSizeStr", "0.1")
        entry_dec = _round_price_for_side(float(entry), tick_str, side_up)
        entry_calc = float(entry_dec)

    # DRY-RUN → נחזיר חיווי מלא עם הכמות והמחיר לאחר עיגון
    if dry_run or not EXECUTE_TRADES:
        return {
            "mode": "dry_run",
            "symbol": sym,
            "side": side_up,
            "entry": float(entry_calc if entry_calc is not None else entry),
            "sl": float(sl),
            "tp": float(tp),
            "leverage": int(leverage),
            "budget": float(budget),
            "quantity": float(qty_calc) if qty_calc is not None else None,
            "ok": True,
        }

    # LIVE: שימוש במימוש legacy אם ביקשת וגם קיים
    if _USE_BINANCE_TRADER and _binance_trader_available:
        try:
            res = await binance_futures_trade(  # type: ignore
                symbol=sym,
                side=side_up,
                entry=float(entry_calc if entry_calc is not None else entry),
                sl=float(sl),
                tp=float(tp),
                leverage=int(leverage),
                budget=float(budget),
                quantity=float(qty_calc) if qty_calc is not None else None,
                market_type="futures",
            )
            return {"mode": "live_legacy", "ok": True, **res}
        except Exception as e:
            logger.exception("legacy binance_futures_trade failed")
            return {"mode": "live_legacy", "ok": False, "error": str(e)}

    # LIVE: ביצוע ישיר דרך הלקוח המעודכן (LIMIT-IOC)
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
            price=float(entry_calc if entry_calc is not None else entry),
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
            "entry": float(entry_calc if entry_calc is not None else entry),
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
            "entry": float(entry_calc if entry_calc is not None else entry),
            "sl": float(sl),
            "tp": float(tp),
            "leverage": int(leverage),
            "budget": float(budget),
            "quantity": float(qty_calc) if qty_calc is not None else None,
            "error": str(e),
        }























































