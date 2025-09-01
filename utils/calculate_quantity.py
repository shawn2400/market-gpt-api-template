# utils/calculate_quantity.py
# שמירת תאימות לאזורים ישנים בקוד + פולבקים אמינים ל-precision_utils.

import logging
from typing import Dict, Optional
from decimal import Decimal

# --- ניסיון להשתמש במימוש הישן (אם קיים) ---
_has_core = True
try:
    from utils.quantity_utils import (
        get_precision_info as _get_precision_info_core,
        round_step as _round_step_core,
        round_tick as _round_tick_core,
        calculate_quantity as _calculate_quantity_core,
    )
except Exception as e:
    _has_core = False
    logging.warning("[calculate_quantity] quantity_utils core not available, will use precision_utils fallback: %s", e)

# --- פולבקים דרך precision_utils ---
try:
    from utils.precision_utils import (
        get_precision_info as _get_precision_info_px,
        apply_qty_step as _apply_qty_step_px,
        apply_price_tick as _apply_price_tick_px,
        calc_quantity_from_budget as _calc_qty_budget_px,
    )
except Exception as e:
    # זה מצב חריג מאוד — בלי precision_utils אין יכולת פולבק
    logging.error("[calculate_quantity] precision_utils import failed: %s", e)
    _get_precision_info_px = None
    _apply_qty_step_px = None
    _apply_price_tick_px = None
    _calc_qty_budget_px = None


def get_precision_info(symbol: str) -> Dict[str, float]:
    """
    מחזיר pricePrecision/quantityPrecision. קודם ננסה את ה-core; אחרת פולבק ל-precision_utils.
    """
    if _has_core:
        try:
            return _get_precision_info_core(symbol)
        except Exception as e:
            logging.warning("[calculate_quantity] core.get_precision_info failed, fallback: %s", e)
    if _get_precision_info_px:
        return _get_precision_info_px(symbol)
    return {"pricePrecision": 2, "quantityPrecision": 3}


def round_step(value: float, step: float) -> float:
    """
    עיגול למטה ל-step נתון. אם יש core נשתמש בו; אחרת נממש כאן.
    """
    if _has_core:
        try:
            return _round_step_core(value, step)
        except Exception as e:
            logging.warning("[calculate_quantity] core.round_step failed, fallback: %s", e)
    try:
        v = Decimal(str(value))
        s = Decimal(str(step))
        if s <= 0:
            return float(v)
        return float((v // s) * s)
    except Exception:
        return float(value)


def round_tick(price: float, tick_size: float, *, symbol: Optional[str] = None) -> float:
    """
    עיגול למטה ל-tick_size.
    אם יש core נשתמש בו; אחרת פולבק דרך precision_utils.apply_price_tick (דורש symbol לשימוש בפילטרים).
    """
    if _has_core:
        try:
            return _round_tick_core(price, tick_size)
        except Exception as e:
            logging.warning("[calculate_quantity] core.round_tick failed, fallback: %s", e)

    # אם יש לנו precision_utils, עדיף לתת לו את הסימבול (לא "__GENERIC__")
    if _apply_price_tick_px and symbol:
        v, _ = _apply_price_tick_px(price, symbol)
        return float(v)

    # פולבק מתמטי פשוט
    try:
        v = Decimal(str(price))
        t = Decimal(str(tick_size))
        if t <= 0:
            return float(v)
        return float((v // t) * t)
    except Exception:
        return float(price)


def calculate_quantity(symbol: str, entry_price: float, leverage: float, budget_usdt: float) -> float:
    """
    API תואם לקוד הישן:
    - קודם מנסה את המימוש הישן (quantity_utils).
    - אם נכשל/לא קיים → פולבק מדויק: (Budget×Leverage)/Entry + עיגון LOT_SIZE/MIN_NOTIONAL דרך precision_utils.
    מחזיר float כמות מעוגנת; בשגיאה מחזיר 0.0 (כמו הישן).
    """
    # ניסיון ראשון: core הישן
    if _has_core:
        try:
            return _calculate_quantity_core(symbol, entry_price, leverage, budget_usdt)
        except Exception as e:
            logging.warning("[calculate_quantity] core.calculate_quantity failed, using fallback: %s", e)

    # פולבק: precision_utils
    try:
        if not _calc_qty_budget_px:
            raise RuntimeError("precision_utils fallback unavailable")

        res = _calc_qty_budget_px(
            symbol=symbol,
            price=float(entry_price),
            budget_usd=float(budget_usdt),
            leverage=float(leverage if leverage is not None else 1.0),
        )
        if not res.get("ok"):
            logging.error("[calculate_quantity] fallback calc failed: %s", res)
            return 0.0
        qty = float(res["qty"])
        return qty if qty > 0 else 0.0
    except Exception as e:
        logging.error(f"[calculate_quantity] ❌ שגיאה בחישוב כמות עבור {symbol}: {e}")
        return 0.0










