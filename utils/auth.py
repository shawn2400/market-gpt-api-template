# utils/auth.py
from __future__ import annotations
import hmac, os
from fastapi import Header, HTTPException, status

_TOKEN = os.getenv("API_BEARER_TOKEN", "").strip()

def _is_valid(token: str) -> bool:
    # תומך בריבוי טוקנים מופרדים בפסיקים אם תרצה לגלגל הדרגתית
    valid_tokens = [t.strip() for t in _TOKEN.split(",") if t.strip()]
    for vt in valid_tokens:
        if hmac.compare_digest(token, vt):
            return True
    return False

async def require_bearer_token(authorization: str | None = Header(None)):
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Authorization header")
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Authorization scheme")
    token = parts[1].strip()
    if not token or not _is_valid(token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    return True











