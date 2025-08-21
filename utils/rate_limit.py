# utils/rate_limit.py
from __future__ import annotations
import time, re
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from collections import defaultdict
from typing import Dict, Tuple, Pattern

class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, limit: int = 60, window: int = 60, endpoint_limits: Dict[str, Tuple[int, int]] | None = None):
        super().__init__(app)
        self.limit = limit
        self.window = window
        self.endpoint_limits: list[tuple[Pattern, Tuple[int, int]]] = []

        # אם העברת endpoint_limits – מקמפל ל־regex
        if endpoint_limits:
            for pattern, (lim, win) in endpoint_limits.items():
                self.endpoint_limits.append((re.compile(pattern), (lim, win)))

        # אחסון שימושים
        self.hits: Dict[Tuple[str, str], list[float]] = defaultdict(list)

    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host if request.client else "unknown"
        path = request.url.path

        # ברירת מחדל
        limit, window = self.limit, self.window

        # בדיקה מול regex-ים מותאמים
        for regex, (lim, win) in self.endpoint_limits:
            if regex.match(path):
                limit, window = lim, win
                break

        key = (client_ip, path)
        now = time.time()

        # ניקוי hits ישנים
        self.hits[key] = [ts for ts in self.hits[key] if ts > now - window]

        if len(self.hits[key]) >= limit:
            return JSONResponse(
                {"detail": f"Rate limit exceeded ({limit}/{window}s)"},
                status_code=429
            )

        self.hits[key].append(now)
        return await call_next(request)


