# utils/order_sanity.py
from __future__ import annotations
from math import floor
from typing import Dict, Any, Tuple
from utils.binance_client import exchange_info as _exchange_info
from utils.config import MAX_LEVERAGE, MIN_NOTIONAL_USDT, DEFAULT_QTY_STEP, DEFAULT_PRICE_TICK

def _round_step(val: float, step: float) -> float:
    if step <= 0:
        return val
    return floor(val / step) * step

def normalize_order(symbol: str, qty: float, price: float) -> Tuple[float, float]:
    info: Dict[str, Any] = {}
    try:
        info = _exchange_info() or {}
    except Exception:
        info = {}
    step = DEFAULT_QTY_STEP
    tick = DEFAULT_PRICE_TICK
    for it in (info.get("symbols") or []):
        if (it.get("symbol") or "").upper() == symbol.upper():
            try:
                fl = it.get("filters") or []
                lot = next((f for f in fl if f.get("filterType") == "LOT_SIZE"), {})
                prf = next((f for f in fl if f.get("filterType") in ("PRICE_FILTER", "MARKET_LOT_SIZE")), {})
                step = float(lot.get("stepSize") or step)
                tick = float(prf.get("tickSize") or tick)
            except Exception:
                pass
            break
    return (_round_step(qty, step), _round_step(price, tick))

def enforce_min_notional(qty: float, price: float) -> bool:
    return (qty * price) >= float(MIN_NOTIONAL_USDT)

def clamp_leverage(lev: int) -> int:
    try:
        return max(1, min(int(MAX_LEVERAGE), int(lev)))
    except Exception:
        return 1
