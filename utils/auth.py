# utils/auth.py
from __future__ import annotations

import os
import logging
from typing import List, Optional, Dict, Any

logger = logging.getLogger("algogpt.auth")

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _coerce_bool(val: Optional[str]) -> bool:
    return str(val or "").strip().lower() in ("1", "true", "yes", "on")

def _split_multi(s: str) -> List[str]:
    """פיצול רשימה מכל צורה: פסיקים/רווחים/שורות."""
    import re
    return [x for x in re.split(r"[,\s]+", (s or "").strip()) if x]

def _mask(tok: str) -> str:
    if not tok:
        return ""
    if len(tok) <= 4:
        return tok[0] + "…" + tok[-1]
    return tok[:2] + "…" + tok[-2:]

# ──────────────────────────────────────────────────────────────────────────────
# Token store (in-memory)
# ──────────────────────────────────────────────────────────────────────────────

_TOKENS: List[str] = []
_ALLOW_ALL: bool = False

# ──────────────────────────────────────────────────────────────────────────────
# Loading tokens from env/file
# ──────────────────────────────────────────────────────────────────────────────

def _extend_with_api_tokens(toks: List[str]) -> None:
    """
    תמיכה לאחור במשתנים חלופיים — לא חובה להשתמש בהם,
    אבל אם קיימים בסביבה, נטען גם מהם כדי לא להפיל ראוטרים ישנים.
    """
    # Multi-value envs
    for k in ("API_TOKENS", "ALGOGPT_API_TOKENS", "ALGOGPT_TOKENS"):
        v = os.getenv(k, "")
        if v.strip():
            toks.extend(_split_multi(v))

    # Single-value fallbacks
    for k in ("PRIMARY_API_TOKEN", "API_BEARER_TOKEN", "ALGOGPT_API_TOKEN",
              "ALGOGPT_TOKEN", "API_TOKEN", "TOKEN"):
        v = os.getenv(k, "").strip()
        if v:
            toks.append(v)

def load_tokens_from_env() -> List[str]:
    toks: List[str] = []

    # 1) מקור ראשי מומלץ — רשימה (פסיקים/רווחים/שורות)
    toks += _split_multi(os.getenv("AUTH_TOKENS", ""))

    # 2) קובץ/ים: כל שורה = טוקן (אפשר כמה נתיבים מופרדים בפסיקים/רווחים/שורות)
    files = _split_multi(os.getenv("AUTH_TOKENS_FILE", ""))
    for path in files:
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    t = line.strip()
                    if t:
                        toks.append(t)
        except Exception as e:
            logger.warning({"event": "auth.tokens_file_read_failed", "file": path, "error": str(e)})

    # 3) תמיכה לאחור במשתנים חלופיים (לא חובה להשתמש; כאן כדי לא לשבור)
    _extend_with_api_tokens(toks)

    # ניקוי ריקים וכפילויות (שמירת סדר הופעה ראשון)
    toks = [t for t in toks if t]
    uniq = list(dict.fromkeys(toks))
    return uniq

def _compute_allow_all_flag() -> bool:
    """
    דגל 'פתוח לכולם' — אם אחד משלושת השמות דולק (ALLOW_ALL / AUTH_ALLOW_ALL / SECURITY_ALLOW_ALL),
    נחשב True. ברירת מחדל False.
    """
    return (
        _coerce_bool(os.getenv("ALLOW_ALL", "0")) or
        _coerce_bool(os.getenv("AUTH_ALLOW_ALL", "0")) or
        _coerce_bool(os.getenv("SECURITY_ALLOW_ALL", "0"))
    )

def refresh_tokens_from_env() -> Dict[str, Any]:
    global _TOKENS, _ALLOW_ALL
    _TOKENS = load_tokens_from_env()
    _ALLOW_ALL = _compute_allow_all_flag()
    logger.info({
        "event": "auth.tokens_loaded",
        "allow_all": _ALLOW_ALL,
        "count": len(_TOKENS),
        "tokens": [_mask(t) for t in _TOKENS],
    })
    return {"ok": True, "count": len(_TOKENS), "allow_all": _ALLOW_ALL}

