# /app/routes/debug.py
from __future__ import annotations
from fastapi import APIRouter, Request
import os, platform, time
from typing import Any, Dict, Optional

from utils.auth import (
    extract_token, token_matches,
    get_loaded_tokens, refresh_tokens_from_env,
)

router = APIRouter(prefix="", tags=["Debug"])  # בלי Depends — ציבורי

@router.get("/_debug/auth", include_in_schema=False)
async def debug_auth(request: Request):
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

@router.get("/debug/env")
async def debug_env():
    return {
        "API_TOKENS": os.getenv("API_TOKENS"),
        "ALGOGPT_TOKENS": os.getenv("ALGOGPT_TOKENS"),
        "API_BEARER_TOKEN": bool(os.getenv("API_BEARER_TOKEN")),
        "API_TOKENS_FILE": os.getenv("API_TOKENS_FILE"),
        "SECURITY_PUBLIC_PATHS": os.getenv("SECURITY_PUBLIC_PATHS"),
        "AUTH_TOKENS_TTL": os.getenv("AUTH_TOKENS_TTL"),
        "ENV": os.getenv("ENV", "production"),
        "platform": platform.platform(),
        "time_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
    }

@router.post("/debug/refresh-auth")
async def debug_refresh_auth():
    toks = refresh_tokens_from_env()
    return {
        "ok": True,
        "detail": "Tokens reloaded from environment",
        "count": len(toks),
        "tokens_masked": get_loaded_tokens(mask=True),
    }











