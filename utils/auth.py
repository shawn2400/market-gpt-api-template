# utils/auth.py
from __future__ import annotations
import os
import logging
from typing import List, Optional, Dict, Any

from fastapi import HTTPException, Request

# נשתמש בהגדרות מ-utils.config כדי לשמור תאימות כוללת
from utils.config import (
    get_settings,
    strip_bearer_prefix as _strip_bearer,
    valid_token as _config_valid_token,
)

logger = logging.getLogger("algogpt.auth")

# ----------------- helpers -----------------
def _coerce_bool(val: Optional[str]) -> bool:
    return str(val or "").strip().lower() in ("1", "true", "yes", "on")

def _split_multi(s: str) -> List[str]:
    import re
    return [x for x in re.split(r"[,\s]+", (s or "").strip()) if x]

def _mask(tok: str) -> str:
    if not tok:
        return ""
    if len(tok) <= 4:
        return tok[0] + "…" + tok[-1]
    return tok[:2] + "…" + tok[-2:]

# ----------------- token storage (לוגיקה פנימית, בנוסף להגדרות ב-config) -----------------
_TOKENS: List[str] = []
_ALLOW_ALL: bool = False

def load_tokens_from_env() -> List[str]:
    toks: List[str] = []

    # Multi-value envs
    for k in ("AUTH_TOKENS", "ALGOGPT_API_TOKENS", "API_TOKENS", "ALGOGPT_TOKENS"):
        v = os.getenv(k, "")
        if v.strip():
            toks.extend(_split_multi(v))

    # Single-value fallbacks
    for k in ("PRIMARY_API_TOKEN", "API_BEARER_TOKEN",
              "ALGOGPT_API_TOKEN", "ALGOGPT_TOKEN",
              "API_TOKEN", "TOKEN"):
        v = os.getenv(k, "")
        if v.strip():
            toks.append(v.strip())

    # From files (one token per line)
    for file_env in ("AUTH_TOKENS_FILE", "API_TOKENS_FILE"):
        path = os.getenv(file_env, "").strip()
        if not path:
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    t = (line or "").strip()
                    if t:
                        toks.append(t)
        except Exception as e:
            logger.warning({"event": "auth.tokens_file_read_failed", "file": path, "error": str(e)})

    # ניקוי כפילויות וריקים
    toks = [t for t in toks if t]
    uniq = list(dict.fromkeys(toks))
    return uniq

def refresh_tokens_from_env() -> Dict[str, Any]:
    global _TOKENS, _ALLOW_ALL
    _TOKENS = load_tokens_from_env()
    # ALLOW_ALL מקבל fallback מ-AUTH_ALLOW_ALL
    _ALLOW_ALL = _coerce_bool(os.getenv("ALLOW_ALL", os.getenv("AUTH_ALLOW_ALL", "0")))
    logger.info({
        "event": "auth.tokens_loaded",
        "allow_all": _ALLOW_ALL,
        "count": len(_TOKENS),
        "tokens": [_mask(t) for t in _TOKENS],
    })
    return {"ok": True, "count": len(_TOKENS), "allow_all": _ALLOW_ALL}

# טען פעם ראשונה כשמודול נטען
refresh_tokens_from_env()

def get_loaded_tokens(mask: bool = True) -> List[str]:
    return [_mask(t) for t in _TOKENS] if mask else list(_TOKENS)

def allow_all() -> bool:
    # אם ה-config אומר AUTH_ALLOW_ALL — זה גובר
    s = get_settings()
    return bool(_ALLOW_ALL or s.AUTH_ALLOW_ALL)

# ----------------- request helpers -----------------
def _extract_from_request(request: Request) -> Optional[str]:
    """
    מנסה לחלץ טוקן מה-headers לפי הרשימות שהוגדרו ב-config
    או מה-query params (api_key/token/…)
    תומך ב-Bearer/Token/JWT prefixes.
    """
    s = get_settings()

    # headers first
    try:
        for h in s.AUTH_HEADER_CANDIDATES:
            if h in request.headers:
                raw = request.headers.get(h)
                if not raw:
                    continue
                # אם זה Authorization עם prefix — נפשט
                val = _strip_bearer(raw)
                if val:
                    return val
    except Exception:
        pass

    # query params fallback
    try:
        for q in s.AUTH_QUERY_KEYS:
            if q in request.query_params:
                val = request.query_params.get(q)
                if val:
                    return _strip_bearer(val)
    except Exception:
        pass

    return None

def token_matches(token: Optional[str]) -> bool:
    if allow_all():
        return True
    if not token:
        return False

    # אם ה-config טוען שהטוקן תקף — קבל
    try:
        if _config_valid_token(token):
            return True
    except Exception:
        # אם משום מה config לא זמין — נמשיך לבדוק מול הסט הפנימי
        pass

    # בדיקת הסט הפנימי של מודול זה
    return token in _TOKENS

# ----------------- FastAPI dependency -----------------
def require_bearer_token(request: Request):
    tok = _extract_from_request(request)
    if not token_matches(tok):
        raise HTTPException(status_code=401, detail="Invalid API key")
    return tok

# תאימות לשם ישן
require_api_key = require_bearer_token

# ----------------- Public paths exposure (ל־/status/auth) -----------------
def get_public_paths() -> Dict[str, Any]:
    s = get_settings()
    return {
        "paths": sorted(s.AUTH_PUBLIC_PATHS),
        "prefixes": [],  # נשמר API זהה למה שהיה, גם אם לא משתמשים בפריפיקסים כאן
    }
























































































































































































