# utils/quantity_utils.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Dict, Any, Optional
from decimal import Decimal, ROUND_DOWN
import os

def round_step(value: float, step: float) -> float:
    """
    עיגול ערך לפי LOT_SIZE (stepSize) של הסימבול – עיגול למטה.
    """
    try:
        v = Decimal(str(value))
        s = Decimal(str(step))
        if s <= 0:
            return float(v)
        q = (v / s).to_integral_value(rounding=ROUND_DOWN) * s
        return float(q.quantize(s, rounding=ROUND_DOWN))
    except Exception:
        return float(value)

def round_tick(price: float, tick: float) -> float:
    """
    עיגול מחיר לפי PRICE_FILTER (tickSize) – עיגול למטה.
    """
    try:
        p = Decimal(str(price))
        t = Decimal(str(tick))
        if t <= 0:
            return float(p)
        k = (p / t).to_integral_value(rounding=ROUND_DOWN) * t
        return float(k.quantize(t, rounding=ROUND_DOWN))
    except Exception:
        return float(price)

# ---- get_precision_info shim (ניסיון להיעזר במודול מדויק יותר אם קיים) ----
try:
    from utils.precision_utils import get_precision_info as _get_precision_info  # type: ignore
except Exception:
    _get_precision_info = None  # type: ignore

def get_precision_info(symbol: str) -> Dict[str, Any]:
    """
    מחזיר פרטי דיוק ומינונים למסחר. אם קיים מודול מדויק — ישתמש בו.
    אחרת יחזיר ערכי דיפולט שמרניים.
    """
    if _get_precision_info is not None:
        try:
            return _get_precision_info(symbol)
        except Exception:
            pass
    return {
        "symbol": symbol.upper(),
        "price_precision": 2,
        "quantity_precision": 3,
        "min_qty": 0.001,
        "min_notional": 5.0,
        "step_size": 0.001,
        "tick_size": 0.01,
    }

def _env_float(name: str, default: float) -> float:
    try:
        v = os.getenv(name, "")
        return float(v) if v not in ("", None) else default
    except Exception:
        return default

def calculate_quantity(
    symbol: str,
    entry_price: float,
    leverage: float,
    budget_usdt: float,
    *,
    min_notional_usdt: Optional[float] = None,
    margin_buffer_pct: Optional[float] = None,
) -> float:
    """
    חישוב כמות לפי נוסחת notional: qty ≈ (budget * leverage) / price,
    עם באפר מרג'ין, עיגון ל-LOT_SIZE ואכיפת MIN_NOTIONAL.

    פרמטרים אופציונליים ילקחו מ־ENV אם לא סופקו:
      - AUTO_QTY_MARGIN_BUFFER_PCT (ברירת מחדל 0.20)
      - MIN_NOTIONAL_USDT (ברירת מחדל 5.0)
    """
    try:
        px = Decimal(str(entry_price))
        lev = Decimal(str(leverage if leverage is not None else 1.0))
        budget = Decimal(str(budget_usdt))

        prec = get_precision_info(symbol)
        step = Decimal(str(prec.get("step_size", 0.001)))
        min_not = Decimal(str(
            min_notional_usdt
            if min_notional_usdt is not None
            else prec.get("min_notional", _env_float("MIN_NOTIONAL_USDT", 5.0))
        ))
        buf = Decimal(str(
            margin_buffer_pct
            if margin_buffer_pct is not None
            else _env_float("AUTO_QTY_MARGIN_BUFFER_PCT", 0.20)
        ))

        effective_budget = budget * (Decimal("1") - buf)
        raw_qty = (effective_budget * lev) / px

        # round down to step
        if step > 0:
            q_units = (raw_qty / step).to_integral_value(rounding=ROUND_DOWN)
            qty = (q_units * step)
        else:
            qty = raw_qty

        # enforce min notional
        if qty * px < min_not:
            qty = (min_not / px)
            if step > 0:
                q_units = (qty / step).to_integral_value(rounding=ROUND_DOWN)
                qty = (q_units * step)

        # never zero
        if qty <= 0:
            qty = step if step > 0 else Decimal("0.001")

        # כמות סופית
        return float(qty)
    except Exception:
        return 0.0

__all__ = ["round_step", "round_tick", "get_precision_info", "calculate_quantity"]





