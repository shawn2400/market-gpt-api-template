# utils/cache.py
from __future__ import annotations
import time, asyncio
from typing import Any, Callable, Dict, Tuple

# key -> (expire_ts, value)
_store: Dict[str, Tuple[float, Any]] = {}
_lock = asyncio.Lock()

async def aget_or_set(key: str, ttl_seconds: float, loader: Callable[[], Any]) -> Any:
    """Cache אסינכרוני: אם key קיים ולא פג — החזר; אחרת טען, שמור, והחזר."""
    now = time.monotonic()
    async with _lock:
        hit = _store.get(key)
        if hit and hit[0] > now:
            return hit[1]
    # load without holding the lock
    val = await loader() if asyncio.iscoroutinefunction(loader) else loader()
    expire = now + float(ttl_seconds or 0)
    async with _lock:
        _store[key] = (expire, val)
    return val

def purge_expired() -> int:
    now = time.monotonic()
    dead = [k for k,(t,_) in _store.items() if t <= now]
    for k in dead:
        _store.pop(k, None)
    return len(dead)


