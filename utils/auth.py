# utils/auth.py
from __future__ import annotations
from fastapi import Header, HTTPException

def require_bearer_token(authorization: str | None = Header(default=None)):
    """
    בדיקת Authorization: Bearer <token>. כל טוקן לא-ריק מתקבל (אפשר להחליף לאימות אמיתי).
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail={"error": "unauthorized", "code": "NO_BEARER"})
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail={"error": "unauthorized", "code": "EMPTY_TOKEN"})
    return None






