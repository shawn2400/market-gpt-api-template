# utils/auth.py
import os
from fastapi import Header, HTTPException, status

# ✅ Token קבוע מה־ENV
API_BEARER_TOKEN = os.getenv("API_BEARER_TOKEN", "").strip()

async def require_bearer_token(
    authorization: str = Header(..., description="Bearer <token>")
):
    """
    Middleware / Dependency:
    בודק אם ההרשאה נכונה לפי Bearer Token שנמצא ב־ENV.
    """
    if not API_BEARER_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server missing API_BEARER_TOKEN"
        )

    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header format"
        )

    token = authorization.split(" ", 1)[1].strip()
    if token != API_BEARER_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized"
        )

    return True

































