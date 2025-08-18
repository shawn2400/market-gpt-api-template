# utils/auth.py
from __future__ import annotations
import os, hmac, re
from fastapi import Header, HTTPException, status

# ננקה CR/LF/טאבים ו־ZWSP — אבל לא רווחים רגילים!
_CLEANCTL_RE = re.compile(r"[\r\n\t\u200B\u200C\u200D\u2060\ufeff]+")
_BEARER_RE = re.compile(r"(?i)^\s*Bearer\s+(.+?)\s*$")

def _strip_ctl(s: str | None) -> str:
    return "" if not s else _CLEANCTL_RE.sub("", s).strip()

def _expected_token() -> str:
    for name in ("API_BEARER_TOKEN", "ALGOGPT_TOKEN", "ALGOGPT_API_TOKEN", "API_BEARER"):
        v = os.getenv(name)
        if v:
            return _strip_ctl(v)
    return ""

_ALLOW_ALL = (_strip_ctl(os.getenv("SECURITY_ALLOW_ALL", "")).lower() in ("1","true","yes"))

async def require_bearer_token(authorization: str | None = Header(None)) -> None:
    if _ALLOW_ALL:
        return
    expected = _expected_token()
    if not expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    m = _BEARER_RE.match(authorization)
    if not m:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    provided = _strip_ctl(m.group(1))
    if not (provided and hmac.compare_digest(provided, expected)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
















