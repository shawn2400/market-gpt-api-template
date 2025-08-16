# utils/precision_utils.py
from __future__ import annotations
from decimal import Decimal, ROUND_DOWN, getcontext
from functools import lru_cache
from typing import Dict, Any, Optional, Tuple

from utils.binance_client import futures_exchange_info_safe

# דיוק גבוה למניעת שגיאות ציפה
getcontext().prec = 28

@lru_cache(maxsize=1)
def _load_futures_exchange_info() -> Dict[str, Any]:
    """
    exchangeInfo של Futures (עם ריטריי/פולבק שמיושם ב-binance_client).
    """
    data = futures_exchange_info_safe()
    return data or {}

def _find_symbol_info(symbol: str) -> Optional[Dict[str, Any]]:
    ei = _load_futures_exchange_info()
    su = (symbol or "").upper()
    for s in ei.get("symbols", []) or []:
        if s.get("symbol") == su:
            return s
    return None

def get_precision_info(symbol: str) -> dict:
    """
    מחזיר pricePrecision / quantityPrecision מתוך exchangeInfo.
    אם הסימבול לא נמצא – מחזיר דיפולט שמרני.
    """
    info = _find_symbol_info(symbol)
    if not info:
        return {"pricePrecision": 2, "quantityPrecision": 3}
    return {
        "pricePrecision": int(info.get("pricePrecision", 2)),
        "quantityPrecision": int(info.get("quantityPrecision", 3)),
    }

def _decimal_step_round(value: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        return value
    # רינדון למטה על פי step
    return (value // step) * step

def _get_filter(info: Dict[str, Any], ftype: str) -> Optional[Dict[str, Any]]:
    for f in info.get("filters", []) or []:
        if f.get("filterType") == ftype:
            return f
    return None

def _get_tick_size(info: Dict[str, Any]) -> Decimal:
    f = _get_filter(info, "PRICE_FILTER")
    if f:
        ts = f.get("tickSize") or f.get("tick_size") or "0"
        try:
            return Decimal(str(ts))
        except Exception:
            return Decimal("0")
    return Decimal("0")

def _get_step_size(info: Dict[str, Any]) -> Decimal:
    # Futures בד"כ "LOT_SIZE"; לפעמים יש גם MARKET_LOT_SIZE (בדרך כלל זהה)
    f = _get_filter(info, "LOT_SIZE") or _get_filter(info, "MARKET_LOT_SIZE")
    if f:
        ss = f.get("stepSize") or f.get("step_size") or "0"
        try:
            return Decimal(str(ss))
        except Exception:
            return Decimal("0")
    return Decimal("0")

def _get_min_qty(info: Dict[str, Any]) -> Decimal:
    f = _get_filter(info, "LOT_SIZE")
    if f:
        v = f.get("minQty") or "0"
        try:
            return Decimal(str(v))
        except Exception:
            return Decimal("0")
    return Decimal("0")

def _get_min_notional(info: Dict[str, Any]) -> Decimal:
    """
    ב-UM Futures קיים לעיתים filterType=MIN_NOTIONAL עם שדה 'notional'.
    אם לא קיים – נחזיר 0 (אין בדיקה).
    """
    f = _get_filter(info, "MIN_NOTIONAL")
    if f:
        v = f.get("notional") or f.get("minNotional") or "0"
        try:
            return Decimal(str(v))
        except Exception:
            return Decimal("0")
    return Decimal("0")

def apply_price_tick(price: float, symbol: str) -> Tuple[float, str]:
    """
    מעגל מחיר ל-tickSize לפי exchangeInfo ומחזיר (float_dec, string_formatted).
    אם לא נמצא tickSize – יישען על pricePrecision.
    """
    info = _find_symbol_info(symbol) or {}
    price_precision = info.get("pricePrecision")

    v = Decimal(str(price))
    t = _get_tick_size(info)

    dec = _decimal_step_round(v, t) if t > 0 else v

    # פורמט לפי pricePrecision אם ידוע, אחרת השארה טבעית
    if isinstance(price_precision, int) and price_precision >= 0:
        q = Decimal(1).scaleb(-price_precision)
        s = format(dec.quantize(q, rounding=ROUND_DOWN).normalize(), "f")
    else:
        s = format(dec.normalize(), "f")

    return float(dec), s

def apply_qty_step(qty: float, symbol: str) -> Tuple[float, str]:
    """
    מעגל כמות ל-stepSize לפי exchangeInfo ומחזיר (float_dec, string_formatted).
    אם לא נמצא stepSize – יישען על quantityPrecision.
    """
    info = _find_symbol_info(symbol) or {}
    qty_precision = info.get("quantityPrecision")
    step = _get_step_size(info)

    v = Decimal(str(qty))
    dec = _decimal_step_round(v, step) if step > 0 else v

    if isinstance(qty_precision, int) and qty_precision >= 0:
        q = Decimal(1).scaleb(-qty_precision)
        out = format(dec.quantize(q, rounding=ROUND_DOWN).normalize(), "f")
    else:
        out = format(dec.normalize(), "f")

    return float(dec), out

def calc_quantity_from_budget(symbol: str, price: float, budget_usd: float, leverage: float = 1.0) -> Dict[str, Any]:
    """
    מחשב כמות Futures מהתקציב והמחיר:
    qty_raw = (budget_usd * leverage) / price
    מחזיר גם בדיקות MIN_NOTIONAL / minQty.
    """
    info = _find_symbol_info(symbol) or {}
    if price <= 0 or budget_usd <= 0:
        return {"qty": 0.0, "qty_str": "0", "ok": False, "reason": "bad price/budget"}

    raw = (Decimal(str(budget_usd)) * Decimal(str(leverage))) / Decimal(str(price))
    # עיגון ל-step
    step = _get_step_size(info)
    min_qty = _get_min_qty(info)
    min_notional = _get_min_notional(info)

    qty_dec = _decimal_step_round(raw, step) if step > 0 else raw
    if qty_dec <= 0:
        return {"qty": 0.0, "qty_str": "0", "ok": False, "reason": "qty<=0"}

    # כיבוד minQty
    if min_qty > 0 and qty_dec < min_qty:
        qty_dec = min_qty

    # בדיקת MIN_NOTIONAL אם קיים
    notional = qty_dec * Decimal(str(price))
    if min_notional > 0 and notional < min_notional:
        # ננסה להרים כמות למינימום הנדרש
        req = (min_notional / Decimal(str(price)))
        adj = _decimal_step_round(req, step) if step > 0 else req
        if adj > qty_dec:
            qty_dec = adj

    # פורמט טקסטואלי לפי quantityPrecision
    qty_precision = info.get("quantityPrecision")
    if isinstance(qty_precision, int) and qty_precision >= 0:
        q = Decimal(1).scaleb(-qty_precision)
        qty_str = format(qty_dec.quantize(q, rounding=ROUND_DOWN).normalize(), "f")
    else:
        qty_str = format(qty_dec.normalize(), "f")

    return {
        "qty": float(qty_dec),
        "qty_str": qty_str,
        "ok": True,
        "min_notional": float(min_notional),
        "notional": float(notional),
    }






















