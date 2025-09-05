# storage/kv.py
from __future__ import annotations
import os, time, json, threading
from typing import Optional

_REDIS_URL = os.getenv("REDIS_URL", "").strip()
_redis = None
if _REDIS_URL:
    try:
        import redis  # type: ignore
        _redis = redis.from_url(_REDIS_URL, decode_responses=True)
    except Exception:
        _redis = None

_mem = {}
_lock = threading.Lock()

def setex(key: str, ttl: int, value: str) -> None:
    if _redis:
        try:
            _redis.setex(key, ttl, value)
            return
        except Exception:
            pass
    with _lock:
        _mem[key] = (time.time() + ttl, value)

def get(key: str) -> Optional[str]:
    if _redis:
        try:
            return _redis.get(key)
        except Exception:
            pass
    with _lock:
        v = _mem.get(key)
        if not v:
            return None
        exp, val = v
        if exp < time.time():
            _mem.pop(key, None)
            return None
        return val
