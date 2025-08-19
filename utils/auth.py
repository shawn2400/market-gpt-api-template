# utils/auth.py
from __future__ import annotations
import os
from typing import Set, Optional
from fastapi import Header, HTTPException, status, Request

def _split_tokens(val: str) -> Set[str]:
    parts = [p.strip() for p in val.replace(";", ",").split(",")]
    return {p for p in parts if p}

# קונפיג: תמיכה במספר שמות משתנים / רשימות
_TOKENS: Set[str] = set()
for key in ("ALGOGPT_TOKENS", "ALGOGPT_TOKEN", "ALGOGPT_API_TOKEN", "API_BEARER"):
    v = (os.getenv(key) or "").strip()
    if not v:
        continue
    if "," in v or ";" in v:
        _TOKENS |= _split_tokens(v)
    else:
        _TOKENS.add(v)

_ALLOW_ALL = (os.getenv("SECURITY_ALLOW_ALL", "0").strip().lower() in ("1", "true", "yes"))

def _extract_bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    # תומך גם ב־"bearer" קטנות או רווחים כפולים
    parts = authorization.strip().split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return None

def require_bearer_token(authorization: Optional[str] = Header(default=None), request: Request = None):
    """
    תלוי־ראוט: בודק Authorization: Bearer <token>.
    אם SECURITY_ALLOW_ALL=1 — עוקף (לסביבת פיתוח/סמוק).
    """
    if _ALLOW_ALL:
        return None
    token = _extract_bearer(authorization)
    if token and token in _TOKENS:
        return None
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Unauthorized",
    )


















