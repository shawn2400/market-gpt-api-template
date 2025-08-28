# utils/binance_trader.py
from __future__ import annotations
import logging
from typing import Dict, Any

from utils.binance_client import (
    futures_mark_price,
    set_leverage,
    place_limit_order,
    futures_open_positions,
)

logger = logging.getLogger("algogpt.binance.trader")

def _calc_entry_price(side: str, mark: float) -> float:
    """
    בוחר מחיר Limit שמבטיח Post-Only (לא יחצה את הספר).
    BUY → מעט מתחת ל-Mark, SELL → מעט מעל.
    """
    if side == "BUY":
        return mark * 0.998  # ~0.2% מתחת ל-Mark
    else:
        return mark * 1.002  # ~0.2% מעל ה-Mark

async def binance_futures_trade(
    symbol: str,
    side: str,
    budget: float,
    leverage: int = 10,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    ביצוע טרייד ב-Binance Futures.
    - כניסה ב-LIMIT Post-Only (GTX) כדי לשמור Maker.
    - שינוי מינוף לפני שליחה.
    - qty מחושב כ-(budget / mark_price) — שמירה על התנהגות קיימת.
    """
    symbol = symbol.upper().strip()
    side = side.upper().strip()
    if side not in ("BUY", "SELL"):
        raise ValueError("side must be BUY or SELL")

    mark = futures_mark_price(symbol)
    if mark is None:
        raise RuntimeError(f"Mark price unavailable for {symbol}")

    # שמרנו את הסמנטיקה המקורית: budget/price (ללא הכפלת leverage)
    qty = budget / mark

    entry_price = _calc_entry_price(side, mark)

    if dry_run:
        logger.info(f"[DRY RUN] {side} {symbol} budget={budget} qty≈{qty:.8f} lev={leverage} limit={entry_price:.8f}")
        return {
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "entry": entry_price,
            "leverage": leverage,
            "dry_run": True,
        }

    # שינוי מינוף
    try:
        set_leverage(symbol, leverage)
    except Exception as e:
        logger.error(f"[Leverage] failed for {symbol}: {e}")
        # לא מפילים מיד — יש מערכות שמאפשרות שליחה גם אם ה-leverage לא עודכן

    # שליחת LIMIT GTX (Post-Only). אם חוצה ספר → ידחה, וזה תקין למדיניות Maker.
    order = place_limit_order(
        symbol=symbol,
        side=side,
        quantity=qty,
        price=entry_price,
        post_only=True,          # GTX
        reduce_only=False,
        position_side=None,      # אם אתה ב-Hedge Mode הוסף "LONG"/"SHORT"
        time_in_force=None,      # None => GTX
    )

    # אין הבטחה למילוי מיידי (Post-Only). מחזירים את פרטי ההזמנה.
    out = {
        "symbol": symbol,
        "side": side,
        "qty": qty,
        "entry": entry_price,
        "leverage": leverage,
        "order": {k: order.get(k) for k in ("orderId", "clientOrderId", "status", "price", "origQty")},  # מידע שימושי
    }
    logger.info(f"[New LIMIT GTX] {out}")
    return out

def force_close_position(symbol: str) -> Dict[str, Any]:
    """
    סגירת פוזיציה קיימת ב-Reduce-Only עם LIMIT+IOC אגרסיבי (ללא Market).
    LONG → SELL ב-IOC במחיר נמוך מה-Mark; SHORT → BUY ב-IOC במחיר גבוה מה-Mark.
    """
    symbol = symbol.upper().strip()
    positions = futures_open_positions() or []
    pos = next((p for p in positions if p.get("symbol") == symbol), None)
    if not pos:
        return {"symbol": symbol, "closedAmt": 0.0, "message": "no position for symbol"}

    amt = float(pos.get("positionAmt") or 0.0)
    if amt == 0.0:
        return {"symbol": symbol, "closedAmt": 0.0, "message": "no open amount"}

    mark = futures_mark_price(symbol)
    if mark is None:
        raise RuntimeError(f"Mark price unavailable for {symbol}")

    if amt > 0:
        # סגירת לונג: SELL
        side = "SELL"
        limit_px = mark * 0.98  # 2% מתחת ל-Mark כדי להבטיח מילוי מידי ב-IOC
    else:
        # סגירת שורט: BUY
        side = "BUY"
        limit_px = mark * 1.02  # 2% מעל ה-Mark

    try:
        r = place_limit_order(
            symbol=symbol,
            side=side,
            quantity=abs(amt),
            price=limit_px,
            post_only=False,           # לא Post-Only
            reduce_only=True,          # סגירה בלבד
            position_side=None,        # אם Hedge Mode פעיל הוסף "LONG"/"SHORT" בהתאם
            time_in_force="IOC",       # Immediate-Or-Cancel
        )
        logger.info(f"[Force Close IOC] {symbol} amt={amt} -> {side} limit={limit_px} resp={r.get('orderId')}")
        return {
            "symbol": symbol,
            "closedAmt": amt,
            "side": side,
            "orderId": r.get("orderId"),
            "status": r.get("status"),
        }
    except Exception as e:
        logger.error(f"[Force Close IOC] failed for {symbol}: {e}")
        raise



































