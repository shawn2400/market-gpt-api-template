# utils/cache.py
from __future__ import annotations
import time
import threading
from typing import Any, Callable, Optional, Dict, Tuple

class _TTLCache:
    def __init__(self, max_size: int = 512):
        self._max = max_size
        self._d: Dict[str, Tuple[float, Any]] = {}
        self._lock = threading.RLock()

    def _purge(self) -> None:
        if len(self._d) <= self._max:
            return
        # מחיקת חצי מהפריטים הישנים
        now = time.time()
        items = sorted(self._d.items(), key=lambda kv: kv[1][0])
        for k, _ in items[: len(items)//2]:
            self._d.pop(k, None)

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            item = self._d.get(key)
            if not item:
                return None
            exp, val = item
            if exp < time.time():
                self._d.pop(key, None)
                return None
            return val

    def set(self, key: str, value: Any, ttl_sec: float) -> Any:
        exp = time.time() + max(0.0, float(ttl_sec))
        with self._lock:
            self._d[key] = (exp, value)
            self._purge()
        return value

cache = _TTLCache(max_size=1024)

def _mk_key(prefix: str, *args: Any, **kwargs: Any) -> str:
    # מפתח פשוט ויציב
    parts = [prefix] + [repr(a) for a in args] + [f"{k}={repr(v)}" for k, v in sorted(kwargs.items())]
    return "|".join(parts)

def get_or_set(key: str, ttl_sec: float, loader: Callable[[], Any]) -> Any:
    v = cache.get(key)
    if v is not None:
        return v
    val = loader()
    return cache.set(key, val, ttl_sec)

async def aget_or_set(key: str, ttl_sec: float, aloader: Callable[[], Any]) -> Any:
    v = cache.get(key)
    if v is not None:
        return v
    val = await aloader()
    return cache.set(key, val, ttl_sec)

def cached(ttl_sec: float, key_prefix: str):
    """דקורטור פונקציונאלי לפונקציות סינכרוניות בלבד."""
    def wrap(fn: Callable[..., Any]):
        def inner(*a, **kw):
            key = _mk_key(key_prefix, *a, **kw)
            return get_or_set(key, ttl_sec, lambda: fn(*a, **kw))
        return inner
    return wrap
