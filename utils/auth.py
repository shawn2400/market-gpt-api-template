# utils/auth.py
from __future__ import annotations

import os
import time
import logging
from typing import Optional, Set, List, Dict, Any
from fastapi import Request, Header, HTTPException

logger = logging.getLogger("algogpt.auth")

# ─────────────────────────
# ENV helpers
# ─────────────────────────
def _b(v: str | None) -> bool:
    return str(v or "").lower() in ("1", "true", "yes", "on")

def _split(s: str) -> List[str]:
    raw = (s or "").replace("\n", ",").replace("\t", ",").strip()
    return [p.strip() for p in raw.split(",") if p.strip()]

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
    # תמיד להתיר את /status כש SECURITY_PUBLIC_STATUS פעיל
    if _PUBLIC_STATUS and path in ("/status/ping", "/status/all"):
        return True
    if path in _PUBLIC_PATHS:
        return True
    for pref in _PUBLIC_PREFIXES:
        if pref and path.startswith(pref):
            return True
    return False

# ─────────────────────────
# Tokens cache (with TTL)
# ─────────────────────────
_TOKENS: Set[str] = set()
_TOKENS_LOADED_AT = 0.0

def _tokens_ttl_sec() -> float:
    try:
        return float(os.getenv("AUTH_TOKENS_TTL", "60"))
    except Exception:
        return 60.0

def _load_tokens(force: bool = False) -> Set[str]:
    """Load tokens from API_TOKENS and API_TOKENS_FILE with small TTL."""
    global _TOKENS, _TOKENS_LOADED_AT
    now = time.time()
    ttl = _tokens_ttl_sec()
    if not force and _TOKENS and (now - _TOKENS_LOADED_AT) < ttl:
        return _TOKENS

    toks: Set[str] = set()
    # from env
    toks.update(_split(os.getenv("API_TOKENS", "")))
    # from file (one token per line)
    fp = (os.getenv("API_TOKENS_FILE", "") or "").strip()
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

# prime cache on import
_load_tokens(force=True)

# ─────────────────────────
# Token extraction / check
# ─────────────────────────
def extract_token(
    request: Request,
    authorization: Optional[str],
    x_api_key: Optional[str],
) -> Optional[str]:
    # Header: X-API-Key
    if x_api_key and x_api_key.strip():
        return x_api_key.strip()

    # Header: Authorization (Bearer <token> או טוקן גולמי)
    if authorization and authorization.strip():
        a = authorization.strip()
        parts = a.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1].strip()
        return a  # יש קליינטים ששולחים רק טוקן

    # Query param fallback
    try:
        qp = request.query_params
        for k in ("api_key", "token"):
            v = qp.get(k)
            if v and v.strip():
                return v.strip()
    except Exception:
        pass
    return None

def token_matches(token: Optional[str]) -> bool:
    return bool(token and token in _load_tokens())

# ─────────────────────────
# FastAPI dependency
# ─────────────────────────
async def require_api_key(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None),
) -> bool:
    """
    תלויות אבטחה לראוטים מוגנים:
    - מתיר נתיבים ציבוריים לפי ENV.
    - אם לא ציבורי: דורש טוקן תקף (Bearer / X-API-Key / ?api_key=...).
    """
    if request.method == "OPTIONS" or _is_public(request.url.path):
        return True

    token = extract_token(request, authorization, x_api_key)
    if not token:
        raise HTTPException(status_code=401, detail="Missing API token")

    if not token_matches(token):
        raise HTTPException(status_code=401, detail="Invalid API token")

    return True

# ─────────────────────────
# Introspection helpers
# ─────────────────────────
def get_loaded_tokens(mask: bool = True) -> List[str]:
    toks = sorted(_load_tokens())
    if not mask:
        return toks
    return [f"{t[:3]}***{t[-2:]}" if len(t) > 5 else "***" for t in toks]

def get_public_config() -> Dict[str, Any]:
    return {
        "allow_all": _ALLOW_ALL,
        "public_status": _PUBLIC_STATUS,
        "paths": sorted(_PUBLIC_PATHS),
        "prefixes": list(_PUBLIC_PREFIXES),
        "tokens_ttl_sec": _tokens_ttl_sec(),
    }

__all__ = [
    "require_api_key",
    "extract_token", "token_matches",
    "get_loaded_tokens", "get_public_config",
]





















































































































































































