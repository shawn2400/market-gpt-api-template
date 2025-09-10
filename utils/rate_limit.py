# utils/rate_limit.py
from __future__ import annotations
import time
from typing import Dict, Tuple
from fastapi import HTTPException

_buckets: Dict[str, Tuple[float, float, int, float]] = {}

def allow(name: str, capacity: int, per_seconds: int) -> bool:
    now = time.time()
    tokens, last, cap, rate = _buckets.get(name, (capacity, now, capacity, capacity / per_seconds))
    tokens = min(cap, tokens + (now - last) * rate)
    if tokens >= 1.0:
        tokens -= 1.0
        _buckets[name] = (tokens, now, cap, rate)
        return True
    _buckets[name] = (tokens, now, cap, rate)
    return False

def require(name: str, capacity: int, per_seconds: int):
    if not allow(name, capacity, per_seconds):
        raise HTTPException(status_code=429, detail="rate limit")



