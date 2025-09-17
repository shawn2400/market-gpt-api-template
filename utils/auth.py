# utils/auth.py
from __future__ import annotations
import os
import time
import logging
from typing import Optional, Set, List
from fastapi import Request, Header, HTTPException

logger = logging.getLogger("algogpt.auth")

# ─────────────────────────
# ENV helpers
# ─────────────────────────
def _b(v: str | None) -> bool:
    return str(v or "").lower() in ("1", "true", "yes", "on")

def _split(s: str) -> List[str]:
    return [p.strip() for p in (s or "").split(",") if p.strip()]

# ─────────────────────────
# Security config (public)
# ─────────────────────────
_ALLOW_ALL = _b(os.getenv("SECURITY_ALLOW_ALL"))
_PUBLIC_STATUS = _b(os.getenv("SECURITY_PUBLIC_STATUS"))
_PUBLIC_PATHS: Set[str] = set(_split(os.getenv("SECURITY_PUBLIC_PATHS", "")))
_PUBLIC_PREFIXES: List[str] = _split(os.getenv("SECURITY_PUBLIC_PREFIXES", ""))

def _is_public(path: str) -> bool:
    if _ALLOW_ALL:
        return True
    # תמיד להתיר את /status כשSECURITY_PUBLIC_STATUS פעיל
    if _PUBLIC_STATUS and path in ("/status/ping", "/status/all"):
        return True
    if path in _PUBLIC_PATHS:
        return True
    for pref in _PUBLIC_PREFIXES:
        if path.startswith(pref):
            return True
    return False

# ─────────────────────────
# Tokens cache
# ─────────────────────────
_TOKENS: Set[str] = set()
_TOKENS_LOADED_AT = 0.0
_TOKENS_TTL_SEC = float(os.getenv("AUTH_TOKENS_TTL", "10"))

def _load_tokens(force: bool = False) -> Set[str]:
    """Load tokens from API_TOKENS and API_TOKENS_FILE with small TTL."""
    global _TOKENS, _TOKENS_LOADED_AT
    now = time.time()
    if not force and _TOKENS and (now - _TOKENS_LOADED_AT) < _TOKENS_TTL_SEC:
        return _TOKENS

    toks: Set[str] = set()
    # from env list
    for t in _split(os.getenv("API_TOKENS", "")):
        toks.add(t)
    # from file lines
    fp = os.getenv("API_TOKENS_FILE", "").strip()
    if fp:
        try:
            if os.path.isfile(fp):
                with open(fp, "r", encoding="utf-8") as fh:
                    for ln in fh:
                        ln = ln.strip()
                        if ln:
                            toks.add(ln)
        except Exception as e:
            logger.warning("auth: failed reading API_TOKENS_FILE %s: %s", fp, e)

    _TOKENS = toks
    _TOKENS_LOADED_AT = now
    logger.info("auth: loaded %d token(s)", len(_TOKENS))
    return _TOKENS

# ─────────────────────────
# Token extraction
# ─────────────────────────
def _extract_token(
    request: Request,
    authorization: Optional[str],
    x_api_key: Optional[str],
) -> Optional[str]:
    # Header: X-API-Key
    if x_api_key and x_api_key.strip():
        return x_api_key.strip()

    # Header: Authorization (Bearer <token> or raw token)
    if authorization and authorization.strip():
        a = authorization.strip()
        parts = a.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1].strip()
        return a  # allow raw token (some clients send just the token)

    # Optional query param fallback
    try:
        qp = request.query_params
        for k in ("api_key", "token"):
            v = qp.get(k)
            if v and v.strip():
                return v.strip()
    except Exception:
        pass

    return None

# ─────────────────────────
# FastAPI dependency
# ─────────────────────────
async def require_api_key(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None),
) -> bool:
    """
    Use as a FastAPI dependency to protect routes.
    Allows public paths/prefixes per env. Raises 401 if token missing/invalid.
    """
    # Public or preflight
    if request.method == "OPTIONS" or _is_public(request.url.path):
        return True

    token = _extract_token(request, authorization, x_api_key)
    if not token:
        raise HTTPException(status_code=401, detail="Missing API token")

    if token not in _load_tokens():
        raise HTTPException(status_code=401, detail="Invalid API token")

    return True

# ─────────────────────────
# Introspection helpers (optional)
# ─────────────────────────
def get_loaded_tokens(mask: bool = True) -> List[str]:
    toks = sorted(_load_tokens())
    if not mask:
        return toks
    return [f"{t[:3]}***{t[-2:]}" if len(t) > 5 else "***" for t in toks]

def get_public_config() -> dict:
    return {
        "allow_all": _ALLOW_ALL,
        "public_status": _PUBLIC_STATUS,
        "paths": sorted(_PUBLIC_PATHS),
        "prefixes": list(_PUBLIC_PREFIXES),
        "tokens_ttl_sec": _TOKENS_TTL_SEC,
    }

__all__ = [
    "require_api_key",
    "get_loaded_tokens",
    "get_public_config",
]





















































































































































































