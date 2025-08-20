# utils/auth.py
from __future__ import annotations
import os
from typing import Set, Optional
from fastapi import Header, HTTPException, status, Query

def _split_tokens(val: str) -> Set[str]:
    parts = [p.strip() for p in val.replace(";", ",").split(",")]
    return {p for p in parts if p}

def _extract_bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
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

def _load_tokens() -> Set[str]:
    """טוען טוקנים בכל קריאה (דינמי מה־ENV)."""
    tokens: Set[str] = set()

    primary = (os.getenv("ALGOGPT_TOKENS") or "").strip()
    if primary:
        tokens |= _split_tokens(primary)
    else:
        # fallback לשמות אחרים
        for key in (
            "ALGOGPT_TOKEN",
            "ALGOGPT_API_TOKEN",
            "API_BEARER",
            "API_BEARER_TOKEN",
            "AUTH_TOKEN",
        ):
            v = (os.getenv(key) or "").strip()
            if v:
                tokens |= _split_tokens(v)
    return tokens

def require_bearer_token(
    authorization: Optional[str] = Header(default=None),
    token: Optional[str] = Query(default=None),
):
    """
    מאשר גם Authorization: Bearer ... וגם ?token=...
    """
    allow_all = (os.getenv("SECURITY_ALLOW_ALL", "0").strip().lower() in ("1", "true", "yes"))
    if allow_all:
        return None

    tokens = _load_tokens()
    bearer = _extract_bearer(authorization)
    candidate = (bearer or (token or "")).strip()
    if candidate and candidate in tokens:
        return None

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")





























