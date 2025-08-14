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





















