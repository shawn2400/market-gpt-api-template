# utils/rate_limit.py
from __future__ import annotations
import os, time, logging
from typing import Optional, Tuple, Callable
try:
    from utils.redis_client import get_redis
except Exception:
    get_redis = lambda: None  # type: ignore

try:
    # אופציונלי – אם FastAPI נטען, נשתמש בו לזריקת 429 בתוך dependency
    from fastapi import HTTPException, Depends
except Exception:  # pragma: no cover
    HTTPException = Exception  # type: ignore
    def Depends(x):  # type: ignore
        return x

log = logging.getLogger("algogpt.rl")

DEFAULT_LIMIT = int(os.getenv("RL_DEFAULT_LIMIT", "60"))
DEFAULT_WINDOW = int(os.getenv("RL_DEFAULT_WINDOW", "60"))

# זיכרון (fallback)
_mem_calls = {}  # (bucket_key) -> (first_ts, count)

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
            # Sliding window בקירוב: מפתח לכל חלון, INCR + TTL
            pipe = r.pipeline()
            pipe.incr(key, 1)
            pipe.expire(key, window_sec)
            val, _ = pipe.execute()
            remaining = max(0, limit - int(val))
            return (int(val) <= limit, remaining)
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

# דיפנדנסי ידידותי ל-FastAPI – אופציונלי, אם לא משתמשים בו אין חובה לייבא
def require_rate_limit(
    scope: str = "global",
    ident_from: str = "ip",
    limit: int = DEFAULT_LIMIT,
    window_sec: int = DEFAULT_WINDOW
) -> Callable[[], None]:
    """
    שימוש: router.get(..., dependencies=[Depends(require_rate_limit("calib", "ip", 30, 60))])
    ident_from: "ip" | "token"
    """
    async def _dep(request=None):
        ident: str = "anon"
        try:
            if ident_from == "token":
                ident = (request.headers.get("authorization") or request.headers.get("Authorization") or "").strip() or "anon"
            else:
                # IP
                ident = (request.client.host if request and request.client else "anon")
        except Exception:
            pass
        ok, remaining = await allow(scope, ident, limit=limit, window_sec=window_sec)
        if not ok:
            # 429 – Too Many Requests
            raise HTTPException(status_code=429, detail={"error": "rate_limited", "scope": scope, "remaining": remaining})
        return None
    return _dep

__all__ = ["allow", "require_rate_limit", "DEFAULT_LIMIT", "DEFAULT_WINDOW"]








