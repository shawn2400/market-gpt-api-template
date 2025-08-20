# utils/auth.py
from __future__ import annotations
import os
from typing import Set, Optional
from fastapi import Header, HTTPException, status, Query

def _split_tokens(val: str) -> Set[str]:
    parts = [p.strip() for p in val.replace(";", ",").split(",")]
    return {p for p in parts if p}

# -------------------------------------------------
# טוקנים – נטענים מה־ENV
# -------------------------------------------------
_TOKENS: Set[str] = set()

primary = (os.getenv("ALGOGPT_TOKENS") or "").strip()
if primary:
    _TOKENS |= _split_tokens(primary)
else:
    # fallback שמות אחרים
    for key in (
        "ALGOGPT_TOKEN",
        "ALGOGPT_API_TOKEN",
        "API_BEARER",
        "API_BEARER_TOKEN",
        "AUTH_TOKEN",
    ):
        v = (os.getenv(key) or "").strip()
        if not v:
            continue
        _TOKENS |= _split_tokens(v)

_ALLOW_ALL = (os.getenv("SECURITY_ALLOW_ALL", "0").strip().lower() in ("1", "true", "yes"))

# -------------------------------------------------
# Helpers
# -------------------------------------------------
def _extract_bearer(authorization: Optional[str]) -> Optional[str]:
    if authorization is None:
        return None
    if not isinstance(authorization, str):
        try:
            authorization = str(authorization)
        except Exception:
            return None
    parts = authorization.strip().split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return None

# -------------------------------------------------
# פונקציית אימות עיקרית
# -------------------------------------------------
def require_bearer_token(
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-KEY"),
    token: Optional[str] = Query(default=None),
):
    """
    ✅ תומך בשלושה ערוצים:
       - Authorization: Bearer <TOKEN>
       - X-API-KEY: <TOKEN>
       - ?token=<TOKEN>
    """
    if _ALLOW_ALL:
        return None

    bearer = _extract_bearer(authorization)
    candidate = (bearer or (x_api_key or token or "")).strip()

    if candidate and candidate in _TOKENS:
        return None

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

# -------------------------------------------------
# פונקציית אימות לנתיבים פנימיים
# -------------------------------------------------
def require_internal_token(
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-KEY"),
    token: Optional[str] = Query(default=None),
):
    """
    🔓 Internal = משתמש באותה לוגיקה של require_bearer_token
    """
    return require_bearer_token(authorization=authorization, x_api_key=x_api_key, token=token)
































