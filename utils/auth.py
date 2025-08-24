# utils/auth.py
from __future__ import annotations
import os
from fastapi import Header, HTTPException, Request, status

# --- Load tokens from ENV ---
TOKENS = [
    t.strip()
    for t in (os.getenv("API_BEARER_TOKEN", "") + "," + os.getenv("ALGOGPT_TOKENS", "")).split(",")
    if t.strip()
]
ALLOW_ALL = os.getenv("SECURITY_ALLOW_ALL", "0").strip().lower() in ("1", "true", "yes")

async def require_api_key(
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
):
    """
    Validate API key from:
      - Authorization: Bearer <token>
      - X-API-Key: <token>
      - query param ?token=<token>
    """
    if ALLOW_ALL:
        return True

    supplied: str | None = None

    # Header: Authorization: Bearer xxx
    if authorization and authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()

    # Header: X-API-Key: xxx
    if not supplied and x_api_key:
        supplied = x_api_key.strip()

    # Query param
    if not supplied:
        supplied = request.query_params.get("token")

    # Match against known tokens
    if supplied and supplied in TOKENS:
        return True

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid API key"
    )

# Backward compatibility
async def require_bearer_token(
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
):
    return await require_api_key(request, authorization, x_api_key)

require_auth = require_api_key






































































































































































