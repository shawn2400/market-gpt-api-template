# utils/precision_utils.py
from __future__ import annotations
from decimal import Decimal, ROUND_DOWN, getcontext
from typing import Dict, Any, Optional, Tuple
import threading
import time
import logging
import os

from utils.binance_client import (
    futures_exchange_info_safe,
    DEFAULT_QTY_STEP_STR as _DEF_QTY_STEP,
    DEFAULT_PRICE_TICK_STR as _DEF_TICK,
    DEFAULT_MIN_NOTIONAL as _DEF_MIN_NOTIONAL,
)

# דיוק גבוה למניעת שגיאות חישוביות
getcontext().prec = 28

# ===================== ExchangeInfo Cache =====================
_EX_INFO_LOCK = threading.Lock()
_EX_INFO_DATA: Optional[Dict[str, Any]] = None
_EX_INFO_TS: float = 0.0
_EX_INFO_TTL_SEC = int(os.getenv("EXCHANGE_INFO_TTL_SEC", "900"))  # ברירת מחדל 15 דקות

def _load_ex_info_live() -> Dict[str, Any]:
    try:
        data = futures_exchange_info_safe()
        return data or {}
    except Exception as e:
        logging.warning("[precision_utils] exchange_info load failed: %s", e)
        return {}

def _ensure_ex_info(ttl_sec: int = _EX_INFO_TTL_SEC) -> Dict[str, Any]:
    global _EX_INFO_DATA, _EX_INFO_TS
    now = time.time()
    with _EX_INFO_LOCK:
        if _EX_INFO_DATA is None or (now - _EX_INFO_TS) > ttl_sec:
            _EX_INFO_DATA = _load_ex_info_live()
            _EX_INFO_TS = now
        return _EX_INFO_DATA or {}

def refresh_exchange_info() -> None:
    """רענון יזום של exchangeInfo"""
    global _EX_INFO_DATA, _EX_INFO_TS
    with _EX_INFO_LOCK:
        _EX_INFO_DATA = _load_ex_info_live()
        _EX_INFO_TS = time.time()
    logging.info("[precision_utils] exchange_info refreshed")

# ===================== Symbol Helpers =====================
def _find_symbol_info(symbol: str) -> Optional[Dict[str, Any]]:
    ei = _ensure_ex_info()
    su = (symbol or "").upper()
    for s in (ei.get("symbols") or []):
        if (s.get("symbol") or "").upper() == su:
            return s
    return None

def get_precision_info(symbol: str) -> dict:
    """
    מחזיר pricePrecision / quantityPrecision מתוך exchangeInfo.
    אם הסימבול לא נמצא – מחזיר ערכים דיפולטיביים.
    """
    info = _find_symbol_info(symbol)
    if not info:
        return {"pricePrecision": 8, "quantityPrecision": 8}
    return {
        "pricePrecision": int(info.get("pricePrecision", 8)),
        "quantityPrecision": int(info.get("quantityPrecision", 8)),
    }

# ===================== Rounding =====================
def round_to_precision(value: float, digits: int) -> float:
    """עיגול פשוט ל־N ספרות אחרי הנקודה"""
    try:
        return round(float(value), int(digits))
    except Exception:
        return float(value)

