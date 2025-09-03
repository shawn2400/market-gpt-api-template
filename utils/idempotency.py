# utils/idempotency.py
from __future__ import annotations
import time, threading, os
from typing import Optional

_REDIS_URL = os.getenv("REDIS_URL", "").strip()
_TTL_DEFAULT = int(os.getenv("IDEMPOTENCY_DEFAULT_TTL_SEC", "120"))

# In-memory fallback
_store: dict[str, float] = {}
_lock = threading.Lock()

# Optional Redis
_redis = None
if _REDIS_URL:
    try:
        import redis  # type: ignore
        _redis = redis.from_url(_REDIS_URL, decode_responses=True)
    except Exception:
        _redis = None

def claim(key: str, ttl_sec: Optional[int] = None) -> bool:
    """
    נסה 'לתפוס' מפתח אידמפוטנציה.
    True → הצלחה (לא קיים בעבר).
    False → כבר קיים (לדחיית פעולה כפולה).
    """
    ttl = int(ttl_sec or _TTL_DEFAULT)
    if _redis:
        try:
            # SET NX EX seconds → 1 רק אם לא קיים
            return bool(_redis.set(name=f"idp:{key}", value="1", nx=True, ex=ttl))
        except Exception:
            pass
    now = time.monotonic()
    with _lock:
        # ניקוי ישנים
        rm = [k for k, exp in _store.items() if exp < now]
        for k in rm: _store.pop(k, None)
        if key in _store and _store[key] > now:
            return False
        _store[key] = now + ttl
        return True

def clear(key: str) -> None:
    if _redis:
        try:
            _redis.delete(f"idp:{key}")
            return
        except Exception:
            pass
    with _lock:
        _store.pop(key, None)

__all__ = ["claim", "clear"]
