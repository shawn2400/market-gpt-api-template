# app/middlewares.py
from __future__ import annotations
import os, hmac, hashlib
from typing import Callable, Awaitable
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

# מאחד אימות HMAC אופציונלי לכמה נתיבים, בלי להכביד:
# - /alerts*, /risk*, /telegram/callbacks
# שאר האימותים (API key/Bearer) כבר קיימים ברואטרים עצמם.
# אם WEBHOOK_HMAC_SECRET לא מוגדר – לא בודקים HMAC.

_HMAC_SECRET_RAW = os.getenv("WEBHOOK_HMAC_SECRET", "") or os.getenv("HMAC_SECRET", "")
_HMAC_ENABLED = bool(_HMAC_SECRET_RAW.strip())
_HMAC_SECRET = _HMAC_SECRET_RAW.encode("utf-8")

_SIG_HEADERS = (
    "x-algogpt-signature",
    "X-Algogpt-Signature",
    "X-Hub-Signature-256",
)

_PROTECTED_PREFIXES = ("/alerts", "/risk", "/telegram/callbacks")

def _need_hmac(path: str) -> bool:
    if not _HMAC_ENABLED:
        return False
    return any(path.startswith(p) for p in _PROTECTED_PREFIXES)

def _extract_signature(req: Request) -> str | None:
    for h in _SIG_HEADERS:
        if h in req.headers:
            val = req.headers[h]
            return val.split("=", 1)[1] if "=" in val else val
    return None

def _verify(sig_hex: str | None, body: bytes) -> bool:
    if not sig_hex:
        return False
    expected = hmac.new(_HMAC_SECRET, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig_hex.strip())

class InternalAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable]):
        path = request.url.path

        # OPTIONS / סטטיים – דילוג
        if request.method.upper() == "OPTIONS" or path.startswith("/static/"):
            return await call_next(request)

        # HMAC רק אם מופעל ב-ENV ורק לנתיבים הייעודיים
        if _need_hmac(path):
            # קריאת גוף (ישמר ב־scope כך שהנתיב יקבל אותו)
            body = await request.body()
            sig = _extract_signature(request)
            if not _verify(sig, body):
                return JSONResponse(status_code=401, content={"ok": False, "error": "Invalid HMAC signature"})

        return await call_next(request)


