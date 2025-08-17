# utils/auth.py
from __future__ import annotations

import os
import re
from fastapi import HTTPException, Request, status

# שם משתנה הסביבה שמחזיק את *שם* המפתח של הטוקן (ברירת מחדל: API_BEARER_TOKEN)
_ENV_TOKEN_KEY = os.getenv("API_BEARER_ENV_KEY", "API_BEARER_TOKEN")


def _clean(s: str | None) -> str:
    """
    ניקוי רווחים ותווי בקר (כולל CR/LF/טאבים/רווחים נסתרים).
    """
    if not s:
        return ""
    s = re.sub(r"[\x00-\x1F\x7F]", "", s)  # מסיר תווי בקרה
    return s.strip()


def _get_expected_token() -> str:
    """
    שליפת הטוקן מה-ENV לפי _ENV_TOKEN_KEY (ברירת מחדל: API_BEARER_TOKEN) + ניקוי.
    """
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
    try:
        scheme, presented_raw = auth_header.split(" ", 1)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header format",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header scheme",
            headers={"WWW-Authenticate": "Bearer"},
        )

    presented = _clean(presented_raw)
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


__all__ = ["require_bearer_token"]






