# utils/auth.py
from __future__ import annotations
import os, re, logging
from typing import Optional, Set, List
from fastapi import HTTPException, Header, Request

logger = logging.getLogger("algogpt.auth")

_TOKENS: Set[str] = set()
_PUBLIC_PATHS: Set[str] = set()
_PUBLIC_PREFIXES: List[str] = []

def _read_tokens_from_env() -> Set[str]:
    toks: list[str] = []
    env = os.getenv("API_TOKENS", "")
    if env:
        toks += re.split(r"[,\s]+", env.strip())
    fp = os.getenv("API_TOKENS_FILE")
    if fp and os.path.isfile(fp):
        try:
            with open(fp, "r", encoding="utf-8") as fh:
                toks += [ln.strip() for ln in fh if ln.strip()]
        except Exception as e:
            logger.warning("auth: failed reading API_TOKENS_FILE %s: %s", fp, e)
    return {t for t in (x.strip() for x in toks) if t}

def _read_public_from_env() -> None:
    global _PUBLIC_PATHS, _PUBLIC_PREFIXES
    if os.getenv("SECURITY_PUBLIC_STATUS", "0") == "1":
        paths = os.getenv("SECURITY_PUBLIC_PATHS", "")
        _PUBLIC_PATHS = {p.strip() for p in paths.split(",") if p.strip()}
        prefs = os.getenv("SECURITY_PUBLIC_PREFIXES", "")
        _PUBLIC_PREFIXES = [p.strip() for p in prefs.split(",") if p.strip()]
    else:
        _PUBLIC_PATHS = set()
        _PUBLIC_PREFIXES = []

def refresh_tokens_from_env() -> None:
    """Load tokens + public allowlist from ENV/files. Call on startup."""
    global _TOKENS
    _TOKENS = _read_tokens_from_env()
    _read_public_from_env()
    logger.info(
        "auth: loaded %d token(s). public_paths=%s prefixes=%s",
        len(_TOKENS), sorted(_PUBLIC_PATHS), _PUBLIC_PREFIXES
    )

# load on import (app startup)
refresh_tokens_from_env()

def get_loaded_tokens(mask: bool = True):
    if mask:
        return [f"{t[:3]}***{t[-2:]}" if len(t) > 5 else "***" for t in sorted(_TOKENS)]
    return sorted(_TOKENS)

def get_public_paths():
    return {"paths": sorted(_PUBLIC_PATHS), "prefixes": list(_PUBLIC_PREFIXES)}

def _is_public(path: str) -> bool:
    if path in _PUBLIC_PATHS:
        return True
    return any(path.startswith(pref) for pref in _PUBLIC_PREFIXES)

async def require_api_key(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None),
):
    # allow public paths (opt-in by env)
    path = request.url.path
    if _is_public(path):
        return

    token: Optional[str] = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(None, 1)[1].strip()
    if not token and x_api_key:
        token = x_api_key.strip()
    if not token:
        token = request.query_params.get("api_key")

    if token and token in _TOKENS:
        return

    raise HTTPException(status_code=401, detail="Invalid API key")















































































































































































