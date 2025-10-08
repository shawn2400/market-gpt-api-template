# routes/debug.py
from __future__ import annotations

import os
from typing import Any, Dict

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

# מסתמכים על utils.auth הקיים בפרויקט
from utils.auth import (
    extract_token,
    token_matches,
    refresh_tokens,
    get_loaded_tokens,
)

router = APIRouter(tags=["debug"])


@router.get("/_debug/auth", include_in_schema=False)
async def _debug_auth(request: Request) -> Dict[str, Any]:
    """
    בדיקת אימות: מציג כותרות רלוונטיות, הטוקן שהופק, האם יש התאמה לטוקנים הטעונים,
    ורשימת טוקנים במסכה (mask=True).
    """
    auth_header = request.headers.get("authorization") or request.headers.get("Authorization")
    x_api_key = request.headers.get("x-api-key") or request.headers.get("X-API-Key")
    token = extract_token(request, auth_header, x_api_key)

    return {
        "ok": True,
        "auth_header": auth_header,
        "x_api_key": x_api_key,
        "query": dict(request.query_params),
        "extracted_token": token,
        "matches": bool(token_matches(token)),
        "tokens_loaded": get_loaded_tokens(mask=True),
    }


@router.post("/debug/refresh-auth", include_in_schema=False)
async def _debug_refresh_auth() -> Dict[str, Any]:
    """
    רענון טוקנים מתוך הסביבה/קובץ (הלוגיקה ב־utils.auth) והחזרת סטטוס + תצוגה במסכה.
    """
    info = refresh_tokens()
    return {
        "ok": True,
        "detail": "Tokens reloaded from environment",
        **info,
        "tokens_masked": get_loaded_tokens(mask=True),
    }


@router.get("/debug/env", include_in_schema=False)
async def _debug_env() -> Dict[str, Any]:
    """
    החזרת חלק ממשתני הסביבה הרלוונטיים לדיבאג אימות.
    (אל תוסיף לכאן סודות — ההחזרה היא גולמית)
    """
    keys = (
        "API_TOKEN",
        "API_TOKENS",
        "TOKENS_FILE",
        "SECURITY_ALLOW_ALL",
        "ENABLE_READONLY_HTTP",
        "OPENAPI_INCLUDE_TAGS",
        "OPENAPI_HIDE_PATTERNS",
    )
    return {"ok": True, "env": {k: os.getenv(k) for k in keys}}


@router.get("/_debug/ping", include_in_schema=False)
async def _debug_ping() -> JSONResponse:
    """
    פינג דיבאג בסיסי לבדיקת זמינות ראוט הדיבאג.
    """
    return JSONResponse({"ok": True, "pong": True})










