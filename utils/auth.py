# utils/auth.py
from __future__ import annotations
import os
from fastapi import Header, HTTPException, status

_TOKEN = os.getenv("API_BEARER_TOKEN", "").strip()

def require_bearer_token(authorization: str | None = Header(default=None)) -> None:
    """
    Validates Authorization: Bearer <token> against API_BEARER_TOKEN env.
    Raises 401 on missing/invalid; 500 if token not configured on server.
    """
    if not _TOKEN:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Auth not configured")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    token = authorization.split(" ", 1)[1].strip()
    if token != _TOKEN:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    return None














