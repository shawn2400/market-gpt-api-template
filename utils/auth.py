# utils/auth.py
from __future__ import annotations
import os
from typing import Set, Optional
from fastapi import Header, HTTPException, status

_TOKEN_KEYS = (
    "ALGOGPT_TOKENS",
    "ALGOGPT_TOKEN",
    "ALGOGPT_API_TOKEN",
    "API_BEARER",
    "API_BEARER_TOKEN",
)

def _split_tokens(val: str) -> Set[str]:
    parts = [p.strip() for p in val.replace(";", ",").split(",")]
    return {p for p in parts if p}

def _load_tokens_from_env() -> Set[str]:
    tokens: Set[str] = set()
    for key in _TOKEN_KEYS:
        v = (os.getenv(key) or "").strip()
        if not v:
            continue
        if "," in v or ";" in v:
            tokens |= _split_tokens(v)
        else:
            tokens.add(v)
    return tokens

def _extract_bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    parts = authorization.strip().split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return None

def require_bearer_token(authorization: Optional[str] = Header(default=None)):
    """
    בודק Authorization: Bearer <token>. קורא טוקנים מה-ENV בכל קריאה.
    SECURITY_ALLOW_ALL=1 → עוקף (לבדיקות בלבד).
    """
    if (os.getenv("SECURITY_ALLOW_ALL", "0").strip().lower() in ("1","true","yes")):
        return None

    token = _extract_bearer(authorization)
    tokens = _load_tokens_from_env()

    if token and token in tokens:
        return None

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")






















