# utils/auth.py
from __future__ import annotations

import os
import re
from fastapi import Header, HTTPException, Request

# =========================
# Env
# =========================

def _truthy(val: str | None) -> bool:
    if val is None:
        return False
    return val.strip().lower() in ("1", "true", "yes", "y", "on")

SECURITY_ALLOW_ALL = _truthy(os.getenv("SECURITY_ALLOW_ALL", "0"))

# טוקן ראשי בודד (אופציונלי)
_API_BEARER_TOKEN = os.getenv("API_BEARER_TOKEN", "").strip()

# רשימת טוקנים חלופיים (אופציונלי), מופרדים בפסיקים/רווחים/שורות
_ALGOGPT_TOKENS_RAW = os.getenv("ALGOGPT_TOKENS", "").strip()

def _allowed_tokens() -> set[str]:
    tokens: list[str] = []
    if _API_BEARER_TOKEN:
        tokens.append(_API_BEARER_TOKEN)
    if _ALGOGPT_TOKENS_RAW:
        # פיצול לפי פסיקים/רווחים/שבירות שורה
        parts = re.split(r"[,\s]+", _ALGOGPT_TOKENS_RAW)
        tokens.extend([p.strip() for p in parts if p and p.strip()])
    return set(tokens)

# =========================
# Core
# =========================

def _extract_token_from_authorization(authorization: str | None) -> str | None:
    """
    מקבל Header Authorization גולמי ומחלץ ממנו את הטוקן.
    תומך גם ב-`Bearer <token>` וגם בערך יחיד (raw token).
    רגישות אותיות בשם הסכמה מבוטלת (bearer/BEARER/…).
    """
    if not authorization:
        return None
    raw = authorization.strip()
    if not raw:
        return None

    parts = raw.split()
    if len(parts) == 1:
        # ערך יחיד — מתייחסים כטוקן
        return parts[0].strip()

    scheme, *rest = parts
    if scheme.lower() == "bearer" and rest:
        return rest[0].strip()

    # סכמה אחרת — לא מקבלים
    return None


def require_api_key(
    request: Request,
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> bool:
    """
    Middleware להגנה על ה-API.
    מאשר גישה אם אחד מהתנאים:
      - SECURITY_ALLOW_ALL=1  (פתוח כולו — DEV בלבד)
      - לא הוגדר אף טוקן ב-Env (נחשב מצב DEV)
      - קיים טוקן חוקי ב-Authorization: Bearer <TOKEN> או בכותרת X-API-Key

    מחזיר:
      True על הצלחה; אחרת מרים HTTPException(401).
    """
    # התנהגות DEV: פתוח לגמרי
    if SECURITY_ALLOW_ALL:
        return True

    allowed = _allowed_tokens()
    # אם אין בכלל טוקנים מוגדרים — לא ננעל (DEV)
    if not allowed:
        return True

    # לא חוסמים בקשות OPTIONS (CORS preflight)
    if request.method.upper() == "OPTIONS":
        return True

    # 1) ניסיון לחלץ מ-Authorization
    token = _extract_token_from_authorization(authorization)

    # 2) או מכותרת חלופית X-API-Key
    if not token and x_api_key:
        token = x_api_key.strip() or None

    if not token:
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if token not in allowed:
        raise HTTPException(
            status_code=401,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return True


def require_bearer_token(
    request: Request,
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> bool:
    """
    Alias ל-require_api_key לשמירה על תאימות לאחור.
    """
    return require_api_key(request=request, authorization=authorization, x_api_key=x_api_key)








































