# utils/auth.py
from __future__ import annotations
import os
from typing import Optional, Dict, Any
from fastapi import Header, HTTPException, status

# שימוש ב-PyJWT אם זמין, אבל לא חובה
try:
    import jwt as pyjwt  # PyJWT
except Exception:
    pyjwt = None  # type: ignore


def _extract_bearer(authorization: Optional[str]) -> str:
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Authorization header")
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Authorization scheme")
    token = parts[1].strip()
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Empty bearer token")
    return token


def _validate_static_token(token: str) -> Optional[Dict[str, Any]]:
    static_token = os.getenv("API_BEARER_TOKEN", "").strip()
    if static_token and token == static_token:
        return {"sub": "static", "scopes": ["api:full"]}
    return None


def _validate_jwt(token: str) -> Optional[Dict[str, Any]]:
    secret = os.getenv("API_JWT_SECRET", "").strip()
    if not secret or pyjwt is None:
        return None
    try:
        payload = pyjwt.decode(token, secret, algorithms=["HS256"], options={"verify_aud": False})
        return {"sub": payload.get("sub", "jwt"), "claims": payload}
    except Exception:
        return None


def require_bearer_token(
    authorization: Optional[str] = Header(None, convert_underscores=False),
    x_api_key: Optional[str] = Header(None)
) -> Dict[str, Any]:
    """
    סדר עדיפויות:
    1) X-API-Key == API_BEARER_TOKEN  -> קבל
    2) Authorization: Bearer <token>:
       2.1) אם שווה ל-API_BEARER_TOKEN -> קבל
       2.2) אחרת נסה JWT עם API_JWT_SECRET (אם זמין)
    """
    static_token = os.getenv("API_BEARER_TOKEN", "").strip()
    if x_api_key and static_token and x_api_key.strip() == static_token:
        return {"ok": True, "auth": "x-api-key", "sub": "static"}

    token = _extract_bearer(authorization)

    if static_token:
        ok = _validate_static_token(token)
        if ok:
            return {"ok": True, "auth": "bearer-static", **ok}

    ok = _validate_jwt(token)
    if ok:
        return {"ok": True, "auth": "bearer-jwt", **ok}

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")













