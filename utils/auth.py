# utils/auth.py
from __future__ import annotations
import os
from typing import Set, Optional
from fastapi import Header, HTTPException, status, Query

def _split_tokens(val: str) -> Set[str]:
    parts = [p.strip() for p in val.replace(";", ",").split(",")]
    return {p for p in parts if p}

# -------------------------------------------------
# טוקנים נטענים – עדיפות ל-ALGOGPT_TOKENS
# -------------------------------------------------
_TOKENS: Set[str] = set()

primary = (os.getenv("ALGOGPT_TOKENS") or "").strip()
if primary:
    _TOKENS |= _split_tokens(primary)
else:
    # fallback לשמות אחרים – לשמירה על תאימות
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
# פונקציות עזר
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

def require_bearer_token(
    authorization: Optional[str] = Header(default=None),
    token: Optional[str] = Query(default=None),
):
    """
    מאשר גם Authorization: Bearer ... וגם ?token=...
    """
    if _ALLOW_ALL:
        return None
    bearer = _extract_bearer(authorization)
    candidate = (bearer or (token or "")).strip()
    if candidate and candidate in _TOKENS:
        return None
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")





























