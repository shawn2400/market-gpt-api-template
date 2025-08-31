# utils/auth.py
from __future__ import annotations
import os
import hmac
import logging
from typing import Set, Optional, List
from threading import RLock
from fastapi import Header, HTTPException, status, Request

logger = logging.getLogger("algogpt.auth")

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _truthy(v: str | None) -> bool:
    return str(v or "").strip().lower() in ("1", "true", "yes", "on")

def _split_tokens(val: str) -> Set[str]:
    # תומך בפסיקים/נקודה־פסיק/שבירת שורה
    raw = val.replace("\n", ",").replace(";", ",").split(",")
    return {p.strip() for p in raw if p and p.strip()}

def _mask_token(t: str) -> str:
    if not t:
        return ""
    return "***" if len(t) <= 6 else f"{t[:3]}…{t[-3:]}"

def _const_eq(a: str, b: str) -> bool:
    try:
        return hmac.compare_digest(a, b)
    except Exception:
        return a == b

def _extract_bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    parts = authorization.strip().split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return None

# ──────────────────────────────────────────────────────────────────────────────
# Tokens store (with refresh)
# ──────────────────────────────────────────────────────────────────────────────

_TOKENS_LOCK = RLock()
_TOKENS: Set[str] = set()
_ALLOW_ALL: bool = False

def _load_tokens_from_env() -> Set[str]:
    keys = (
        "API_BEARER_TOKEN",
        "API_BEARER_TOKEN_ALT",
        "API_BEARER_TOKENS",
        "ALGOGPT_TOKEN",
        "ALGOGPT_TOKENS",
        "API_BEARER",
    )
    tokens: Set[str] = set()
    for k in keys:
        v = (os.getenv(k) or "").strip()
        if not v:
            continue
        if ("," in v) or (";" in v) or ("\n" in v):
            tokens |= _split_tokens(v)
        else:
            tokens.add(v)
    return {t for t in tokens if t}

def _init_store() -> None:
    global _TOKENS, _ALLOW_ALL
    with _TOKENS_LOCK:
        _TOKENS = _load_tokens_from_env()
        _ALLOW_ALL = _truthy(os.getenv("SECURITY_ALLOW_ALL"))
    logger.info("[Auth] loaded %d tokens (allow_all=%s)", len(_TOKENS), _ALLOW_ALL)

_init_store()

def refresh_tokens_from_env() -> int:
    """רענון טוקנים ו־allow_all מתוך ENV (ללא ריסטארט פרוסס)."""
    global _TOKENS, _ALLOW_ALL
    with _TOKENS_LOCK:
        _TOKENS = _load_tokens_from_env()
        _ALLOW_ALL = _truthy(os.getenv("SECURITY_ALLOW_ALL"))
        count = len(_TOKENS)
    logger.info("[Auth] tokens refreshed (%d loaded, allow_all=%s)", count, _ALLOW_ALL)
    return count

def get_loaded_tokens(mask: bool = True) -> List[str]:
    """
    מחזיר רשימת הטוקנים הטעונים. ברירת מחדל: במסוך.
    שים לב: החזרת טוקנים גולמיים עלולה להיות מסוכנת—השתמש בזהירות!
    """
    with _TOKENS_LOCK:
        toks = list(_TOKENS)
    return [(_mask_token(t) if mask else t) for t in toks]

def allow_all() -> bool:
    with _TOKENS_LOCK:
        return _ALLOW_ALL

def token_matches(candidate: Optional[str]) -> bool:
    if not candidate:
        return False
    with _TOKENS_LOCK:
        for t in _TOKENS:
            if _const_eq(candidate, t):
                return True
    return False

def extract_token(
    request: Request,
    authorization: Optional[str] = None,
    x_api_key: Optional[str] = None,
) -> Optional[str]:
    """
    מאחד את כל מקורות הטוקן: Authorization: Bearer, X-API-Key, ו־?api_key=
    """
    token = _extract_bearer(authorization) or (x_api_key or "").strip() or None
    if not token:
        qp = request.query_params.get("api_key")
        token = qp.strip() if qp else None
    return token or None

# ──────────────────────────────────────────────────────────────────────────────
# FastAPI dependency
# ──────────────────────────────────────────────────────────────────────────────

async def require_api_key(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None),
) -> None:
    if allow_all():
        return
    token = extract_token(request, authorization, x_api_key)
    if not token_matches(token):
        logger.warning("[Auth] invalid token=%s", (token[:6] + "...") if token else None)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )

__all__ = [
    "require_api_key",
    "refresh_tokens_from_env",
    "get_loaded_tokens",
    "extract_token",
    "allow_all",
    "token_matches",
]












































































































































































