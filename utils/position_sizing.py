# app/utils/position_sizing.py
import os, math, json
from typing import Optional, Dict

def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default

def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default

def _leverage_cap(symbol: str, req_leverage: int) -> int:
    max_lev = _env_int("MAX_LEVERAGE", 20)
    # קאפ פר-סימבול מה-ENV אם קיים
    caps_raw = os.getenv("LEVERAGE_SYMBOL_CAPS", "")
    sym_cap = None
    if caps_raw:
        try:
            caps = json.loads(caps_raw)
            sym_cap = int(caps.get(symbol, max_lev))
        except Exception:
            sym_cap = None
    # מפת ADX (אופציונלי)
    adx_map_raw = os.getenv("LEV_ADX_MAP_JSON", "")
    adx_cap = None
    if adx_map_raw:
        try:
            adx_map = json.loads(adx_map_raw)
            # בגרסאות רבות מחושב חיצונית; כאן נשאיר כמקסימום אפשרי אם אינדיקציה חסרה
            adx_cap = max(int(v) for v in adx_map.values()) if adx_map else None
        except Exception:
            adx_cap = None

    caps_to_apply = [req_leverage, max_lev]
    if sym_cap: caps_to_apply.append(sym_cap)
    if adx_cap: caps_to_apply.append(adx_cap)
    return max(1, min(caps_to_apply))

def _symbol_filters(symbol: str) -> Dict[str, float]:
    """
    שלוף פקדי בורסת הסימבול אם יש לך cache פנימי; אחרת fallback ל-ENV.
    מצפה שתהיה אצלך פונקציה קיימת ששואבת exchange_info (אם יש – החלף כאן בקריאה אליה).
    """
    qty_step = _env_float("DEFAULT_QTY_STEP", 0.001)
    price_tick = _env_float("DEFAULT_PRICE_TICK", 0.01)
    min_notional = _env_float("MIN_NOTIONAL_USDT", 5.0)
    return {
        "qty_step": qty_step,
        "price_tick": price_tick,
        "min_notional": min_notional,
    }

def _step_down(x: float, step: float) -> float:
    return max(step, math.floor(x / step) * step)

def auto_qty(symbol: str, symbol_price: float, leverage: int) -> Optional[float]:
    if os.getenv("AUTO_QTY_ENABLE", "0") != "1":
        return None

    budget = _env_float("AUTO_QTY_BUDGET_USDT", 50.0)
    buf    = _env_float("AUTO_QTY_MARGIN_BUFFER_PCT", 0.20)
    max_budget = _env_float("MAX_TRADE_BUDGET", budget)
    budget = min(budget, max_budget)

    lev = _leverage_cap(symbol, int(leverage))
    effective = max(0.0, budget * (1.0 - buf))
    if symbol_price <= 0 or lev <= 0 or effective <= 0:
        return None

    raw_qty = (effective * lev) / symbol_price
    f = _symbol_filters(symbol)
    stepped = _step_down(raw_qty, f["qty_step"])

    # ודא notional מינימלי
    if (stepped * symbol_price) < f["min_notional"]:
        needed = (f["min_notional"] / symbol_price)
        stepped = _step_down(needed, f["qty_step"])

    return stepped

def ensure_final_qty(ticket: dict, symbol_price: float) -> dict:
    """
    אם ticket["qty"] חסר/0 – נחשב לפי ה-AUTO_QTY_*.
    כמו כן נכבד קאפים של מינוף.
    """
    symbol = ticket.get("symbol") or ""
    req_lev = int(ticket.get("leverage") or _env_int("MIN_LEVERAGE", 5))
    ticket["leverage"] = _leverage_cap(symbol, req_lev)

    q = ticket.get("qty")
    if (q is None) or (float(q) <= 0.0):
        q_calc = auto_qty(symbol, float(symbol_price), int(ticket["leverage"]))
        if q_calc:
            ticket["qty"] = q_calc
    return ticket
