# utils/quantize.py
# -*- coding: utf-8 -*-
"""
כלי קוונטיזציה (Price/Qty) לזוגות חוזים ב-Binance Futures.

הקובץ מספק:
- get_filters(client, symbol) -> מאחזר tickSize/stepSize וערכי סף רלוונטיים בצורה עמידה ומהירה (עם cache).
- quantize_price(px, filters, direction="down") -> מחזיר מחיר מעוגל לפי tick.
- quantize_qty(qty, filters) -> מחזיר כמות מעוגלת לפי step.
- ensure_min_qty(qty, filters) -> מוודא עמידה ב-minQty אם זמין.
- ensure_min_notional(qty, price, filters) -> מוודא עמידה ב-minNotional (נוטיונל מינימלי).
- clamp_decimals(value, max_decimals) -> חיתוך “רעשים” בינאריים בכמות/מחיר.

המודול עמיד כאשר קריאות לרשימת המכשירים נכשלות — יוחזרו ערכי ברירת מחדל
סבירים. כל פונקציה טהורה (ללא תופעות לוואי) פרט ל-cache ב-lru_cache.
"""

from __future__ import annotations
import math
from functools import lru_cache
from typing import Dict, Any, Optional

__all__ = [
    "get_filters",
    "quantize_price",
    "quantize_qty",
    "ensure_min_qty",
    "ensure_min_notional",
    "clamp_decimals",
]

_DEFAULT_TICK = 0.01
_DEFAULT_STEP = 0.001
_DEFAULT_MIN_NOTIONAL = 5.0  # USDT-M common default; overridden if NOTIONAL filter exists.

def _safe_float(x: Any, fallback: float) -> float:
    try:
        v = float(x)
        if not math.isfinite(v):
            return fallback
        return v
    except Exception:
        return fallback

def _decimals_from_step_str(step_str: str) -> int:
    s = str(step_str)
    if "." not in s:
        return 0
    frac = s.split(".", 1)[1].rstrip("0")
    return max(0, len(frac))

def clamp_decimals(value: float, max_decimals: int) -> float:
    max_decimals = int(max(0, max_decimals))
    fmt = "{:0." + str(max_decimals) + "f}"
    try:
        return float(fmt.format(float(value)))
    except Exception:
        return float(value)

def _floor_to(x: float, step: float) -> float:
    if step <= 0:
        return float(x)
    return math.floor(float(x) / float(step)) * float(step)

def _ceil_to(x: float, step: float) -> float:
    if step <= 0:
        return float(x)
    return math.ceil(float(x) / float(step)) * float(step)

@lru_cache(maxsize=2048)
def get_filters(client, symbol: str) -> Dict[str, Any]:
    sym = (symbol or "").upper()
    out: Dict[str, Any] = {
        "tick": float(_DEFAULT_TICK),
        "step": float(_DEFAULT_STEP),
        "pricePrecision": 8,
        "quantityPrecision": 8,
        "minQty": None,
        "minNotional": None,
    }

    try:
        info = client.futures_exchange_info() or {}
    except Exception:
        return out

    try:
        for s in info.get("symbols", []):
            if (s.get("symbol") or "").upper() != sym:
                continue
            out["pricePrecision"] = int(s.get("pricePrecision", out["pricePrecision"]))
            out["quantityPrecision"] = int(s.get("quantityPrecision", out["quantityPrecision"]))
            for f in s.get("filters", []):
                ftype = f.get("filterType")
                if ftype == "PRICE_FILTER":
                    out["tick"] = _safe_float(f.get("tickSize"), out["tick"])
                elif ftype in ("LOT_SIZE", "MARKET_LOT_SIZE", "MARKET_Lot_SIZE"):
                    out["step"] = _safe_float(f.get("stepSize"), out["step"])
                    if f.get("minQty") is not None:
                        out["minQty"] = _safe_float(f.get("minQty"), out.get("minQty") or 0.0)
                elif ftype in ("MIN_NOTIONAL", "NOTIONAL"):
                    val = f.get("notional", f.get("minNotional"))
                    if val is not None:
                        out["minNotional"] = _safe_float(val, out.get("minNotional") or _DEFAULT_MIN_NOTIONAL)
            break
    except Exception:
        pass

    if out["tick"] <= 0:
        out["tick"] = float(_DEFAULT_TICK)
    if out["step"] <= 0:
        out["step"] = float(_DEFAULT_STEP)
    return out

def quantize_price(px: float, filters: Dict[str, Any], direction: str = "down") -> float:
    tick = _safe_float(filters.get("tick"), _DEFAULT_TICK)
    if tick <= 0:
        tick = _DEFAULT_TICK

    if direction.lower().startswith("up"):
        p = _ceil_to(px, tick)
    elif direction.lower().startswith("near"):
        steps = round(float(px) / tick)
        p = steps * tick
    else:
        p = _floor_to(px, tick)

    decs = _decimals_from_step_str(str(filters.get("tick") or _DEFAULT_TICK))
    return clamp_decimals(p, decs)

def quantize_qty(qty: float, filters: Dict[str, Any]) -> float:
    step = _safe_float(filters.get("step"), _DEFAULT_STEP)
    if step <= 0:
        step = _DEFAULT_STEP
    q = _floor_to(qty, step)
    decs = _decimals_from_step_str(str(filters.get("step") or _DEFAULT_STEP))
    return clamp_decimals(q, decs)

def ensure_min_qty(qty: float, filters: Dict[str, Any]) -> float:
    q = quantize_qty(qty, filters)
    min_q = filters.get("minQty")
    if min_q is None:
        return q
    min_q = _safe_float(min_q, 0.0)
    if min_q <= 0:
        return q
    step = _safe_float(filters.get("step"), _DEFAULT_STEP)
    if q <= 0:
        q = min_q
    if q < min_q:
        q = _ceil_to(min_q, step)
    return quantize_qty(q, filters)

def ensure_min_notional(qty: float, price: float, filters: Dict[str, Any]) -> float:
    q = quantize_qty(qty, filters)
    min_notional = filters.get("minNotional")
    if min_notional is None:
        return q

    min_notional = _safe_float(min_notional, _DEFAULT_MIN_NOTIONAL)
    px = _safe_float(price, 0.0)
    if px <= 0:
        return q

    notional = q * px
    if notional >= min_notional:
        return q

    step = _safe_float(filters.get("step"), _DEFAULT_STEP)
    if step <= 0:
        step = _DEFAULT_STEP

    needed = min_notional / px
    q_new = _ceil_to(needed, step)
    q_new = quantize_qty(q_new, filters)
    if q_new <= 0:
        return 0.0
    return q_new


