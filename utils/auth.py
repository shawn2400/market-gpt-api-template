# utils/auth.py
from __future__ import annotations
import os, hmac, re
from fastapi import Header, HTTPException, status

# הסר רק תווי שליטה ו-ZWSP — לא רווחים רגילים!
_ZWSP = u"\u200B\u200C\u200D\u2060\ufeff"
_CLEAN_RE = re.compile(r"[\r\n\t" + _ZWSP + r"]+")

def _clean(s: str | None) -> str:
    if not s:
        return ""
    # מסיר CR/LF/TAB/ZWSP ומבצע strip לקצוות — שומר על רווחים פנימיים
    return _CLEAN_RE.sub("", s).strip()

def _expected_token() -> str:
    # סדר עדיפות: API_BEARER_TOKEN ← ALGOGPT_TOKEN ← ALGOGPT_API_TOKEN ← API_BEARER
    for name in ("API_BEARER_TOKEN", "ALGOGPT_TOKEN", "ALGOGPT_API_TOKEN", "API_BEARER"):
        v = _clean(os.getenv(name))
        if v:
            return v
    return ""

def _extract_bearer_token(authorization: str | None) -> str:
    if not authorization:
        return ""
    # מנקה תווי שליטה בלבד, לא פוגע ברווח אחרי "Bearer "
    auth = _CLEAN_RE.sub("", authorization).strip()
    low = auth.lower()
    if low.startswith("bearer "):          # הפורמט התקין
        token = auth.split(" ", 1)[1]
    elif low.startswith("bearer"):         # תומך גם ב-Bearer<token> ללא רווח
        token = auth[len("bearer"):]
    else:
        return ""
    return _clean(token)

_ALLOW_ALL = _clean(os.getenv("SECURITY_ALLOW_ALL", "")).lower() in ("1", "true", "yes")

async def require_bearer_token(authorization: str | None = Header(None)) -> None:
    """
    Secure-by-default:
    - אם SECURITY_ALLOW_ALL=1 → פתוח (Dev בלבד).
    - אחרת: דורש Bearer שמדויק לערך שב-ENV.
    """
    if _ALLOW_ALL:
        return

    expected = _expected_token()
    if not expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    provided = _extract_bearer_token(authorization)
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
















