# app/rate_limit_mw.py
from __future__ import annotations
import os, time, asyncio
from typing import Callable, Awaitable, Optional
from starlette.types import ASGIApp
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

# נסה Redis מה-utilities; אם לא, נעבוד אינ-ממורי
try:
    from utils.redis_client import get_redis  # קיים אצלך ב-repo
except Exception:
    get_redis = None

RATE_LIMIT_ENABLE = os.getenv("RATE_LIMIT_ENABLE", "0") == "1"
RATE_LIMIT_BACKEND = os.getenv("RATE_LIMIT_BACKEND", "redis").lower()
RL_FAIL_OPEN = os.getenv("RL_FAIL_OPEN", "0") == "1"

SCAN_RL_LIMIT = int(os.getenv("SCAN_RL_LIMIT", "0") or 0)
SCAN_RL_WINDOW = int(os.getenv("SCAN_RL_WINDOW", "0") or 0)

# נתיבים שיוגנו ב-RL (אפשר להרחיב)
_PROTECTED_PREFIXES = ("/scan", "/scan/top-volume")

# אינ-ממורי (fallback) — חלון קבוע פשוט
_inmem_counters = {}  # key -> (window_start_ts, count)
_inmem_lock = asyncio.Lock()

def _client_fingerprint(req: Request) -> str:
    ip = req.client.host if req.client else "unknown"
    tok = req.headers.get("X-API-Key") or req.headers.get("Authorization", "")
    return f"{ip}:{tok[:16]}"

async def _check_inmem(key: str, limit: int, window: int) -> tuple[bool,int,int,int]:
    now = int(time.time())
    win = now // window if window > 0 else 0
    async with _inmem_lock:
        ts, cnt = _inmem_counters.get(key, (win, 0))
        if ts != win:
            ts, cnt = win, 0
        allowed = cnt < limit if limit > 0 else True
        if allowed:
            cnt += 1
            _inmem_counters[key] = (ts, cnt)
        remaining = max(0, limit - cnt) if limit > 0 else 0
    reset = (win + 1) * window if window > 0 else now
    return allowed, remaining, reset, cnt

async def _check_redis(r, key: str, limit: int, window: int) -> tuple[bool,int,int,int]:
    # חלון קבוע עם expire
    now = int(time.time())
    p = r.pipeline()
    p.incr(key, 1)
    p.expire(key, window)
    cnt, _ = await p.execute()
    allowed = cnt <= limit if limit > 0 else True
    remaining = max(0, limit - cnt) if limit > 0 else 0
    reset = now + window
    return allowed, remaining, reset, cnt

class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp):
        super().__init__(app)
        self._redis: Optional[any] = None
        if RATE_LIMIT_ENABLE and RATE_LIMIT_BACKEND == "redis" and get_redis:
            try:
                self._redis = get_redis()
            except Exception:
                self._redis = None

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable]):
        if not RATE_LIMIT_ENABLE:
            return await call_next(request)

        path = request.url.path
        # אוכפים רק על /scan* (כולל /scan/top-volume)
        if not path.startswith("/scan"):
            return await call_next(request)

        limit = SCAN_RL_LIMIT
        window = SCAN_RL_WINDOW
        if limit <= 0 or window <= 0:
            # לא הוגדרו ערכים — לא נאכוף
            return await call_next(request)

        fp = _client_fingerprint(request)
        key = f"rl:scan:{fp}"

        try:
            if self._redis:
                allowed, remaining, reset, count = await _check_redis(self._redis, key, limit, window)
            else:
                # fallback אינ-ממורי
                allowed, remaining, reset, count = await _check_inmem(key, limit, window)
        except Exception:
            # אם יש כשל ברדיס:
            if RL_FAIL_OPEN:
                return await call_next(request)
            # fail-closed
            return JSONResponse(
                status_code=429,
                content={"ok": False, "error": "rate_limit_backend_unavailable"},
                headers={"Retry-After": str(window)}
            )

        headers = {
            "X-RateLimit-Limit": str(limit),
            "X-RateLimit-Remaining": str(remaining),
            "X-RateLimit-Reset": str(reset),
        }

        if not allowed:
            retry_after = max(1, reset - int(time.time()))
            return JSONResponse(
                status_code=429,
                content={"ok": False, "error": "rate_limited", "limit": limit, "window": window},
                headers={**headers, "Retry-After": str(retry_after)}
            )

        # ממשיכים לבקשה
        resp = await call_next(request)
        for k, v in headers.items():
            resp.headers[k] = v
        return resp
