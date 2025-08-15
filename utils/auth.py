# utils/auth.py
"""
Auth dependency מרכזי ל-FastAPI:
- דורש טוקן דרך אחד מהבאים: Authorization: Bearer <TOKEN> / X-API-Key / ?token=...
- בודק התאמה ל-API_BEARER_TOKEN מה-ENV (Render/Railway).
- מחזיר 401 עם WWW-Authenticate אם חסר/שגוי.
שימוש:
    from fastapi import Depends, APIRouter
    from utils.auth import require_bearer_token
    router = APIRouter(dependencies=[Depends(require_bearer_token)])
או ברמת endpoint:
    @app.get("/price", dependencies=[Depends(require_bearer_token)])
"""

import os
from typing import Optional
from fastapi import HTTPException, status, Depends, Request, Header, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# HTTPBearer נאפשר אך לא נסתמך עליו בלבד כדי לתמוך גם ב-X-API-Key ו-?token
_http_bearer = HTTPBearer(auto_error=False)

def _get_expected_token() -> str:
    token = (os.getenv("API_BEARER_TOKEN") or "").strip()
    if not token:
        # שגיאה מהירה בפרודקשן אם משתנה סביבה לא מוגדר
        # (שמור: אם אתה רוצה "מצב dev ללא טוקן", החלף כאן ל-return "")
        raise RuntimeError("API_BEARER_TOKEN is not set in environment.")
    if len(token) < 32:
        # חוסם טוקנים חלשים/קצרים
        raise RuntimeError("API_BEARER_TOKEN is too short; use a strong 32-64 char token.")
    return token

def _extract_provided_token(
    request: Request,
    authorization: str = Header(default=""),
    x_api_key: str = Header(default=""),
    token_q: str = Query(default=""),
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_http_bearer),
) -> str:
    """
    מחלץ טוקן ממספר מקורות נפוצים, בסדר עדיפויות:
    1) Authorization: Bearer <token> (מתוך HTTPBearer אם אפשר)
    2) Header: Authorization (ניתוח ידני) / X-API-Key
    3) Query param: ?token=<token>
    """
    # 1) אם HTTPBearer תפס משהו — זה המועדף
    if creds and (creds.scheme or "").lower() == "bearer" and creds.credentials:
        return creds.credentials.strip()

    # 2) Authorization ידני
    if authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()

    # 3) X-API-Key
    if x_api_key:
        return x_api_key.strip()

    # 4) ?token=
    if token_q:
        return token_q.strip()

    # 5) ניסיון אחרון: query בשם "token" אם לא הועבר פרמ' פורמלי
    qtok = request.query_params.get("token")
    if qtok:
        return qtok.strip()

    return ""

def require_bearer_token(
    provided: str = Depends(_extract_provided_token),
) -> bool:
    """
    Dependency לשימוש ברמת Router/Endpoint.
    זורק 401 אם אין טוקן/לא תואם. אחרת מחזיר True.
    """
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
