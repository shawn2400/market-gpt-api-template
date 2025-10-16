# -*- coding: utf-8 -*-
from __future__ import annotations
import os, time
from typing import Tuple, Optional, Dict, Any
from contextlib import suppress

_COOLDOWN: Dict[str, float] = {}

def _envf(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default

def _eni(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default

# Redis אופציונלי לקול־דאון across workers
try:
    import redis  # type: ignore
    _REDIS_URL = os.getenv("REDIS_URL", "").strip()
    _R = redis.Redis.from_url(_REDIS_URL, decode_responses=True) if _REDIS_URL else None
except Exception:
    _R = None

def _set_cooldown(sym: str, seconds: int) -> None:
    sym = sym.upper()
    until = time.time() + max(1, seconds)
    _COOLDOWN[sym] = until
    if _R:
        with suppress(Exception):
            _R.setex(f"vg:cool:{sym}", seconds, str(int(until)))

def _cooldown_active(sym: str) -> bool:
    sym = sym.upper()
    now = time.time()
    if sym in _COOLDOWN and _COOLDOWN[sym] > now:
        return True
    if _R:
        with suppress(Exception):
            v = _R.get(f"vg:cool:{sym}")
            if v and float(v) > now:
                _COOLDOWN[sym] = float(v)
                return True
    return False

def check(symbol: str, atr_pct: float) -> (bool, str):
    """
    מחזיר (מותר, סיבה/״ok״). אם ATR% חורג – מפעיל קול־דאון.
    ENV:
      VOLATILITY_GATE_ATRPCT (ברירת מחדל 1.8)
      VOLATILITY_COOLDOWN_SEC (ברירת מחדל 300)
    """
    max_atr = _envf("VOLATILITY_GATE_ATRPCT", 1.8)
    cool = _eni("VOLATILITY_COOLDOWN_SEC", 300)
    sym = symbol.upper()

    if _cooldown_active(sym):
        return False, "cooldown_active"

    if atr_pct > max_atr:
        _set_cooldown(sym, cool)
        return False, "atr_pct_exceeds_gate"

    return True, "ok"
