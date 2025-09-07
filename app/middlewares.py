# app/middlewares.py
from __future__ import annotations
from fastapi import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from utils.security import guard

class InternalAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, paths=("/alerts", "/risk")):
        super().__init__(app)
        self.paths = paths

    async def dispatch(self, request, call_next):
        try:
            if any(request.url.path.startswith(p) for p in self.paths):
                res = await guard(request)
                if res.get("duplicate"):
                    # בקשה כפולה באותו חלון זמן – מחזירים 202 כדי שהלקוח לא ייכשל
                    return JSONResponse(status_code=202, content={"ok": True, "duplicate": True})
            return await call_next(request)
        except HTTPException as e:
            return JSONResponse(status_code=e.status_code, content={"ok": False, "error": e.detail})
        except Exception as e:
            return JSONResponse(status_code=403, content={"ok": False, "error": "forbidden"})

