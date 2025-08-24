# utils/auth.py
from __future__ import annotations
import os
from typing import Set, Optional
from fastapi import Header, HTTPException, status

def _split_tokens(val: str) -> Set[str]:
    parts = [p.strip() for p in val.replace(";", ",").split(",")]
    return {p for p in parts if p}

# --- Load allowed tokens from ENV ---
_TOKENS: Set[str] = set()
for key in ("ALGOGPT_TOKENS", "ALGOGPT_TOKEN", "ALGOGPT_API_TOKEN", "API_BEARER", "API_BEARER_TOKEN"):
    v = (os.getenv(key) or "").strip()
    if not v:
        continue
    if "," in v or ";" in v:
        _TOKENS |= _split_tokens(v)
    else:
        _TOKENS.add(v)

_ALLOW_ALL = (os.getenv("SECURITY_ALLOW_ALL", "0").strip().lower() in ("1", "true", "yes"))

def require_api_key(authorization: Optional[str] = Header(default=None)) -> str:
    """
    דרישת API Key לכל הקריאות המוגנות.
    """
    if _ALLOW_ALL:
        return "ALLOW_ALL"

    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Authorization header")

    parts = authorization.strip().split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Authorization format")

    token = parts[1].strip()
    if token not in _TOKENS:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

    return token







































































































































































