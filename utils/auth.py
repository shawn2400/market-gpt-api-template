# utils/auth.py
from __future__ import annotations
import os
import logging
from typing import List, Optional, Dict, Any

from fastapi import Header, HTTPException, Request

logger = logging.getLogger("algogpt.auth")

# ==============================
# Helpers
# ==============================
def _coerce_bool(val: Optional[str]) -> bool:
    return str(val or "").strip().lower() in ("1", "true", "yes", "on", "y")

def _split_multi(s: str) -> List[str]:
    import re
    return [x for x in re.split(r"[,\s]+", (s or "").strip()) if x]

def _mask(tok: str) -> str:
    if not tok:
        return ""
    if len(tok) <= 4:
        return tok[0] + "…" + tok[-1]
    return tok[:2] + "…" + tok[-2:]

# ==============================
# Load tokens from ENV (canonical + fallbacks)
# ==============================
_CANON_ENV = "AUTH_TOKENS"
_DEPRECATED_MULTI_ENVS = ("ALGOGPT_TOKENS", "API_TOKENS", "ALGOGPT_API_TOKENS")
_SINGLE_FALLBACKS = (
    "PRIMARY_API_TOKEN", "API_BEARER_TOKEN", "API_TOKEN", "ALGOGPT_API_TOKEN", "ALGOGPT_TOKEN", "TOKEN"
)
_FILE_ENVS = ("AUTH_TOKENS_FILE", "API_TOKENS_FILE")
_SENTINELS = {"PUT_REAL_API_TOKEN", "CHANGE_ME", "REPLACE_ME", "YOUR_TOKEN_HERE", "TOKEN"}

_TOKENS: List[str] = []
_ALLOW_ALL: bool = False

def _extend_with_api_tokens(toks: List[str]) -> List[str]:
    # Canonical
    canon = os.getenv(_CANON_ENV, "")
    if canon.strip():
        toks.extend(_split_multi(canon))

    # Deprecated (multi) — add + warn
    for k in _DEPRECATED_MULTI_ENVS:
        v = os.getenv(k, "")
        if v.strip():
            logger.warning("AUTH deprecation: %s is set; please move to %s only.", k, _CANON_ENV)
            toks.extend(_split_multi(v))

    # Single-value fallbacks
    for k in _SINGLE_FALLBACKS:
        v = os.getenv(k, "").strip()
        if v:
            toks.append(v)

    # From files (one token per line)
    for file_env in _FILE_ENVS:
        path = os.getenv(file_env, "").strip()
        if not path:
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    t = line.strip()
                    if t:
                        toks.append(t)
        except Exception as e:
            logger.warning({"event": "auth.tokens_file_read_failed", "file": path, "error": str(e)})

    # Cleanup: drop empties/sentinels, keep order & uniqueness
    cleaned: List[str] = []
    seen: set[str] = set()
    for t in toks:
        tt = t.strip()
        if not tt or tt in _SENTINELS or tt in seen:
            continue
        cleaned.append(tt)
        seen.add(tt)
    return cleaned

def load_tokens_from_env() -> List[str]:
    toks: List[str] = []
    toks = _extend_with_api_tokens(toks)
    return toks

def refresh_tokens_from_env() -> Dict[str, Any]:
    """Reload tokens + allow_all from environment."""
    global _TOKENS, _ALLOW_ALL
    _TOKENS = load_tokens_from_env()
    # respect both ALLOW_ALL and AUTH_ALLOW_ALL
    _ALLOW_ALL = _coerce_bool(os.getenv("ALLOW_ALL", os.getenv("AUTH_ALLOW_ALL", "0")))
    logger.info({
        "event": "auth.tokens_loaded",
        "allow_all": _ALLOW_ALL,
        "count": len(_TOKENS),
        "tokens": [_mask(t) for t in _TOKENS],
    })
    return {"ok": True, "count": len(_TOKENS), "allow_all": _ALLOW_ALL}

# Public alias (יש ראוטרים שמחפשים)
def refresh_tokens() -> Dict[str, Any]:
    return refresh_tokens_from_env()

# Initial load
refresh_tokens_from_env()

def get_loaded_tokens(mask: bool = True) -> List[str]:
    return [_mask(t) for t in _TOKENS] if mask else list(_TOKENS)

def allow_all() -> bool:
    return _ALLOW_ALL

# ==============================
# Request token extraction
# ==============================
def _extract_bearer_from_auth_header(h: Optional[str]) -> Optional[str]:
    if not h:
        return None
    parts = h.strip().split(None, 1)
    if len(parts) == 2 and parts[0].lower() in ("bearer", "token", "jwt"):
        return parts[1].strip()
    if len(parts) == 1 and parts[0]:  # token without "Bearer"
        return parts[0].strip()
    return None

_QUERY_KEYS = ("api_key", "apikey", "token", "key", "auth")

def extract_token(request: Request, auth_header: Optional[str], x_api_key: Optional[str]) -> Optional[str]:
    # Canonical: X-API-Key
    if x_api_key:
        return x_api_key.strip()
    # Back-compat: Authorization: Bearer …
    tok = _extract_bearer_from_auth_header(auth_header or "")
    if tok:
        return tok
    # Query fallbacks
    try:
        for k in _QUERY_KEYS:
            qtok = request.query_params.get(k)
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

# ==============================
# FastAPI dependencies
# ==============================
async def require_api_key(
    request: Request,
    # FastAPI ממפה X-API-Key → x_api_key (אין צורך convert_underscores פה)
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    Authorization: Optional[str] = Header(None),
):
    tok = extract_token(request, Authorization, x_api_key)
    if not token_matches(tok):
        raise HTTPException(status_code=401, detail="Invalid API key")
    return tok

# תאימות: יש קוד שקורא לשם הזה
require_bearer_token = require_api_key

# ==============================
# Public paths helpers (ל- /status/auth)
# ==============================
def _split_env(s: str) -> List[str]:
    return [x for x in _split_multi(s)]

def get_public_paths() -> Dict[str, Any]:
    paths = set(_split_env(os.getenv("SECURITY_PUBLIC_PATHS", "")))
    prefixes = set(_split_env(os.getenv("SECURITY_PUBLIC_PREFIXES", "")))
    return {"paths": sorted(paths), "prefixes": sorted(prefixes)}



























































































































































































