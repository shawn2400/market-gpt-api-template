# utils/auth.py
from __future__ import annotations

import os
import re
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

def _split_multi(s: str) -> List[str]:
    """Split on commas/whitespace/newlines/tabs into a clean list."""
    return [x for x in re.split(r"[,\n\r\t ]+", (s or "").strip()) if x]

def _tokens_ttl_sec() -> float:
    try:
        return float(os.getenv("AUTH_TOKENS_TTL", "60"))
    except Exception:
        return 60.0

# ─────────────────────────
# Public config (from ENV)
# ─────────────────────────
_ALLOW_ALL: bool = False
_PUBLIC_STATUS: bool = False
_PUBLIC_PATHS: Set[str] = set()
_PUBLIC_PREFIXES: List[str] = []

def _read_public_from_env() -> None:
    """Load public paths/prefixes and flags from ENV."""
    global _ALLOW_ALL, _PUBLIC_STATUS, _PUBLIC_PATHS, _PUBLIC_PREFIXES
    _ALLOW_ALL = _b(os.getenv("SECURITY_ALLOW_ALL"))
    _PUBLIC_STATUS = _b(os.getenv("SECURITY_PUBLIC_STATUS"))
    _PUBLIC_PATHS = set(_split_multi(os.getenv("SECURITY_PUBLIC_PATHS", "")))
    _PUBLIC_PREFIXES = _split_multi(os.getenv("SECURITY_PUBLIC_PREFIXES", ""))

def _is_public(path: str) -> bool:
    """Check if a path is public according to ENV."""
    if _ALLOW_ALL:
        return True
    # Always allow status endpoints when SECURITY_PUBLIC_STATUS is on
    if _PUBLIC_STATUS and path in ("/status/ping", "/status/all"):
        return True
    if path in _PUBLIC_PATHS:
        return True
    for pfx in _PUBLIC_PREFIXES:
        if path.startswith(pfx):
            return True
    return False

# ─────────────────────────
# Tokens cache (with TTL)
# ─────────────────────────
_TOKENS: Set[str] = set()
_TOKENS_LOADED_AT: float = 0.0

def _read_tokens_from_env() -> Set[str]:
    toks: Set[str] = set()
    toks.update(_split_multi(os.getenv("API_TOKENS", "")))
    fp = (os.getenv("API_TOKENS_FILE", "") or "").strip()
    if fp and os.path.isfile(fp):
        try:
            with open(fp, "r", encoding="utf-8") as fh:
                for ln in fh:
                    ln = ln.strip()
                    if ln:
                        toks.add(ln)
        except Exception as e:
            logger.warning("auth: failed reading API_TOKENS_FILE %s: %s", fp, e)
    return toks

def refresh_tokens_from_env() -> None:
    """Force-reload tokens & public config from ENV."""
    global _TOKENS, _TOKENS_LOADED_AT
    _read_public_from_env()
    _TOKENS = _read_tokens_from_env()
    _TOKENS_LOADED_AT = time.time()
    logger.info("auth: loaded %d token(s)", len(_TOKENS))

def _ensure_tokens_fresh() -> None:
    if (time.time() - _TOKENS_LOADED_AT) >= _tokens_ttl_sec():
        refresh_tokens_from_env()

# Load once on import
refresh_tokens_from_env()

# ─────────────────────────
# Introspection helpers
# ─────────────────────────
def get_loaded_tokens(mask: bool = True) -> List[str]:
    _ensure_tokens_fresh()
    toks = sorted(_TOKENS)
    if not mask:
        return toks
    return [f"{t[:3]}***{t[-2:]}" if len(t) > 5 else "***" for t in toks]

def get_public_paths() -> Dict[str, Any]:
    _ensure_tokens_fresh()
    return {"paths": sorted(_PUBLIC_PATHS), "prefixes": list(_PUBLIC_PREFIXES)}

# Back-compat for older code/tests
def get_public_config() -> Dict[str, Any]:
    _ensure_tokens_fresh()
    return {
        "allow_all": _ALLOW_ALL,
        "public_status": _PUBLIC_STATUS,
        "paths": sorted(_PUBLIC_PATHS),
        "prefixes": list(_PUBLIC_PREFIXES),
        "tokens_ttl_sec": _tokens_ttl_sec(),
    }

def allow_all() -> bool:
    _ensure_tokens_fresh()
    return _ALLOW_ALL

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

    # Header: Authorization (Bearer <token> or raw token)
    if authorization and authorization.strip():
        a = authorization.strip()
        parts = a.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1].strip()
        return a  # allow raw token

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
    _ensure_tokens_fresh()
    return bool(token and token in _TOKENS)

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
    Honors public paths/prefixes from ENV. Raises 401 if token missing/invalid.
    """
    # Public or preflight
    if request.method == "OPTIONS" or _is_public(request.url.path):
        return True

    token = extract_token(request, authorization, x_api_key)
    if not token:
        raise HTTPException(status_code=401, detail="Missing API token")

    if not token_matches(token):
        raise HTTPException(status_code=401, detail="Invalid API token")

    return True

__all__ = [
    "require_api_key",
    "extract_token", "token_matches",
    "get_loaded_tokens", "get_public_paths", "get_public_config",
    "allow_all", "refresh_tokens_from_env",
]





















































































































































































