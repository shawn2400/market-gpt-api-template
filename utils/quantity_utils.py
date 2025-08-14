# utils/quantity_utils.py

import math
import logging
from typing import Any, Optional, Dict

from utils.binance_client import get_client, futures_exchange_info_safe

# --- Cache לזיכרון לדיוקים/אינפו ---
_precision_cache: Dict[str, Dict[str, float]] = {}

# ---------- Helpers ----------
def _infer_quantity_precision_from_step(step_size: float) -> int:
    """
    גזירת מספר ספרות אחרי הנקודה מתוך stepSize (למשל 0.001 -> 3).
    """
    if step_size <= 0:
        return 4
    if step_size >= 1:
        return 0
    return max(0, int(round(-math.log10(step_size), 0)))

def _round_down_to_step(value: float, step: float) -> float:
    """
    עיגול מטה לערך הקרוב התואם את ה-stepSize (בטוח ל-floating).
    """
    if step <= 0:
        return value
    return math.floor(value / step) * step

def round_step(value: float, step: float) -> float:
    """אליאס ציבורי לעיגול לפי step."""
    return _round_down_to_step(value, step)

def round_tick(price: float, tick_size: float) -> float:
    """עיגול מטה למחיר התואם את ה-tickSize."""
    try:
        if tick_size <= 0:
            return price
        return math.floor(price / tick_size) * tick_size
    except Exception as e:
        logging.error(f"[quantity_utils] שגיאה בעיגול לפי tick: {e}")
        return price

# ---------- Precision Info ----------
def _get_precision_info_fallback(symbol: str) -> Dict[str, float]:
    """
    שליפת דיוקים מתוך futures_exchange_info_safe (עם Cache).
    """
    sym = symbol.upper().strip()
    if sym in _precision_cache:
        return _precision_cache[sym]

    info = futures_exchange_info_safe() or {}
    for s in info.get("symbols", []):
        if s.get("symbol") == sym:
            step_size = 0.01
            min_qty = 0.0
            tick_size = 0.01
            for f in s.get("filters", []):
                ftype = f.get("filterType")
                if ftype == "LOT_SIZE":
                    step_size = float(f.get("stepSize", step_size))
                    min_qty = float(f.get("minQty", min_qty))
                elif ftype == "PRICE_FILTER":
                    tick_size = float(f.get("tickSize", tick_size))
            precision = {
                "stepSize": step_size,
                "minQty": min_qty,
                "tickSize": tick_size,
                "quantityPrecision": _infer_quantity_precision_from_step(step_size),
            }
            _precision_cache[sym] = precision
            return precision

    logging.warning(f"[quantity_utils] ⚠️ {sym} לא נמצא ב-exchangeInfo; שימוש בדיפולטים")
    precision = {"stepSize": 0.01, "minQty": 0.0, "tickSize": 0.01, "quantityPrecision": 2}
    _precision_cache[sym] = precision
    return precision

def get_precision_info(symbol: str) -> Dict[str, float]:
    """
    מחזיר פרטי דיוק: stepSize, minQty, tickSize, quantityPrecision.
    """
    try:
        return _get_precision_info_fallback(symbol)
    except Exception as e:
        logging.debug(f"[quantity_utils] precision fallback error: {e}")
        return {"stepSize": 0.01, "minQty": 0.0, "tickSize": 0.01, "quantityPrecision": 2}

# ---------- Price ----------
def get_price(symbol: str) -> Optional[float]:
    """
    מחזיר מחיר נוכחי דרך הלקוח. None במקרה כשל.
    """
    try:
        client = get_client()
        t = client.get_symbol_ticker(symbol=symbol.upper())
        return float(t.get("price"))
    except Exception as e:
        logging.warning(f"[quantity_utils] שגיאה בשליפת מחיר עבור {symbol}: {e}")
        return None

# ---------- Quantity APIs ----------
def calculate_quantity_usdt(symbol: str, usdt_amount: float) -> float:
    """
    מחשב כמות לפי סכום ב־USDT (ללא מינוף), כולל עיגול ל-stepSize ובדיקת minQty.
    """
    price = get_price(symbol)
    if not price or price <= 0 or usdt_amount <= 0:
        return 0.0

    raw_qty = usdt_amount / price
    p = get_precision_info(symbol)
    step = float(p.get("stepSize", 0.01))
    min_qty = float(p.get("minQty", 0.0))
    precision = int(p.get("quantityPrecision", _infer_quantity_precision_from_step(step)))

    qty = _round_down_to_step(raw_qty, step)
    if qty < min_qty:
        logging.warning(f"[quantity_utils] כמות נמוכה מהמינימום: {qty} < {min_qty} (symbol={symbol})")
        return 0.0
    return round(qty, precision)

def auto_risk_allocation(symbol: str, risk_usd: float, sl_pct: Optional[float] = None) -> float:
    """
    מקצה כמות לפי סיכון בדולרים. אם sl_pct (אחוז מרחק SL) סופק — מתחשב בו.
    ללא sl_pct: qty ≈ risk / price.
    """
    price = get_price(symbol)
    if not price or risk_usd <= 0:
        return 0.0

    if sl_pct and sl_pct > 0:
        # הפסד ≈ price * qty * (sl_pct/100)  ⇒  qty ≈ risk / (price * sl_pct/100)
        raw_qty = risk_usd / (price * (sl_pct / 100.0))
    else:
        raw_qty = risk_usd / price

    p = get_precision_info(symbol)
    step = float(p.get("stepSize", 0.01))
    min_qty = float(p.get("minQty", 0.0))
    precision = int(p.get("quantityPrecision", _infer_quantity_precision_from_step(step)))

    qty = _round_down_to_step(raw_qty, step)
    if qty < min_qty:
        logging.warning(f"[quantity_utils] כמות נמוכה מהמינימום (risk): {qty} < {min_qty} (symbol={symbol})")
        return 0.0
    return round(qty, precision)

def calculate_quantity(symbol: str, price: float, leverage: float, budget: float) -> float:
    """
    מחשב כמות לפי תקציב, מחיר ומינוף. כולל עיגול ל-stepSize ובדיקת minQty.
    """
    if price <= 0 or leverage <= 0 or budget <= 0:
        return 0.0

    notional = budget * leverage
    raw_qty = notional / price

    p: Any = get_precision_info(symbol)
    step = float(p.get("stepSize", 0.01))
    min_qty = float(p.get("minQty", 0.0))
    precision = int(p.get("quantityPrecision", _infer_quantity_precision_from_step(step)))

    qty = _round_down_to_step(raw_qty, step)
    if qty < min_qty:
        logging.warning(f"[quantity_utils] כמות נמוכה מהמינימום (budget/leverage): {qty} < {min_qty} (symbol={symbol})")
        return 0.0

    return round(qty, precision)









