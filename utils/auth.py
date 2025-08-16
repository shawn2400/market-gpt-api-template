# utils/auth.py
"""
Auth dependency מרכזי ל-FastAPI:
- דורש טוקן דרך אחד מהבאים:
  Authorization: Bearer <TOKEN> / X-API-Key / ?token=...
- בודק התאמה ל-API_BEARER_TOKEN מה-ENV.
- מחזיר 401 עם WWW-Authenticate אם חסר/שגוי.

שימוש:
    from fastapi import Depends
    from utils.auth import require_bearer_token

    @app.get("/secure", dependencies=[Depends(require_bearer_token)])
    async def secure_ep(): ...

או ברמת רואטר:
    router = APIRouter(dependencies=[Depends(require_bearer_token)])
"""

import os
from typing import Optional
from fastapi import HTTPException, status, Depends, Request, Header, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

_http_bearer = HTTPBearer(auto_error=False)

def _get_expected_token() -> str:
    token = (os.getenv("API_BEARER_TOKEN") or "").strip()
    if not token:
        raise RuntimeError("API_BEARER_TOKEN is not set in environment.")
    if len(token) < 32:
        raise RuntimeError("API_BEARER_TOKEN is too short; use a strong 32-64 char token.")
    return token

def _extract_provided_token(
    request: Request,
    authorization: str = Header(default=""),
    x_api_key: str = Header(default="", alias="X-API-Key"),
    token_q: str = Query(default="", alias="token"),
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_http_bearer),
) -> str:
    # Bearer ע"י ה-Security helper
    if creds and (creds.scheme or "").lower() == "bearer" and creds.credentials:
        return creds.credentials.strip()

    # Bearer ידני מה-Authorization
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()

    # X-API-Key
    if x_api_key:
        return x_api_key.strip()

    # ?token=... (גם alias וגם חיפוש חופשי ב-query string)
    if token_q:
        return token_q.strip()
    qtok = request.query_params.get("token")
    if qtok:
        return qtok.strip()

    return ""

def require_bearer_token(provided: str = Depends(_extract_provided_token)) -> bool:
    expected = _get_expected_token()
    if not provided:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if provided != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return True



