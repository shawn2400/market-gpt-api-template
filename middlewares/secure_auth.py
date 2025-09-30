# middlewares/secure_auth.py
from __future__ import annotations
import os, logging
from typing import Callable, Iterable
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger("algogpt.auth")

def _env_tokens() -> list[str]:
    toks = []
    for k in ("API_BEARER_TOKEN", "API_TOKEN", "PRIMARY_API_TOKEN", "ALGOGPT_API_TOKEN"):
        v = (os.getenv(k) or "").strip()
        if v:
            toks.append(v)
    return list(dict.fromkeys(toks))  # unique, keep order

PUBLIC_PREFIXES: tuple[str, ...] = (
    "/price", "/public", "/risk", "/static",
)
PUBLIC_PATHS: set[str] = {
    "/", "/docs", "/redoc", "/openapi.json",
    "/health", "/healthz", "/readyz",
    "/status/ping", "/status/all", "/status/executor", "/status/ws",
    "/ops/approve", "/ops/approve-link", "/ops/approve/signed",
    "/ops/reject", "/ops/ui", "/ops/ui/ticket", "/ops/manager/health",
    "/ops/digest/expired",
    "/telegram/ping", "/telegram/webhook", "/telegram/callback",
    "/trade/approve", "/trade/reject",
    "/ui/dashboard",
    "/metrics",  # אם תרצה לחסום — הסר מפה והעבר לאימות
}

def _is_public(path: str) -> bool:
    if path in PUBLIC_PATHS:
        return True
    for p in PUBLIC_PREFIXES:
        if path.startswith(p):
            return True
    return False

class SecureAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, header_key: str = "X-API-Key"):
        super().__init__(app)
        self.header_key = header_key
        self.tokens = _env_tokens()

    async def dispatch(self, request: Request, call_next: Callable):
        path = request.url.path
        # דלג על מסלולים ציבוריים
        if _is_public(path):
            return await call_next(request)

        # אסוף טוקן
        token = request.headers.get(self.header_key) or ""
        if not token:
            auth = request.headers.get("Authorization", "")
            if auth.startswith("Bearer "):
                token = auth.split(" ", 1)[1].strip()
        if not token:
            token = request.query_params.get("apikey") or request.query_params.get("api_key") or ""

        # ולידציה
        if self.tokens and token in self.tokens:
            return await call_next(request)

        # אין טוקן תקף
        return JSONResponse({"detail": "Invalid API key"}, status_code=401)
