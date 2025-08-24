# utils/auth.py
from __future__ import annotations
import os
from fastapi import Header, HTTPException, Request

TOKENS = [t.strip() for t in (os.getenv("API_BEARER_TOKEN", "") + "," + os.getenv("ALGOGPT_TOKENS", "")).split(",") if t.strip()]
ALLOW_ALL = os.getenv("SECURITY_ALLOW_ALL", "0").strip().lower() in ("1", "true", "yes")

async def require_api_key(
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
):
    if ALLOW_ALL:
        return True

    supplied: str | None = None

    # 1) Authorization: Bearer <token>
    if authorization and authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()

    # 2) X-API-Key
    if not supplied and x_api_key:
        supplied = x_api_key.strip()

    # 3) ?token=<...>
    if not supplied:
        supplied = request.query_params.get("token")

    if supplied and supplied in TOKENS:
        return True

    raise HTTPException(status_code=401, detail="Invalid API key")










































