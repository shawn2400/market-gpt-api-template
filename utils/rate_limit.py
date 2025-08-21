# utils/rate_limit.py
from __future__ import annotations
import time
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from utils.redis_client import redis_client

class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Rate-limit לפי IP (ברירת מחדל: 60 בקשות ב־60 שניות).
    אם יש Redis → משתמש בו (Distributed). אחרת In-Memory Fallback.
    """

    def __init__(self, app, limit: int = 60, window: int = 60):
        super().__init__(app)
        self.limit = limit
        self.window = window
        self._memory_hits: dict[str, tuple[int, int]] = {}  # ip -> (reset_ts, count)

    async def dispatch(self, request: Request, call_next):
        ip = request.client.host
        now = int(time.time())

        # --- Redis-based (shared across workers)
        if redis_client:
            key = f"ratelimit:{ip}"
            pipe = redis_client.pipeline()
            pipe.incr(key, 1)
            pipe.expire(key, self.window)
            count, _ = pipe.execute()
            if int(count) > self.limit:
                return JSONResponse(
                    {"detail": "Rate limit exceeded", "ip": ip, "limit": self.limit, "window": self.window},
                    status_code=429
                )
            return await call_next(request)

        # --- In-memory fallback (single worker)
        reset, count = self._memory_hits.get(ip, (now + self.window, 0))
        if now > reset:
            reset, count = now + self.window, 0
        count += 1
        self._memory_hits[ip] = (reset, count)

        if count > self.limit:
            return JSONResponse(
                {"detail": "Rate limit exceeded", "ip": ip, "limit": self.limit, "window": self.window},
                status_code=429
            )

        return await call_next(request)
