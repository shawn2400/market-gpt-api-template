# utils/auth.py
from __future__ import annotations
import os, hmac, re
from fastapi import Header, HTTPException, status

# ניקוי תווי בקרה/רווחים בלתי נראים
_ZWSP = u"\u200B\u200C\u200D\u2060\ufeff"
_CLEAN_RE = re.compile(r"[\r\n\t\s" + _ZWSP + r"]+")

def _clean(s: str | None) -> str:
    if not s:
        return ""
    # מסיר CR/LF/טאבים/ZWSP ורווחים מסביב
    return _CLEAN_RE.sub("", s).strip()

def _expected_token() -> str:
    # סדר עדיפות: API_BEARER_TOKEN ← ALGOGPT_TOKEN ← ALGOGPT_API_TOKEN ← API_BEARER
    for name in ("API_BEARER_TOKEN", "ALGOGPT_TOKEN", "ALGOGPT_API_TOKEN", "API_BEARER"):
        v = _clean(os.getenv(name))
        if v:
            return v
    return ""

_ALLOW_ALL = _clean(os.getenv("SECURITY_ALLOW_ALL", "")).lower() in ("1", "true", "yes")

async def require_bearer_token(authorization: str | None = Header(None)) -> None:
    """
    Secure-by-default:
    - אם SECURITY_ALLOW_ALL=1 → פתוח (נוח לבדיקה בסביבות dev).
    - אחרת: דורש Bearer שמדויק לערך שב-ENV.
    """
    if _ALLOW_ALL:
        return

    expected = _expected_token()
    if not expected:
        # אין טוקן בקונפיג = לא נאפשר גישה
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    auth = _clean(authorization)
    if not auth or not auth.lower().startswith("bearer"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    provided = _clean(auth.split(None, 1)[1] if " " in auth else "")
    # השוואה קבועת-זמן
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")















