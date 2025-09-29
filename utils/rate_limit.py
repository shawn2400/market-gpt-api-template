# utils/rate_limit.py
from __future__ import annotations
import os, time, logging
from typing import Optional, Tuple, Callable

# Redis (אופציונלי)
try:
    from utils.redis_client import get_redis
except Exception:  # pragma: no cover
    get_redis = lambda: None  # type: ignore

# FastAPI hooks (אופציונלי)
try:
    from fastapi import HTTPException, Depends  # noqa: F401
except Exception:  # pragma: no cover
    HTTPException = Exception  # type: ignore
    def Depends(x):  # type: ignore
        return x

log = logging.getLogger("algogpt.rl")

# פרמטרים מ-ENV (דיפולטים שמרניים)
DEFAULT_LIMIT = int(os.getenv("RL_DEFAULT_LIMIT", "60"))
DEFAULT_WINDOW = int(os.getenv("RL_DEFAULT_WINDOW", "60"))
KEY_PREFIX = os.getenv("RL_KEY_PREFIX", "rl")

# זיכרון (fallback) – גלובלי ופשוט
_mem_calls: dict[str, tuple[int, int]] = {}  # key -> (first_ts, count)

def _bucket_key(scope: str, ident: str) -> str:
    scope = (scope or "global").strip().lower()
    ident = ident.strip().lower() if ident else "anon"
    return f"{KEY_PREFIX}:{scope}:{ident}"

def _extract_client_id(request, ident_from: str) -> str:
    """
    ident_from: "ip" | "token"
    - ip: יעדיף X-Forwarded-For / X-Real-IP ואז request.client.host
    - token: Authorization/X-API-Key
    """
    if request is None:
        return "anon"

    if ident_from == "token":
        auth = (request.headers.get("authorization")
                or request.headers.get("Authorization")
                or request.headers.get("x-api-key")
                or request.headers.get("X-API-Key")
                or "").strip()
        return auth or "anon"

    # IP (מאחורי פרוקסי)
    xff = (request.headers.get("x-forwarded-for")
           or request.headers.get("X-Forwarded-For") or "").strip()
    if xff:
        # לוקחים את הראשון
        return xff.split(",")[0].strip().lower() or "anon"
    xrip = (request.headers.get("x-real-ip")
            or request.headers.get("X-Real-IP") or "").strip()
    if xrip:
        return xrip.lower()
    try:
        return (request.client.host or "anon").lower()
    except Exception:
        return "anon"

async def allow(
    scope: str,
    ident: str,
    *,
    limit: int = DEFAULT_LIMIT,
    window_sec: int = DEFAULT_WINDOW
) -> Tuple[bool, int]:
    """
    החזר (allowed, remaining) עבור תיחום קצב פשוט (קופסה אחת לכל scope+ident).
    משתמש ב-Redis אם זמין; אחרת ב-fallback בזיכרון.
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
            # fixed-window פשוט: INCR + TTL (מרעננים את ה-TTL בכל קריאה; די טוב לרוב המקרים)
            pipe = r.pipeline()
            pipe.incr(key, 1)
            pipe.expire(key, window_sec)
            val, _ = pipe.execute()
            current = int(val) if val is not None else 1
            remaining = max(0, limit - current)
            return (current <= limit, remaining)
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

# דיפנדנסי ידידותי ל-FastAPI – אופציונלי
def require_rate_limit(
    scope: str = "global",
    ident_from: str = "ip",
    limit: int = DEFAULT_LIMIT,
    window_sec: int = DEFAULT_WINDOW
) -> Callable[[], None]:
    """
    שימוש:
      router.get(
        "/endpoint",
        dependencies=[Depends(require_rate_limit("calib", "ip", 30, 60))]
      )
    ident_from: "ip" | "token"
    """
    async def _dep(request=None):
        ident = _extract_client_id(request, ident_from)
        ok, remaining = await allow(scope, ident, limit=limit, window_sec=window_sec)
        if not ok:
            # 429 – Too Many Requests
            raise HTTPException(
                status_code=429,
                detail={"error": "rate_limited", "scope": scope, "remaining": remaining},
            )
        return None
    return _dep

__all__ = ["allow", "require_rate_limit", "DEFAULT_LIMIT", "DEFAULT_WINDOW"]









