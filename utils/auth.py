# utils/auth.py
from __future__ import annotations
import os, re, logging
from typing import Optional, Set, List
from fastapi import HTTPException, Header, Request

logger = logging.getLogger("algogpt.auth")

_TOKENS: Set[str] = set()
_PUBLIC_PATHS: Set[str] = set()
_PUBLIC_PREFIXES: List[str] = []

# -------- helpers --------
def _truthy(v: Optional[str]) -> bool:
    return (v or "").strip().lower() in {"1", "true", "yes", "on"}

def _normalize_path(p: str) -> str:
    if not p:
        return "/"
    p = p.strip()
    if not p.startswith("/"):
        p = "/" + p
    if len(p) > 1 and p.endswith("/"):
        p = p[:-1]
    return p

# -------- loaders --------
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

    # unique + non-empty
    out: Set[str] = set()
    for t in (x.strip() for x in toks):
        if t:
            out.add(t)
    return out

def _read_public_from_env() -> None:
    """Load public allowlist (exact paths + prefixes) from ENV."""
    global _PUBLIC_PATHS, _PUBLIC_PREFIXES
    if _truthy(os.getenv("SECURITY_PUBLIC_STATUS")):
        paths_raw = os.getenv("SECURITY_PUBLIC_PATHS", "")
        prefs_raw = os.getenv("SECURITY_PUBLIC_PREFIXES", "")

        _PUBLIC_PATHS = {_normalize_path(p) for p in paths_raw.split(",") if p.strip()}
        _PUBLIC_PREFIXES = [_normalize_path(p) for p in prefs_raw.split(",") if p.strip()]
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

# -------- getters --------
def get_loaded_tokens(mask: bool = True):
    if mask:
        return [f"{t[:3]}***{t[-2:]}" if len(t) > 5 else "***" for t in sorted(_TOKENS)]
    return sorted(_TOKENS)

def get_public_paths():
    return {"paths": sorted(_PUBLIC_PATHS), "prefixes": list(_PUBLIC_PREFIXES)}

def _is_public(path: str) -> bool:
    p = _normalize_path(path)
    if p in _PUBLIC_PATHS:
        return True
    return any(p.startswith(pref) for pref in _PUBLIC_PREFIXES)

# -------- dependency --------
async def require_api_key(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None),
):
    # allow public paths (opt-in by env)
    if _is_public(request.url.path):
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
















































































































































































