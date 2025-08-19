# utils/response_limits.py
from __future__ import annotations
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from typing import Optional

class ResponseSizeLimiter(BaseHTTPMiddleware):
    def __init__(self, app, max_bytes: int = 1_048_576):
        super().__init__(app)
        self.max_bytes = int(max_bytes)

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        try:
            cl = response.headers.get("content-length")
            size: Optional[int] = int(cl) if cl and cl.isdigit() else None

            # אם אין Content-Length, ננסה לקרוא מגודל גוף שנבנה מראש (ל-JSONResponse)
            if size is None:
                body = getattr(response, "body", None)
                if isinstance(body, (bytes, bytearray)):
                    size = len(body)

            if size is not None and size > self.max_bytes:
                return JSONResponse(
                    {
                        "detail": "Response too large",
                        "max_bytes": self.max_bytes,
                        "size": size,
                        "hint": "Use compact=1 and/or fields=... or reduce limit"
                    },
                    status_code=413,
                )

            response.headers["X-Response-Limit"] = str(self.max_bytes)
            if size is not None:
                response.headers["X-Response-Size"] = str(size)
        except Exception:
            # לא להפיל בקשה אם חישוב גודל נכשל
            pass
        return response
