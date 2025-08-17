# utils/auth.py
from __future__ import annotations
import os, re
from fastapi import HTTPException, Request, status

# אפשר לשנות את שם משתנה הסביבה שמחזיק את הטוקן ע"י API_BEARER_ENV_KEY
_ENV_TOKEN_KEY = os.getenv("API_BEARER_ENV_KEY", "API_BEARER_TOKEN")

def _clean(s: str | None) -> str:
    if not s:
        return ""
    s = re.sub(r"[\x00-\x1F\x7F]", "", s)
    return s.strip()

def _get_expected_token() -> str:
    """שליפת הטוקן מה־ENV לפי השם שב-_ENV_TOKEN_KEY."""
    return _clean(os.getenv(_ENV_TOKEN_KEY, ""))

async def require_bearer_token(request: Request) -> str:
    """
    FastAPI dependency:
    - קורא Authorization: Bearer <token>
    - משווה מול הטוקן ב־ENV (API_BEARER_TOKEN או שם אחר אם הוגדר API_BEARER_ENV_KEY)
    - מחזיר את הטוקן אם תקין, אחרת 401
    """
    auth_header = request.headers.get("authorization") or request.headers.get("Authorization")
    if not auth_header:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    parts = auth_header.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header format",
            headers={"WWW-Authenticate": "Bearer"},
        )

    presented = _clean(parts[1])
    expected = _get_expected_token()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Server token not configured",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if presented != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return presented

__all__ = ["require_bearer_token"]










