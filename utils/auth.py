# utils/auth.py
from __future__ import annotations
import os
import logging
from typing import List, Optional, Dict, Any

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

# ----------------- token storage -----------------
_TOKENS: List[str] = []
_ALLOW_ALL: bool = False

def _extend_with_api_tokens(toks: List[str]) -> List[str]:
    # Multi-value envs
    for k in ("API_TOKENS", "ALGOGPT_API_TOKENS", "ALGOGPT_TOKENS"):
        v = os.getenv(k, "")
        if v.strip():
            toks.extend(_split_multi(v))
    # Single-value fallbacks
    for k in ("API_BEARER_TOKEN", "PRIMARY_API_TOKEN",
              "ALGOGPT_API_TOKEN", "ALGOGPT_TOKEN",
              "API_TOKEN", "TOKEN"):
        v = os.getenv(k, "").strip()
        if v:
            toks.append(v)
    # de-dup & clean
    return list(dict.fromkeys([t for t in toks if t]))

def load_tokens_from_env() -> List[str]:
    toks: List[str] = []
    # 1) AUTH_TOKENS (רשימה בפסיקים/רווחים/שורות)
    toks += _split_multi(os.getenv("AUTH_TOKENS", ""))

    # 2) AUTH_TOKENS_FILE (אפשר כמה נתיבים מופרדים בפסיקים/רווחים/שורות)
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

    # הוספת מקורות API_* נוספים
    toks = _extend_with_api_tokens(toks)

    # ניקוי כפילויות וריקים
    toks = [t for t in toks if t]
    uniq = list(dict.fromkeys(toks))
    return uniq

def refresh_tokens_from_env() -> Dict[str, Any]:
    global _TOKENS, _ALLOW_ALL
    _TOKENS = load_tokens_from_env()
    # ALLOW_ALL או AUTH_ALLOW_ALL (fallback)
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
    return _ALLOW_ALL

# ----------------- request helpers -----------------
def _extract_bearer_from_auth_header(h: Optional[str]) -> Optional[str]:
    if not h:
        return None
    parts = h.strip().split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    # אם נתנו ישירות את הטוקן בלי "Bearer"
    if len(parts) == 1 and parts[0]:
        return parts[0].strip()
    return None

def extract_token(request, auth_header: Optional[str], x_api_key: Optional[str]) -> Optional[str]:
    # עדיפות ל־X-API-Key אם קיים
    if x_api_key:
        return x_api_key.strip()
    # אחרת Authorization
    tok = _extract_bearer_from_auth_header(auth_header)
    if tok:
        return tok
    # אופציונלי: query param ?token=...
    try:
        qtok = request.query_params.get("token")
        if qtok:
            return qtok.strip()
    except Exception:
        pass
    return None

def token_matches(token: Optional[str]) -> bool:
    if allow_all():
        return True
    if not token:
        return False
    return token in _TOKENS

# ----------------- FastAPI dependency (למי שמשתמש) -----------------
def require_bearer_token(Authorization: Optional[str] = None, X_API_Key: Optional[str] = None):
    from fastapi import HTTPException
    tok = X_API_Key or _extract_bearer_from_auth_header(Authorization)
    if not token_matches(tok):
        raise HTTPException(status_code=401, detail="Invalid API key")
    return tok

# תאימות לשם הישן בקוד אחר
require_api_key = require_bearer_token

# ----------------- Public paths exposure (ל־/status/auth) -----------------
def _split_env(s: str) -> List[str]:
    return [x for x in _split_multi(s)]

def get_public_paths() -> Dict[str, Any]:
    # זה תואם ל-main.py: SECURITY_PUBLIC_PATHS / SECURITY_PUBLIC_PREFIXES
    paths = set(_split_env(os.getenv("SECURITY_PUBLIC_PATHS", "")))
    prefixes = set(_split_env(os.getenv("SECURITY_PUBLIC_PREFIXES", "")))
    return {"paths": sorted(paths), "prefixes": sorted(prefixes)}























































































































































































