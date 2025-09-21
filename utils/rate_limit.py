# utils/rate_limit.py
from __future__ import annotations
import os, time, logging
from typing import Optional, Tuple
try:
    from utils.redis_client import get_redis
except Exception:
    get_redis = lambda: None  # type: ignore

log = logging.getLogger("algogpt.rl")

DEFAULT_LIMIT = int(os.getenv("RL_DEFAULT_LIMIT", "60"))
DEFAULT_WINDOW = int(os.getenv("RL_DEFAULT_WINDOW", "60"))

# זיכרון (fallback)
_mem_calls = {}  # (bucket_key) -> [first_ts, count]

def _bucket_key(scope: str, ident: str) -> str:
    return f"rl:{scope}:{ident}"

async def allow(
    scope: str,
    ident: str,
    *,
    limit: int = DEFAULT_LIMIT,
    window_sec: int = DEFAULT_WINDOW
) -> Tuple[bool, int]:
    """
    החזר (allowed, remaining) עבור תיחום קצב פשוט.
    משתמש ב־Redis אם קיים, אחרת בזיכרון.
    """
    key = _bucket_key(scope, ident)
    r = None
    try:
        r = get_redis()
    except Exception:
        r = None

    now = int(time.time())
    if r:
        try:
            # Sliding window בקירוב: מפתח לכל דקה (או חלון), INCR + TTL
            pipe = r.pipeline()
            pipe.incr(key, 1)
            pipe.expire(key, window_sec)
            val, _ = pipe.execute()
            remaining = max(0, limit - int(val))
            return (val <= limit, remaining)
        except Exception as e:
            log.warning("rate_limit.redis_error: %s", e)

    # Memory fallback
    first, cnt = _mem_calls.get(key, (now, 0))
    if now - first >= window_sec:
        first, cnt = now, 0
    cnt += 1
    _mem_calls[key] = (first, cnt)
    remaining = max(0, limit - cnt)
    return (cnt <= limit, remaining)

__all__ = ["allow", "DEFAULT_LIMIT", "DEFAULT_WINDOW"]







