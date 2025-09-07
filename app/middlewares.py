# app/middlewares.py
from __future__ import annotations
from fastapi import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from utils.security import verify_bearer, verify_optional_hmac

class InternalAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, paths=("/alerts", "/risk")):
        super().__init__(app)
        self.paths = paths

    async def dispatch(self, request, call_next):
        try:
            if any(request.url.path.startswith(p) for p in self.paths):
                # Bearer חובה; HMAC אופציונלי אם הכותרת קיימת
                verify_bearer(request)
                body = await request.body()
                verify_optional_hmac(request, body)
            return await call_next(request)
        except HTTPException as e:
            return JSONResponse(status_code=e.status_code, content={"ok": False, "error": e.detail})
        except Exception:
            return JSONResponse(status_code=403, content={"ok": False, "error": "forbidden"})