def _decimal_step_round(value: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        return value
    return (value // step) * step  # floor

def _decimal_step_round_up(value: Decimal, step: Decimal) -> Decimal:
    """Ceil למכפלת step (משמש ל-Sell מול tick)."""
    if step <= 0:
        return value
    eps = Decimal("1e-18")
    return ((value + step - eps) // step) * step

def _tick_or_default(info: dict) -> str:
    tick = None
    for f in (info.get("filters") or []):
        if f.get("filterType") == "PRICE_FILTER":
            tick = f.get("tickSize")
            break
    return str(tick or _DEF_TICK)

def _step_or_default(info: dict) -> str:
    step = None
    for f in (info.get("filters") or []):
        if f.get("filterType") == "LOT_SIZE":
            step = f.get("stepSize")
            break
    if step is None:
        for f in (info.get("filters") or []):
            if f.get("filterType") == "MARKET_LOT_SIZE":
                step = f.get("stepSize")
                break
    return str(step or _DEF_QTY_STEP)

# ===================== Price & Qty Appliers =====================
def apply_price_tick(price: float, symbol: str) -> Tuple[float, str]:
    """
    מעגל מחיר ל־tickSize לפי exchangeInfo.
    """
    info = _find_symbol_info(symbol) or {}
    price_precision = info.get("pricePrecision", 8)
    tick_size = _tick_or_default(info)

    v = Decimal(str(price))
    t = Decimal(str(tick_size)) if tick_size else Decimal("0")
    dec = _decimal_step_round(v, t) if t > 0 else v

    q = Decimal(1).scaleb(-int(price_precision))
    s = format(dec.quantize(q, rounding=ROUND_DOWN).normalize(), "f")
    return float(dec), s

def apply_price_tick_side(price: float, symbol: str, side: str) -> Tuple[float, str]:
    """
    BUY → ROUND_DOWN | SELL → ROUND_UP
    """
    info = _find_symbol_info(symbol) or {}
    price_precision = info.get("pricePrecision", 8)
    tick_size = _tick_or_default(info)

    v = Decimal(str(price))
    t = Decimal(str(tick_size)) if tick_size else Decimal("0")
    is_sell = (str(side or "").upper() == "SELL")

    if t > 0:
        dec = _decimal_step_round_up(v, t) if is_sell else _decimal_step_round(v, t)
    else:
        dec = v

    q = Decimal(1).scaleb(-int(price_precision))
    s = format(dec.quantize(q, rounding=ROUND_DOWN).normalize(), "f")
    return float(dec), s

def apply_qty_step(qty: float, symbol: str) -> Tuple[float, str]:
    """
    מעגל כמות ל־stepSize לפי exchangeInfo.
    """
    info = _find_symbol_info(symbol) or {}
    qty_precision = info.get("quantityPrecision", 8)
    step_size = _step_or_default(info)

    v = Decimal(str(qty))
    s = Decimal(str(step_size)) if step_size else Decimal("0")
    dec = _decimal_step_round(v, s) if s > 0 else v

    q = Decimal(1).scaleb(-int(qty_precision))
    out = format(dec.quantize(q, rounding=ROUND_DOWN).normalize(), "f")
    return float(dec), out

# ===================== Filters + Quantity =====================
def _symbol_filters(symbol: str) -> Dict[str, Any]:
    """
    מאתר tickSize/stepSize/minQty/minNotional מתוך exchangeInfo עם Fallbacks.
    """
    info = _find_symbol_info(symbol) or {}
    tick_size = None
    step_size = None
    min_qty = None
    min_notional = None

    for f in (info.get("filters") or []):
        t = f.get("filterType")
        if t == "PRICE_FILTER":
            tick_size = f.get("tickSize")
        elif t == "LOT_SIZE":
            step_size = f.get("stepSize") or step_size
            min_qty = f.get("minQty") if f.get("minQty") is not None else min_qty
        elif t == "MARKET_LOT_SIZE":
            step_size = step_size or f.get("stepSize")
        elif t in ("MIN_NOTIONAL", "NOTIONAL"):
            mn = f.get("notional") or f.get("minNotional") or f.get("minNotionalValue")
            if mn is not None:
                min_notional = mn

    def _safe_float(x):
        try:
            return float(x)
        except Exception:
            return None

    return {
        "tick_size": _safe_float(tick_size or _DEF_TICK),
        "step_size": _safe_float(step_size or _DEF_QTY_STEP),
        "min_qty": _safe_float(min_qty),
        "min_notional": _safe_float(min_notional) if min_notional is not None else float(_DEF_MIN_NOTIONAL),
        "pricePrecision": int(info.get("pricePrecision", 8)) if info else 8,
        "quantityPrecision": int(info.get("quantityPrecision", 8)) if info else 8,
    }

def calc_quantity_from_budget(
    symbol: str,
    *,
    price: float,
    budget_usd: float,
    leverage: float = 1.0,
) -> Dict[str, Any]:
    """
    מחשב כמות לפי תקציב×מינוף, עם עיגון ל-LOT_SIZE ועמידה ב-MIN_NOTIONAL.
    """
    try:
        price = float(price); budget_usd = float(budget_usd); leverage = max(1.0, float(leverage))
    except Exception:
        return {"ok": False, "reason": "bad_inputs"}

    if price <= 0 or budget_usd <= 0:
        return {"ok": False, "reason": "non_positive_inputs"}

    flt = _symbol_filters(symbol)
    pos_value = budget_usd * leverage  # USD
    raw_qty = pos_value / price

    qty_dec, qty_str = apply_qty_step(raw_qty, symbol)
    notional = qty_dec * price
    mn = float(flt.get("min_notional") or _DEF_MIN_NOTIONAL)
    min_qty = flt.get("min_qty")

    if min_qty is not None and qty_dec < float(min_qty):
        qty_dec, qty_str = apply_qty_step(float(min_qty), symbol)
        notional = qty_dec * price

    if notional + 1e-9 < mn:
        needed_qty = (mn / price) * 1.001
        qty_dec2, qty_str2 = apply_qty_step(needed_qty, symbol)
        notional2 = qty_dec2 * price
        if notional2 + 1e-9 < mn:
            return {
                "ok": False,
                "reason": "below_min_notional",
                "qty": float(qty_dec),
                "qty_str": qty_str,
                "notional": float(notional),
                "min_notional": float(mn),
            }
        qty_dec, qty_str, notional = qty_dec2, qty_str2, notional2

    if qty_dec <= 0:
        return {"ok": False, "reason": "qty_rounded_to_zero", "min_notional": float(mn)}

    return {
        "ok": True,
        "qty": float(qty_dec),
        "qty_str": qty_str,
        "notional": float(notional),
        "min_notional": float(mn),
        "min_qty": float(min_qty) if min_qty is not None else None,
    }

__all__ = [
    "refresh_exchange_info",
    "get_precision_info",
    "round_to_precision",
    "apply_price_tick",
    "apply_price_tick_side",
    "apply_qty_step",
    "calc_quantity_from_budget",
]

























