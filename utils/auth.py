# utils/auth.py
from __future__ import annotations
import os
from typing import Set, Optional
from fastapi import Header, HTTPException, status, Request

# ============================================================
# איסוף טוקנים מהסביבה (תומך במספר משתני ENV וריבוי ערכים)
# ============================================================

def _split_tokens(val: str) -> Set[str]:
    # מפריד בפסיק/נקודה-פסיק, מנקה רווחים, ומתעלם מריקים
    parts = [p.strip() for p in val.replace(";", ",").split(",")]
    return {p for p in parts if p}

def _read_tokens_file(path: str) -> Set[str]:
    toks: Set[str] = set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s or s.startswith("#"):
                    continue
                toks.add(s)
    except Exception:
        # קובץ אופציונלי – אין חריגה אם לא נמצא
        pass
    return toks

# חשוב: הוספת API_BEARER_TOKEN + כינויים נפוצים
_ENV_TOKEN_KEYS = (
    "API_BEARER_TOKEN",   # <— חדש: זה מהקובץ .env שלך
    "API_BEARER",
    "ALGOGPT_TOKENS",
    "ALGOGPT_TOKEN",
    "ALGOGPT_API_TOKEN",
    "BEARER_TOKEN",
)

_TOKENS: Set[str] = set()
for key in _ENV_TOKEN_KEYS:
    v = (os.getenv(key) or "").strip()
    if not v:
        continue
    if "," in v or ";" in v:
        _TOKENS |= _split_tokens(v)
    else:
        _TOKENS.add(v)

# תמיכה אופציונלית: קובץ עם טוקנים (שורה = טוקן)
_TOKENS |= _read_tokens_file(os.getenv("TOKENS_FILE", "").strip() or "")

# דגל עקיפה כולל (לבדיקות בלבד)
_ALLOW_ALL = (os.getenv("SECURITY_ALLOW_ALL", "0").strip().lower() in ("1", "true", "yes"))

# ============================================================
# עזרי ניתוח כותרת Authorization / פרמטרים
# ============================================================

def _extract_bearer(authorization: Optional[str]) -> Optional[str]:
    """
    מחלץ טוקן מתוך Authorization.
    תומך גם ב: "Bearer <token>" וגם במקרה של Authorization="<token>" (fallback).
    """
    if not authorization:
        return None
    s = authorization.strip()
    parts = s.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    # fallback: אם נתנו רק את הטוקן ללא "Bearer"
    if len(parts) == 1 and parts[0]:
        return parts[0].strip()
    return None

def _is_token_valid(tok: Optional[str]) -> bool:
    return bool(tok and tok in _TOKENS)

# ============================================================
# FastAPI dependency לשימוש עם Depends(require_bearer_token)
# ============================================================

def require_bearer_token(
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None),   # אפשר גם X-API-Key
    request: Request = None
):
    """
    בודק הרשאה ע"פ:
      1) Authorization: Bearer <token>     (או Authorization: <token>)
      2) X-API-Key: <token>
      3) Query string: ?token=<token>      (fallback נוח ל-curl)

    דגל SECURITY_ALLOW_ALL=1 עוקף (לשימוש בפיתוח/דבאג בלבד).

    אם אין התאמה – מוחזר 401 עם WWW-Authenticate: Bearer.
    """
    if _ALLOW_ALL:
        return None

    # מקור 1: Authorization
    token = _extract_bearer(authorization)

    # מקור 2: X-API-Key
    if not token and x_api_key:
        token = x_api_key.strip()

    # מקור 3: query param ?token=
    if not token and request is not None:
        qp = request.query_params.get("token")
        if qp:
            token = qp.strip()

    if _is_token_valid(token):
        return None

    # כאן נכשל – 401
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Unauthorized",
        headers={"WWW-Authenticate": 'Bearer realm="AlgoGPT"'},
    )

# ============================================================
# עזרי דיבאג (אופציונלי לשימוש פנימי)
# ============================================================

def get_valid_tokens_snapshot() -> Set[str]:
    """
    שימושי לדיאגנוסטיקה בשורת הפקודה/בדיקות (אל תחשוף ל-API).
    """
    return set(_TOKENS)

def auth_allow_all() -> bool:
    return _ALLOW_ALL


















