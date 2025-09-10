# utils/bad_actor_store.py
from __future__ import annotations
import time, os
from typing import Dict

_CONSEC_FAILS = {}
_COOLDOWN_UNTIL = {}

BAD_ACTOR_CONSEC_N = int(os.getenv("BAD_ACTOR_CONSEC_N", "3"))
BAD_ACTOR_COOLDOWN_SEC = int(os.getenv("BAD_ACTOR_COOLDOWN_SEC", "900"))  # 15min

def mark_fail(symbol: str) -> None:
    s = symbol.upper()
    _CONSEC_FAILS[s] = _CONSEC_FAILS.get(s, 0) + 1
    if _CONSEC_FAILS[s] >= BAD_ACTOR_CONSEC_N:
        _COOLDOWN_UNTIL[s] = time.time() + BAD_ACTOR_COOLDOWN_SEC

def mark_success(symbol: str) -> None:
    s = symbol.upper()
    _CONSEC_FAILS[s] = 0
    _COOLDOWN_UNTIL.pop(s, None)

def allow_symbol(symbol: str) -> bool:
    s = symbol.upper()
    until = _COOLDOWN_UNTIL.get(s, 0)
    return time.time() >= until
