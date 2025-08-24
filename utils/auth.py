# utils/auth.py
from __future__ import annotations
import os
from fastapi import Header, HTTPException, Request

# אוספים טוקנים משני משתנים כדי לשמור תאימות לאחור
TOKENS = [
    t.strip()
    for t in (os.getenv("API_BEARER_TOKEN", "") + "," + os.getenv("ALGOGPT_TOKENS", "")).split(",")
    if t.strip()
]
ALLOW_ALL = os.getenv("SECURITY_ALLOW_ALL", "0").strip().lower() in ("1", "true", "yes")

async def require_api_key(
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
):
    """
    אימות Bearer פשוט:
    - Authorization: Bearer <token>
    - X-API-Key: <token>
    - פרמטר שאילתה: ?token=<token>
    """
    if ALLOW_ALL:
        return True

    supplied: str | None = None

    # 1) Authorization: Bearer <token>
    if authorization and authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()

    # 2) X-API-Key
    if not supplied and x_api_key:
        supplied = x_api_key.strip()

    # 3) ?token=<...>
    if not supplied:
        supplied = request.query_params.get("token")

    if supplied and supplied in TOKENS:
        return True

    raise HTTPException(status_code=401, detail="Invalid API key")

# ===== תאימות לאחור =====
# יש קוד ישן שמייבא require_bearer_token – נשאיר אליאס מלא עם אותה חתימה בדיוק.
async def require_bearer_token(
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
):
    return await require_api_key(request, authorization, x_api_key)

# אליאס נוח כללי – אם יש מודולים שמייבאים require_auth
require_auth = require_api_key











































