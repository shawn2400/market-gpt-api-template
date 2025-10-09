# utils/position_sizing.py
import os, math, json
from typing import Optional, Dict
from contextlib import suppress

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
    """
    קובע מינוף סופי לפי קאפים גלובליים/לסימבול.
    """
    max_lev = _env_int("MAX_LEVERAGE", 20)

    # קאפ פר-סימבול מה-ENV אם קיים (עם הקשחה לגרשיים חיצוניים בטעות)
    sym_cap = None
    caps_raw = os.getenv("LEVERAGE_SYMBOL_CAPS", "")
    if caps_raw:
        caps = None
        with suppress(Exception):
            caps = json.loads(caps_raw)
        if caps is None:
            with suppress(Exception):
                caps = json.loads(caps_raw.strip("'\""))
        if isinstance(caps, dict):
            with suppress(Exception):
                sym_cap = int(caps.get(symbol, max_lev))

    # מפת ADX אופציונלית – אם קיימת ולא משולבת במקום אחר, נשמור כמקסימום עליון “רך”
    adx_cap = None
    adx_map_raw = os.getenv("LEV_ADX_MAP_JSON", "")
    if adx_map_raw:
        adx_map = None
        with suppress(Exception):
            adx_map = json.loads(adx_map_raw)
        if isinstance(adx_map, dict) and adx_map:
            with suppress(Exception):
                adx_cap = max(int(v) for v in adx_map.values())

    caps_to_apply = [req_leverage or 0, max_lev]
    if sym_cap: caps_to_apply.append(sym_cap)
    if adx_cap: caps_to_apply.append(adx_cap)

    lev = max(1, min([x for x in caps_to_apply if x > 0]))
    return lev

def _symbol_filters_from_env() -> Dict[str, float]:
    """
    אם אין לך cache של exchange info—נשתמש ב-ENV כ-fallback.
    """
    qty_step = _env_float("DEFAULT_QTY_STEP", 0.001)
    price_tick = _env_float("DEFAULT_PRICE_TICK", 0.01)
    min_notional = _env_float("MIN_NOTIONAL_USDT", 5.0)
    return {"qty_step": qty_step, "price_tick": price_tick, "min_notional": min_notional}

def _symbol_filters(symbol: str) -> Dict[str, float]:
    """
    מנסה למשוך פילטרים אמיתיים מהבורסה (קאש פנימי אם קיים), אחרת נופל ל-ENV.
    מצופה שפונקציה דומה תחזיר dict עם מפתחות כמו stepSize/tickSize/minNotional.
    """
    with suppress(Exception):
        from utils.exchange_info import get_symbol_filters  # type: ignore
        f = get_symbol_filters(symbol)  # יכול להיות dict או None
        if f:
            return {
                "qty_step": float(f.get("stepSize") or f.get("qty_step") or _env_float("DEFAULT_QTY_STEP", 0.001)),
                "price_tick": float(f.get("tickSize") or f.get("price_tick") or _env_float("DEFAULT_PRICE_TICK", 0.01)),
                "min_notional": float(f.get("minNotional") or f.get("min_notional") or _env_float("MIN_NOTIONAL_USDT", 5.0)),
            }
    # פולבאק
    return _symbol_filters_from_env()

def _step_down(x: float, step: float) -> float:
    if step <= 0:
        return x
    return max(step, math.floor(x / step) * step)

def auto_qty(symbol: str, symbol_price: float, leverage: int) -> Optional[float]:
    """
    מחשב כמות לפי ENV:
      AUTO_QTY_ENABLE=1
      AUTO_QTY_BUDGET_USDT=100
      AUTO_QTY_MARGIN_BUFFER_PCT=0.20
    ומכבד:
      MAX_TRADE_BUDGET, DEFAULT_QTY_STEP, MIN_NOTIONAL_USDT
    """
    if os.getenv("AUTO_QTY_ENABLE", "0") != "1":
        return None

    # דיפולט שדרוג לבקשתך: 100$
    budget = _env_float("AUTO_QTY_BUDGET_USDT", 100.0)
    buf    = _env_float("AUTO_QTY_MARGIN_BUFFER_PCT", 0.20)
    max_budget = _env_float("MAX_TRADE_BUDGET", budget)
    budget = min(budget, max_budget)

    lev = _leverage_cap(symbol, int(leverage or 0))

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

    return stepped if stepped > 0 else None

def ensure_final_qty(ticket: dict, symbol_price: float) -> dict:
    """
    קובע leverage סופי לפי קאפים; ואם qty חסר/0 – מחשב לפי AUTO_QTY_*.
    מינוף דיפולטי הוגדל ל-10 בבקשתך.
    """
    symbol = (ticket.get("symbol") or "").upper()
    req_lev = int(ticket.get("leverage") or ticket.get("lev") or _env_int("MIN_LEVERAGE", 10))
    final_lev = _leverage_cap(symbol, req_lev)
    ticket["leverage"] = final_lev

    q = ticket.get("qty") or ticket.get("quantity")
    qf = float(q) if q is not None else 0.0
    if q is None or qf <= 0.0:
        q_calc = auto_qty(symbol, float(symbol_price), int(final_lev))
        if q_calc and q_calc > 0:
            ticket["qty"] = q_calc

    # אם תרצה שגם התקציב יופיע בכרטיס—נכניס דיפולט רק אם חסר:
    if "budget_usd" not in ticket and os.getenv("AUTO_QTY_ENABLE", "0") == "1":
        ticket["budget_usd"] = _env_float("AUTO_QTY_BUDGET_USDT", 100.0)

    return ticket



