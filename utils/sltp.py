# utils/sltp.py
from __future__ import annotations
from typing import Optional, Tuple
from decimal import Decimal, ROUND_DOWN, ROUND_UP, InvalidOperation

"""
SL/TP calculator:
- תומך בערכים מוחלטים או באחוזים (0<value<1 → אחוז).
- פולבק ATR אם לא נמסרו sl/tp.
- עיגון אופציונלי לפי tickSize בכיוון "בטוח" להפעלה.
- גרסה אוטומטית לפי סימבול: calc_sl_tp_for_symbol(...)
"""

def _to_dec(x) -> Decimal:
    try:
        return Decimal(str(x))
    except Exception:
        return Decimal(0)

def _is_percent(x: float) -> bool:
    try:
        x = float(x)
        return 0 < x < 1
    except Exception:
        return False

def _round_to_tick(price: float, tick_size: float, *, direction: str) -> float:
    if not tick_size or float(tick_size) <= 0:
        return float(price)
    try:
        p = _to_dec(price)
        t = _to_dec(tick_size)
        mult = (p / t).to_integral_value(rounding=ROUND_UP if direction == "UP" else ROUND_DOWN)
        val = (mult * t).quantize(t, rounding=ROUND_DOWN)
        return float(val)
    except (InvalidOperation, ValueError):
        return float(price)

def _coerce_direction(entry: float, target: float, *, side: str, is_sl: bool, was_percent_or_atr: bool) -> float:
    e = float(entry); x = float(target); s = (side or "").upper()
    if not was_percent_or_atr:
        return x
    if s == "LONG":
        if is_sl and x >= e:  return e * 0.999999
        if (not is_sl) and x <= e: return e * 1.000001
    else:
        if is_sl and x <= e:  return e * 1.000001
        if (not is_sl) and x >= e: return e * 0.999999
    return x

def calc_sl_tp(entry: float, side: str,
               sl: Optional[float] = None, tp: Optional[float] = None,
               atr: Optional[float] = None, atr_mult: float = 1.5) -> Tuple[Optional[float], Optional[float]]:
    side_u = (side or "").upper()
    sl_price: Optional[float] = None
    tp_price: Optional[float] = None

    if atr and (sl is None and tp is None):
        if side_u == "LONG":
            sl_price = float(_to_dec(entry) - _to_dec(atr_mult) * _to_dec(atr))
            tp_price = float(_to_dec(entry) + _to_dec(atr_mult) * _to_dec(atr))
        else:
            sl_price = float(_to_dec(entry) + _to_dec(atr_mult) * _to_dec(atr))
            tp_price = float(_to_dec(entry) - _to_dec(atr_mult) * _to_dec(atr))
        sl_price = _coerce_direction(entry, sl_price, side=side_u, is_sl=True,  was_percent_or_atr=True)
        tp_price = _coerce_direction(entry, tp_price, side=side_u, is_sl=False, was_percent_or_atr=True)
        return sl_price, tp_price

    if sl is not None:
        if _is_percent(sl):
            sl_price = float(_to_dec(entry) * (Decimal(1) - _to_dec(sl))) if side_u == "LONG" else float(_to_dec(entry) * (Decimal(1) + _to_dec(sl)))
            sl_price = _coerce_direction(entry, sl_price, side=side_u, is_sl=True, was_percent_or_atr=True)
        else:
            sl_price = float(sl)

    if tp is not None:
        if _is_percent(tp):
            tp_price = float(_to_dec(entry) * (Decimal(1) + _to_dec(tp))) if side_u == "LONG" else float(_to_dec(entry) * (Decimal(1) - _to_dec(tp)))
            tp_price = _coerce_direction(entry, tp_price, side=side_u, is_sl=False, was_percent_or_atr=True)
        else:
            tp_price = float(tp)

    return sl_price, tp_price

def calc_sl_tp_with_tick(entry: float, side: str,
                         sl: Optional[float] = None, tp: Optional[float] = None,
                         atr: Optional[float] = None, atr_mult: float = 1.5,
                         *, tick_size: Optional[float] = None) -> Tuple[Optional[float], Optional[float]]:
    sl_price, tp_price = calc_sl_tp(entry, side, sl=sl, tp=tp, atr=atr, atr_mult=atr_mult)
    if tick_size and float(tick_size) > 0:
        side_u = (side or "").upper()
        if sl_price is not None:
            sl_price = _round_to_tick(sl_price, tick_size, direction=("UP" if side_u == "LONG" else "DOWN"))
        if tp_price is not None:
            tp_price = _round_to_tick(tp_price, tick_size, direction=("DOWN" if side_u == "LONG" else "UP"))
    return sl_price, tp_price

def calc_sl_tp_for_symbol(symbol: str, entry: float, side: str,
                          sl: Optional[float] = None, tp: Optional[float] = None,
                          atr: Optional[float] = None, atr_mult: float = 1.5) -> Tuple[Optional[float], Optional[float]]:
    tick_size = None
    try:
        from utils.binance_client import get_symbol_filters
        f = get_symbol_filters(symbol)
        tick_size = float(f.get("tickSizeStr")) if f and f.get("tickSizeStr") else None
    except Exception:
        tick_size = None
    return calc_sl_tp_with_tick(entry, side, sl=sl, tp=tp, atr=atr, atr_mult=atr_mult, tick_size=tick_size)








       