# טען מיד בעת ייבוא המודול (כדי שהראוטרים ימצאו את require_api_key כבר בהעלאה)
refresh_tokens_from_env()

# ──────────────────────────────────────────────────────────────────────────────
# Public getters
# ──────────────────────────────────────────────────────────────────────────────

def get_loaded_tokens(mask: bool = True) -> List[str]:
    return [_mask(t) for t in _TOKENS] if mask else list(_TOKENS)

def allow_all() -> bool:
    return _ALLOW_ALL

# ──────────────────────────────────────────────────────────────────────────────
# Request helpers (header/query parsing)
# ──────────────────────────────────────────────────────────────────────────────

def _extract_bearer_from_auth_header(h: Optional[str]) -> Optional[str]:
    """
    מקבל Authorization וחותך Bearer <token> או מחזיר את היחיד אם אין prefix.
    """
    if not h:
        return None
    parts = h.strip().split(None, 1)
    if len(parts) == 2 and parts[0].lower() in ("bearer", "token", "jwt"):
        return parts[1].strip()
    if len(parts) == 1 and parts[0]:
        # אם נתנו ישירות את הטוקן בלי Bearer
        return parts[0].strip()
    return None

def extract_token(request, auth_header: Optional[str], x_api_key: Optional[str]) -> Optional[str]:
    """
    סדר עדיפויות:
    1) X-API-Key אם קיים
    2) Authorization (Bearer / Token / JWT / ערך יחיד)
    3) query param (api_key|apikey|token|key|auth)
    """
    if x_api_key:
        return x_api_key.strip()

    tok = _extract_bearer_from_auth_header(auth_header)
    if tok:
        return tok

    # query params (best-effort)
    try:
        for k in ("api_key", "apikey", "token", "key", "auth"):
            qv = request.query_params.get(k)  # type: ignore[attr-defined]
            if qv:
                return qv.strip()
    except Exception:
        pass

    return None

def token_matches(token: Optional[str]) -> bool:
    if allow_all():
        return True
    if not token:
        return False
    return token in _TOKENS

# ──────────────────────────────────────────────────────────────────────────────
# FastAPI dependency (בדיוק מה שהראוטרים מצפים לו)
# ──────────────────────────────────────────────────────────────────────────────

def require_bearer_token(
    Authorization: Optional[str] = None,
    X_API_Key: Optional[str] = None
) -> str:
    """
    תלות ל-FastAPI — תרים 401 אם הטוקן לא תואם.
    """
    from fastapi import HTTPException
    tok = X_API_Key or _extract_bearer_from_auth_header(Authorization)
    if not token_matches(tok):
        raise HTTPException(status_code=401, detail="Invalid API key")
    return tok or ""

# אליאס לשם הישן/נפוץ בראוטרים
require_api_key = require_bearer_token

# ──────────────────────────────────────────────────────────────────────────────
# Public paths exposure (לנתיב /status/auth)
# ──────────────────────────────────────────────────────────────────────────────

def _split_env(s: str) -> List[str]:
    return [x for x in _split_multi(s)]

def get_public_paths() -> Dict[str, Any]:
    """
    קריאה של רשימות ציבוריות מה-ENV לצורך הצגה ב-/status/auth
    (זה לא קובע הרשאות — ההרשאות נקבעות במידלוור הראשי באפליקציה).
    """
    paths = set(_split_env(os.getenv("SECURITY_PUBLIC_PATHS", "")))
    prefixes = set(_split_env(os.getenv("SECURITY_PUBLIC_PREFIXES", "")))
    return {"paths": sorted(paths), "prefixes": sorted(prefixes)}

























































































































































































