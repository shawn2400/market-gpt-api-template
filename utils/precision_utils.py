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
    טוען once את exchangeInfo של ה-Futures (עם ריטריי/פולבק שכבר קיימים ב-binance_client).
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

def round_to_precision(value: float, digits: int) -> float:
    """עיגול פשוט ל־N ספרות אחרי הנקודה (ללא התאמה ל־tick/step)."""
    try:
        return round(float(value), int(digits))
    except Exception:
        return float(value)

def _decimal_step_round(value: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        return value
    return (value // step) * step

def apply_price_tick(price: float, symbol: str) -> Tuple[float, str]:
    """
    מעגל מחיר ל־tickSize לפי exchangeInfo ומחזיר (float_dec, string_formatted).
    אם לא נמצא tickSize – מעגל רק לפי pricePrecision.
    """
    info = _find_symbol_info(symbol) or {}
    price_precision = info.get("pricePrecision")
    tick_size = "0"
    for f in info.get("filters", []) or []:
        if f.get("filterType") == "PRICE_FILTER":
            tick_size = f.get("tickSize", "0")
            break

    v = Decimal(str(price))
    t = Decimal(str(tick_size)) if tick_size else Decimal("0")
    dec = _decimal_step_round(v, t) if t > 0 else v

    # פורמט לפי pricePrecision אם ידוע
    if isinstance(price_precision, int) and price_precision >= 0:
        q = Decimal(1).scaleb(-price_precision)
        s = format(dec.quantize(q, rounding=ROUND_DOWN).normalize(), "f")
    else:
        s = format(dec.normalize(), "f")

    return float(dec), s

def apply_qty_step(qty: float, symbol: str) -> Tuple[float, str]:
    """
    מעגל כמות ל־stepSize לפי exchangeInfo ומחזיר (float_dec, string_formatted).
    אם לא נמצא stepSize – מעגל רק לפי quantityPrecision.
    """
    info = _find_symbol_info(symbol) or {}
    qty_precision = info.get("quantityPrecision")
    step_size = "0"
    for f in info.get("filters", []) or []:
        if f.get("filterType") == "LOT_SIZE":
            step_size = f.get("stepSize", "0")
            break

    v = Decimal(str(qty))
    s = Decimal(str(step_size)) if step_size else Decimal("0")
    dec = _decimal_step_round(v, s) if s > 0 else v

    if isinstance(qty_precision, int) and qty_precision >= 0:
        q = Decimal(1).scaleb(-qty_precision)
        out = format(dec.quantize(q, rounding=ROUND_DOWN).normalize(), "f")
    else:
        out = format(dec.normalize(), "f")

    return float(dec), out

# ---------------------- NEW: פילטרים שימושיים + חישוב כמות מהתקציב ----------------------

def _symbol_filters(symbol: str) -> Dict[str, Any]:
    """
    מאתר tickSize/stepSize/minQty/minNotional (אם קיים) מתוך exchangeInfo.
    """
    info = _find_symbol_info(symbol) or {}
    tick_size = None
    step_size = None
    min_qty = None
    min_notional = None

    for f in info.get("filters", []) or []:
        t = f.get("filterType")
        if t == "PRICE_FILTER":
            tick_size = f.get("tickSize")
        elif t == "LOT_SIZE":
            step_size = f.get("stepSize")
            min_qty = f.get("minQty")
        elif t in ("MIN_NOTIONAL", "NOTIONAL"):
            # ב-USDT-M futures זה בד"כ MIN_NOTIONAL עם מפתח 'notional'
            mn = f.get("notional") or f.get("minNotional")
            if mn is not None:
                min_notional = mn

    def _safe_float(x):
        try:
            return float(x)
        except Exception:
            return None

    return {
        "tick_size": _safe_float(tick_size),
        "step_size": _safe_float(step_size),
        "min_qty": _safe_float(min_qty),
        "min_notional": _safe_float(min_notional),
        "pricePrecision": int(info.get("pricePrecision", 2)) if info else 2,
        "quantityPrecision": int(info.get("quantityPrecision", 3)) if info else 3,
    }

def calc_quantity_from_budget(
    symbol: str,
    *,
    price: float,
    budget_usd: float,
    leverage: float = 1.0,
) -> Dict[str, Any]:
    """
    מחשב כמות לפי תקציב×מינוף, עם עיגון ל-LOT_SIZE ועמידה ב-MIN_NOTIONAL (אם קיים).
    מחזיר: {"ok":bool, "qty":float, "qty_str":str, "notional":float, "min_notional":float|None, "reason":str?}
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
    mn = flt.get("min_notional")

    if mn is not None and notional < mn:
        # נסה להעלות כמות למינימום נומינלי (פולבק עדין)
        needed_qty = (mn / price) * 1.001
        qty_dec2, qty_str2 = apply_qty_step(needed_qty, symbol)
        notional2 = qty_dec2 * price
        if notional2 + 1e-9 < mn:
            return {
                "ok": False,
                "reason": "below_min_notional",
                "qty": qty_dec,
                "qty_str": qty_str,
                "notional": notional,
                "min_notional": mn,
            }
        qty_dec, qty_str, notional = qty_dec2, qty_str2, notional2

    if qty_dec <= 0:
        return {"ok": False, "reason": "qty_rounded_to_zero", "min_notional": mn}

    return {
        "ok": True,
        "qty": float(qty_dec),
        "qty_str": qty_str,
        "notional": float(notional),
        "min_notional": float(mn) if mn is not None else None,
    }























