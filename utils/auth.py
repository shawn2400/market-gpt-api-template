# utils/auth.py
from __future__ import annotations
import os
from fastapi import Header, HTTPException, status

def _expected_token() -> str:
    return (
        os.getenv("ALGOGPT_TOKEN")
        or os.getenv("ALGOGPT_API_TOKEN")
        or os.getenv("API_BEARER")
        or ""
    ).strip()

_ALLOW_ALL = (os.getenv("SECURITY_ALLOW_ALL", "").lower() in ("1", "true", "yes"))

async def require_bearer_token(authorization: str | None = Header(None)) -> None:
    """
    Secure-by-default: אם אין טוקן בהגדרות — 401.
    כדי לפתוח פומבית (פיתוח), הגדר SECURITY_ALLOW_ALL=1.
    """
    if _ALLOW_ALL:
        return
    expected = _expected_token()
    if not expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    provided = authorization.split(None, 1)[1].strip()
    if provided != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")














