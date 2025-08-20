# utils/response_limits.py
from __future__ import annotations
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from typing import Optional

class ResponseSizeLimiter(BaseHTTPMiddleware):
    def __init__(self, app, max_bytes: int = 2_097_152):  # 2MB במקום 1MB
        super().__init__(app)
        self.max_bytes = int(max_bytes)

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        try:
            cl = response.headers.get("content-length")
            size: Optional[int] = int(cl) if cl and cl.isdigit() else None
            if size and size > self.max_bytes:
                return JSONResponse(
                    {"detail": "Response too large",
                     "max_bytes": self.max_bytes,
                     "size": size,
                     "hint": "Use compact=1&fields=..."},
                    status_code=413,
                )
            response.headers["X-Response-Limit"] = str(self.max_bytes)
            if size: response.headers["X-Response-Size"] = str(size)
        except Exception:
            pass
        return response



