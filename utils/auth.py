# utils/auth.py
from __future__ import annotations

import os
import re
from fastapi import HTTPException, Request, status

__all__ = ["require_bearer_token"]

# שם משתנה הסביבה שמחזיק את הטוקן
_ENV_TOKEN_KEY = os.getenv("API_BEARER_ENV_KEY", "API_BEARER_TOKEN")

def _clean(s: str | None) -> str:
    """ניקוי רווחים ותווי בקר (כולל CR/LF/טאבים/רווחים נסתרים)."""
    if not s:
        return ""
    # הסר תווי בקרה ורווחים נסתרים
    s = re.sub(r"[\x00-\x1F\x7F]", "", s)
    return s.strip()

def _get_expected_token() -> str:
    """שליפת הטוקן מה-ENV + ניקוי."""
    raw = os.getenv(_ENV_TOKEN_KEY, "")
    return _clean(raw)

async def require_bearer_token(request: Request) -> str:
    """
    Dependency לאימות Bearer:
    - קורא Authorization: Bearer <token>
    - משווה לטוקן מה-ENV (API_BEARER_TOKEN או לפי API_BEARER_ENV_KEY)
    - מחזיר את הטוקן אם תקין, אחרת 401
    """
    auth_header = request.headers.get("authorization") or request.headers.get("Authorization")
    if not auth_header:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # פורמט צפוי: "Bearer <token>"
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
        # הגנה: אם אין טוקן מוגדר בסביבה – נחסום (עדיף מאשר להשאיר פתוח)
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

    # אפשר להחזיר claims/אובייקט משתמש בעתיד; כרגע מחזירים את הטוקן התקין
    return presented






