from __future__ import annotations
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from utils.auth import extract_token, token_matches, refresh_tokens, get_loaded_tokens

router = APIRouter(tags=["debug"])

@router.get("/_debug/auth", include_in_schema=False)
async def _debug_auth(request: Request):
    a = request.headers.get("authorization") or request.headers.get("Authorization")
    x = request.headers.get("x-api-key") or request.headers.get("X-API-Key")
    t = extract_token(request, a, x)
    return {
        "ok": True,
        "auth_header": a,
        "x_api_key": x,
        "query": dict(request.query_params),
        "extracted_token": t,
        "matches": bool(token_matches(t)),
        "tokens_loaded": get_loaded_tokens(mask=True),
    }

@router.post("/debug/refresh-auth", include_in_schema=False)
async def _debug_refresh_auth():
    info = refresh_tokens()
    return {"ok": True, "detail": "Tokens reloaded from environment", **info, "tokens_masked": get_loaded_tokens(mask=True)}

@router.get("/debug/env", include_in_schema=False)
async def _debug_env():
    import os
    keys = ("API_TOKEN","API_TOKENS","TOKENS_FILE","SECURITY_ALLOW_ALL")
    return {"ok": True, "env": {k: os.getenv(k) for k in keys}}











