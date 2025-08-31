# utils/auth.py
from __future__ import annotations
import os, hmac, logging
from typing import Set, Optional
from fastapi import Header, HTTPException, status, Request

logger = logging.getLogger("algogpt.auth")

def _split_tokens(val: str) -> Set[str]:
    raw = val.replace(";", ",").split(",")
    return {p.strip() for p in raw if p and p.strip()}

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
        if not v: continue
        tokens |= _split_tokens(v) if ("," in v or ";" in v) else {v}
    return {t for t in tokens if t}

_TOKENS: Set[str] = _load_tokens_from_env()
_ALLOW_ALL = (os.getenv("SECURITY_ALLOW_ALL","0").strip().lower() in ("1","true","yes","on"))
logger.info("[Auth] loaded %d tokens (allow_all=%s)", len(_TOKENS), _ALLOW_ALL)

def _const_eq(a: str, b: str) -> bool:
    try: return hmac.compare_digest(a, b)
    except Exception: return a == b

def _extract_bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization: return None
    parts = authorization.strip().split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return None

def _any_token_matches(candidate: Optional[str]) -> bool:
    if not candidate: return False
    for t in _TOKENS:
        if _const_eq(candidate, t):
            return True
    return False

def refresh_tokens_from_env() -> int:
    global _TOKENS
    _TOKENS = _load_tokens_from_env()
    logger.info("[Auth] tokens refreshed (%d loaded)", len(_TOKENS))
    return len(_TOKENS)

async def require_api_key(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None),
) -> None:
    if _ALLOW_ALL:
        return
    token = _extract_bearer(authorization) or (x_api_key or "").strip() or None
    if not token:
        qp = request.query_params.get("api_key")
        token = qp.strip() if qp else None
    if not _any_token_matches(token):
        logger.warning("[Auth] invalid token=%s", (token[:6]+"...") if token else None)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )











































































































































































