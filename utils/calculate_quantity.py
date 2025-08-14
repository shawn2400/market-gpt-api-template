# utils/calculate_quantity.py

import logging
from math import ceil
from decimal import Decimal, ROUND_DOWN, InvalidOperation
from typing import Dict, Any

from utils.binance_client import futures_exchange_info_safe

# קאש פשוט (זיכרון בלבד)
_precision_cache: Dict[str, Dict[str, float]] = {}

# --------- עזרי Decimal בטוחים ---------
def _to_decimal(x) -> Decimal:
    try:
        return Decimal(str(x))
    except Exception:
        return Decimal("0")

def _decimals_from_step(step: Decimal) -> int:
    """
    כמה ספרות אחרי הנקודה נדרשות כדי לייצג את ה-step (למשל 0.001 -> 3).
    """
    s = format(step.normalize(), "f")
    if "." in s:
        return len(s.split(".")[1].rstrip("0"))
    return 0

def _round_to_step(value: Decimal, step: Decimal) -> Decimal:
    """
    עיגול כלפי מטה ל־stepSize באמצעות Decimal.quantize.
    """
    if step <= 0:
        return value
    # scale = מספר ספרות אחרי הנקודה (לפי ה-step)
    decimals = _decimals_from_step(step)
    quantum = Decimal(1).scaleb(-decimals)
    # נחלק ל-step, נחתוך מטה, נחזיר לקנה מידה
    try:
        units = (value / step).to_integral_value(rounding=ROUND_DOWN)
        return (units * step).quantize(quantum, rounding=ROUND_DOWN)
    except (InvalidOperation, ZeroDivisionError):
        return Decimal("0")

def _round_to_tick(price: Decimal, tick: Decimal) -> Decimal:
    """
    עיגול מחיר כלפי מטה ל־tickSize (לשמירה על תאימות לפילטר מחיר).
    """
    if tick <= 0:
        return price
    decimals = _decimals_from_step(tick)
    quantum = Decimal(1).scaleb(-decimals)
    try:
        units = (price / tick).to_integral_value(rounding=ROUND_DOWN)
        return (units * tick).quantize(quantum, rounding=ROUND_DOWN)
    except (InvalidOperation, ZeroDivisionError):
        return price

# --------- שליפת precision מה־exchangeInfo (עם cache) ---------
def get_precision_info(symbol: str) -> Dict[str, float]:
    sym = (symbol or "").upper().strip()
    if not sym:
        logging.error("[BINANCE] ❌ סמל ריק ל-get_precision_info")
        return {"stepSize": 0.01, "minQty": 0.0, "tickSize": 0.01, "minNotional": 0.0}

    if sym in _precision_cache:
        return _precision_cache[sym]

    try:
        info = futures_exchange_info_safe() or {}
        symbols = info.get("symbols", [])
        for s in symbols:
            if (s or {}).get("symbol") == sym:
                step_size = Decimal("0.01")
                min_qty = Decimal("0")
                tick_size = Decimal("0.01")
                min_notional = Decimal("0")

                for f in s.get("filters", []):
                    ftype = f.get("filterType")
                    if ftype == "LOT_SIZE":
                        step_size = _to_decimal(f.get("stepSize") or "0.01")
                        min_qty = _to_decimal(f.get("minQty") or "0")
                    elif ftype == "PRICE_FILTER":
                        tick_size = _to_decimal(f.get("tickSize") or "0.01")
                    elif ftype in ("MIN_NOTIONAL", "NOTIONAL"):
                        # ב־USDT-M futures לעיתים זה "NOTIONAL"
                        mn = f.get("notional") or f.get("minNotional")
                        if mn is not None:
                            min_notional = _to_decimal(mn)

                result = {
                    "stepSize": float(step_size),
                    "minQty": float(min_qty),
                    "tickSize": float(tick_size),
                    "minNotional": float(min_notional),
                }
                _precision_cache[sym] = result
                return result

        logging.warning(f"[BINANCE] ⚠️ סימבול {sym} לא נמצא ב־exchange_info")
    except Exception as e:
        logging.error(f"[BINANCE] ❌ שגיאה בשליפת exchange_info עבור {sym}: {e}")

    return {"stepSize": 0.01, "minQty": 0.0, "tickSize": 0.01, "minNotional": 0.0}

