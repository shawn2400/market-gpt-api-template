# utils/quantize.py
from __future__ import annotations
from decimal import Decimal, ROUND_DOWN, InvalidOperation
from typing import Dict

# מטמון פילטרים לסשן
_FILTERS: Dict[str, Dict[str, float]] = {}

def get_filters(client, symbol: str) -> Dict[str, float]:
    s = symbol.upper()
    if s in _FILTERS:
        return _FILTERS[s]
    info = client.futures_exchange_info()
    tick = 0.01
    step = 0.001
    for sym in info.get("symbols", []):
        if sym.get("symbol") == s:
            for f in sym.get("filters", []):
                if f.get("filterType") == "PRICE_FILTER":
                    tick = float(f.get("tickSize", tick))
                elif f.get("filterType") == "LOT_SIZE":
                    step = float(f.get("stepSize", step))
            break
    _FILTERS[s] = {"tick": tick, "step": step}
    return _FILTERS[s]

def _dec(x) -> Decimal:
    return Decimal(str(x))

def quantize_price(symbol: str, price: float, flt: Dict[str, float]) -> float:
    """ מעגל מחיר לפי tick בעזרת Decimal (למטה) """
    tick = _dec(flt["tick"])
    p = _dec(price)
    try:
        q = (p / tick).to_integral_value(rounding=ROUND_DOWN) * tick
    except InvalidOperation:
        q = p
    return float(q)

def quantize_qty(symbol: str, qty: float, flt: Dict[str, float]) -> float:
    """ מעגל כמות לפי step בעזרת Decimal (למטה) """
    step = _dec(flt["step"])
    qv = _dec(qty)
    try:
        q = (qv / step).to_integral_value(rounding=ROUND_DOWN) * step
    except InvalidOperation:
        q = qv
    # החזרה עם דיוק מספיק גבוה כדי לא לחצות את ה-step
    return float(q.normalize())
