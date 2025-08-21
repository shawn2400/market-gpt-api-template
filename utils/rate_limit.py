# utils/rate_limit.py
from __future__ import annotations
import time
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from typing import Dict, Tuple

class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware שמטיל rate limit גלובלי + פר־endpoint לפי IP.
    limit = מספר בקשות, window = שניות
    """

    def __init__(self, app, limit: int = 60, window: int = 60,
                 endpoint_limits: Dict[str, Tuple[int,int]] | None = None):
        super().__init__(app)
        self.limit = limit
        self.window = window
        # endpoint_limits = {"/backtest": (10,60), "/health": (300,60)}
        self.endpoint_limits = endpoint_limits or {}
        # store: {(ip, path): [timestamps]}
        self.requests: Dict[Tuple[str,str], list[float]] = {}

    async def dispatch(self, request, call_next):
        ip = request.client.host if request.client else "unknown"
        path = request.url.path

        # ✅ בדיקת limit פר־endpoint אם מוגדר
        limit, window = self.endpoint_limits.get(path, (self.limit, self.window))

        now = time.monotonic()
        key = (ip, path)
        hits = self.requests.get(key, [])

        # מסננים hits ישנים מחוץ ל־window
        hits = [t for t in hits if now - t < window]

        if len(hits) >= limit:
            return JSONResponse(
                {"detail": f"Rate limit exceeded ({limit}/{window}s)", "path": path},
                status_code=429
            )

        # מוסיפים את ה־hit הנוכחי
        hits.append(now)
        self.requests[key] = hits

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(max(0, limit - len(hits)))
        response.headers["X-RateLimit-Window"] = str(window)
        return response