# --------- API ציבורי ---------
def round_step(value: float, step: float) -> float:
    """
    עיגול כמות כלפי מטה ל־stepSize.
    """
    v = _to_decimal(value)
    s = _to_decimal(step)
    return float(_round_to_step(v, s))

def round_tick(price: float, tick_size: float) -> float:
    """
    עיגול מחיר כלפי מטה ל־tickSize.
    """
    p = _to_decimal(price)
    t = _to_decimal(tick_size)
    return float(_round_to_tick(p, t))

def _ensure_notional(qty: Decimal, price: Decimal, min_notional: Decimal, step: Decimal) -> Decimal:
    """
    מוודא ש-qty*price ≥ min_notional. אם לא — מעלה את הכמות לסטפ הקרוב שמקיים את הסף.
    """
    if min_notional <= 0:
        return qty
    try:
        notional = qty * price
        if notional >= min_notional:
            return qty
        # נדרשת כמות מינימלית:
        needed_qty = (min_notional / price)
        # העלאה ל-step הקרוב מעלה:
        if step > 0:
            units = (needed_qty / step).to_integral_value(rounding=ROUND_DOWN)
            # אם units*step עדיין קטן — נוסיף 1 יחידת step
            cand = (units * step)
            if cand * price < min_notional:
                cand = (units + 1) * step
            return cand
        return needed_qty
    except Exception:
        return qty

def calculate_quantity(symbol: str, entry_price: float, leverage: float, budget_usdt: float) -> float:
    """
    מחשב כמות חוזים לפוזיציית Futures:
      qty ≈ (budget_usdt * leverage) / entry_price
    תוך כיבוד:
      - LOT_SIZE (stepSize, minQty)
      - PRICE_FILTER (tickSize) לעיגול מחיר (אם תרצה להשתמש גם במחיר)
      - MIN_NOTIONAL/NOTIONAL (אם קיים)
    מחזיר 0.0 אם לא עומדים במינימום.
    """
    try:
        if entry_price <= 0:
            raise ValueError("entry_price must be positive")
        if leverage <= 0:
            raise ValueError("leverage must be positive")
        if budget_usdt <= 0:
            raise ValueError("budget_usdt must be positive")

        prec = get_precision_info(symbol)
        step_size = _to_decimal(prec.get("stepSize", 0.01))
        min_qty = _to_decimal(prec.get("minQty", 0.0))
        tick_size = _to_decimal(prec.get("tickSize", 0.01))  # טרם בשימוש ישיר פה, שמור לזמינות
        min_notional = _to_decimal(prec.get("minNotional", 0.0))

        price = _to_decimal(entry_price)
        lev = _to_decimal(leverage)
        budget = _to_decimal(budget_usdt)

        # כמות גולמית
        raw_qty = (budget * lev) / price

        # עיגול ל־stepSize (כלפי מטה)
        qty = _round_to_step(raw_qty, step_size)

        # כבדיקת סף minNotional, נעלה את הכמות (לא נרד) אם צריך:
        qty = _ensure_notional(qty, price, min_notional, step_size)

        # דרישת minQty
        if qty < min_qty:
            logging.warning(f"[QTY] כמות נמוכה מהמינימום: qty={qty} < minQty={min_qty} (symbol={symbol})")
            return 0.0

        # רווד לדיוק ה־step
        decimals = _decimals_from_step(step_size)
        qty = qty.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_DOWN)

        if qty <= 0:
            logging.warning(f"[QTY] לאחר עיגולים הכמות אפסית/שלילית (symbol={symbol})")
            return 0.0

        return float(qty)
    except Exception as e:
        logging.error(f"[QTY] ❌ שגיאה בחישוב כמות עבור {symbol}: {e}", exc_info=True)
        return 0.0







