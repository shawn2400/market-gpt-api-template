# utils/auth.py
from __future__ import annotations
import os, hmac, logging, re
from typing import Set, Optional, List
from threading import RLock
from fastapi import Header, HTTPException, status, Request

logger = logging.getLogger("algogpt.auth")

def _truthy(v: str | None) -> bool:
    return str(v or "").strip().lower() in {"1", "true", "yes", "on"}

def _split_tokens(val: str) -> Set[str]:
    # ⬅️ כעת תומך גם ברווחים
    parts = re.split(r"[,\n;\s]+", val.strip())
    return {p for p in (s.strip() for s in parts) if p}

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

# Tokens
_TOKENS_LOCK = RLock()
_TOKENS: Set[str] = set()
_ALLOW_ALL: bool = False
_PUBLIC_STATUS: bool = _truthy(os.getenv("SECURITY_PUBLIC_STATUS", "1"))

def _load_tokens_from_env() -> Set[str]:
    keys = (
        "API_BEARER_TOKEN",
        "API_BEARER_TOKEN_ALT",
        "API_BEARER_TOKENS",
        "ALGOGPT_TOKEN",
        "ALGOGPT_TOKENS",
        "API_BEARER",
        # אם יש אצלך גם API_TOKENS – אפשר להוסיף:
        "API_TOKENS",
    )
    tokens: Set[str] = set()
    for k in keys:
        v = (os.getenv(k) or "").strip()
        if not v:
            continue
        tokens |= _split_tokens(v)
    return {t for t in tokens if t}

def _init_store() -> None:
    global _TOKENS, _ALLOW_ALL, _PUBLIC_STATUS
    with _TOKENS_LOCK:
        _TOKENS = _load_tokens_from_env()
        _ALLOW_ALL = _truthy(os.getenv("SECURITY_ALLOW_ALL"))
        _PUBLIC_STATUS = _truthy(os.getenv("SECURITY_PUBLIC_STATUS", "1"))
    logger.info("[Auth] loaded %d tokens (allow_all=%s, public_status=%s)",
                len(_TOKENS), _ALLOW_ALL, _PUBLIC_STATUS)

_init_store()

def refresh_tokens_from_env() -> int:
    global _TOKENS, _ALLOW_ALL, _PUBLIC_STATUS
    with _TOKENS_LOCK:
        _TOKENS = _load_tokens_from_env()
        _ALLOW_ALL  = _truthy(os.getenv("SECURITY_ALLOW_ALL"))
        _PUBLIC_STATUS = _truthy(os.getenv("SECURITY_PUBLIC_STATUS", "1"))
        count = len(_TOKENS)
    logger.info("[Auth] tokens refreshed (%d loaded, allow_all=%s, public_status=%s)",
                count, _ALLOW_ALL, _PUBLIC_STATUS)
    return count

def get_loaded_tokens(mask: bool = True) -> List[str]:
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

def _header_any(request: Request, names: tuple[str, ...]) -> Optional[str]:
    for n in names:
        v = request.headers.get(n)
        if v and v.strip():
            return v.strip()
    return None

def extract_token(
    request: Request,
    authorization: Optional[str] = None,
    x_api_key: Optional[str] = None,
) -> Optional[str]:
    # 1) Authorization: Bearer ...
    token = _extract_bearer(authorization or request.headers.get("authorization"))
    # 2) מפתחים אוהבים וריאציות נוספות:
    if not token:
        hdr = _header_any(
            request,
            (
                "x-api-key",
                "x-auth-token",
                "x-token",
                "x-algogpt-token",
                "x-authorization",
            ),
        )
        token = (hdr or "").strip() or None
    # 3) query params
    if not token:
        qp = request.query_params.get("api_key") or request.query_params.get("token")
        token = qp.strip() if qp else None
    return token or None

# FastAPI dependency
async def require_api_key(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None),
) -> None:
    # ⬅️ אופציונלי: לאפשר /ping ו-/status ללא Auth (לבריאות/בדיקות), נשלט ב-ENV
    if request.url.path in ("/ping", "/status") and _PUBLIC_STATUS:
        return
    if allow_all():
        return
    token = extract_token(request, authorization, x_api_key)
    if not token_matches(token):
        masked = (token[:6] + "...") if token else None
        logger.warning("[Auth] invalid token=%s path=%s", masked, request.url.path)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "Bearer, X-API-Key"},
        )

# Alias for backward compatibility
require_bearer_token = require_api_key

__all__ = [
    "require_api_key",
    "require_bearer_token",
    "refresh_tokens_from_env",
    "get_loaded_tokens",
    "extract_token",
    "allow_all",
    "token_matches",
]














































































































































































