# utils/auth.py
from __future__ import annotations
import os
from typing import Set, Optional
from fastapi import Header, HTTPException, status

def _split_tokens(val: str) -> Set[str]:
    parts = [p.strip() for p in val.replace(";", ",").split(",")]
    return {p for p in parts if p}

_TOKENS: Set[str] = set()
for key in ("ALGOGPT_TOKENS", "ALGOGPT_TOKEN", "API_BEARER_TOKEN", "API_BEARER", "API_BEARER_TOKENS"):
    v = (os.getenv(key) or "").strip()
    if not v:
        continue
    if "," in v or ";" in v:
        _TOKENS |= _split_tokens(v)
    else:
        _TOKENS.add(v)

_ALLOW_ALL = os.getenv("SECURITY_ALLOW_ALL", "0").strip().lower() in ("1", "true", "yes")

def _extract_bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    parts = authorization.strip().split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return None

async def require_api_key(authorization: Optional[str] = Header(None)) -> None:
    if _ALLOW_ALL:
        return
    token = _extract_bearer(authorization)
    if not token or token not in _TOKENS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )









































































































































































