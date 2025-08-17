# utils/auth.py
import os
from fastapi import Header, HTTPException, status

async def require_bearer_token(authorization: str | None = Header(default=None)):
    expected = os.getenv("API_BEARER_TOKEN")
    if not expected:
        # מאובטח יותר לעצור כדי לא לאפשר גישה פתוחה בטעות
        raise HTTPException(status_code=500, detail="API_BEARER_TOKEN לא מוגדר בשרת")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    if token != expected:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid token")
    return None  # לא מחזירים Request כדי לא לעורר Assertion ב-FastAPI



