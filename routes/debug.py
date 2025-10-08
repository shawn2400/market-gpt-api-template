# FILE: routes/debug.py
from __future__ import annotations

import os
import logging
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

# מודולי auth — אם חסר משהו, נתמודד בעדינות
try:
    from utils.auth import extract_token, token_matches, refresh_tokens, get_loaded_tokens
except Exception:  # noqa: BLE001
    # נפילות סביבה לא יפילו את הראוטים
    def extract_token(request: Request, auth_header: str | None, x_api_key: str | None) -> str | None:
        if x_api_key:
            return x_api_key.strip()
        if auth_header and auth_header.lower().startswith("bearer "):
            return auth_header.split(None, 1)[1].strip()
        return None

    def token_matches(tok: str | None) -> bool:
        env_token = os.getenv("API_TOKEN") or os.getenv("API_BEARER_TOKEN")
        return bool(tok and env_token and tok == env_token)

    def refresh_tokens() -> dict:
        # אם אין מימוש — נחזיר מידע בסיסי
        return {"reloaded": False, "reason": "refresh_tokens not available"}

    def get_loaded_tokens(mask: bool = True):
        t = os.getenv("API_TOKEN") or os.getenv("API_BEARER_TOKEN") or ""
        if mask and t:
            t = f"{t[:2]}…{t[-2:]}"
        return {"count": int(bool(t)), "tokens": [t] if t else []}

log = logging.getLogger("algogpt.debug")
router = APIRouter(prefix="/debug", tags=["debug"])

@router.get("/auth", include_in_schema=False)
async def debug_auth(request: Request):
    a = request.headers.get("authorization") or request.headers.get("Authorization")
    x = request.headers.get("x-api-key") or request.headers.get("X-API-Key")
    t = extract_token(request, a, x)
    return JSONResponse({
        "ok": True,
        "auth_header": a,
        "x_api_key": x,
        "query": dict(request.query_params),
        "extracted_token": t,
        "matches": bool(token_matches(t)),
        "tokens_loaded": get_loaded_tokens(mask=True),
    })

@router.post("/refresh-auth", include_in_schema=False)
async def debug_refresh_auth():
    info = refresh_tokens()
    return JSONResponse({"ok": True, "detail": "Tokens (re)loaded", **info, "tokens_masked": get_loaded_tokens(mask=True)})

@router.get("/env", include_in_schema=False)
async def debug_env():
    keys = (
        "API_TOKEN","API_BEARER_TOKEN","PRIMARY_API_TOKEN","API_TOKENS",
        "TOKENS_FILE","SECURITY_ALLOW_ALL","ENABLE_READONLY_HTTP",
    )
    return JSONResponse({"ok": True, "env": {k: os.getenv(k) for k in keys}})










