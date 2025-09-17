# /app/utils/auth.py
from __future__ import annotations

import os
import re
import time
import logging
import pathlib
from typing import Optional, List, Dict

from fastapi import Request, Header, HTTPException

log = logging.getLogger("algogpt.auth")


# ========== Helpers ==========

def _b(v: object) -> bool:
    return str(v or "").strip().lower() in ("1", "true", "yes", "on")


def _split_tokens(s: str) -> List[str]:
    if not s:
        return []
    parts = re.split(r"[,\s]+", str(s).strip())
    return [p.strip() for p in parts if p.strip()]


def _read_file_lines(p: str) -> List[str]:
    try:
        if not p:
            return []
        path = pathlib.Path(p)
        if not path.exists():
            log.warning({"event": "tokens_file_missing", "path": str(p)})
            return []
        vals: List[str] = []
        for ln in path.read_text(encoding="utf-8").splitlines():
            t = ln.strip()
            if t and not t.startswith("#"):
                vals.append(t)
        return vals
    except Exception as e:
        log.warning({"event": "tokens_file_read_failed", "path": p, "error": str(e)})
        return []


# ========== State ==========

_TOKENS: set[str] = set()
_T_AT: float = 0.0
_TTL: float = float(os.getenv("AUTH_TOKENS_TTL", "60") or 60)

_ALLOW_ALL = _b(os.getenv("SECURITY_ALLOW_ALL", os.getenv("AUTH_ALLOW_ALL", "0")))
_PUB_STATUS = _b(os.getenv("SECURITY_PUBLIC_STATUS", "1"))
_PUB_PATHS_CFG = {x for x in re.split(r"[,\s]+", os.getenv("SECURITY_PUBLIC_PATHS", "")) if x}
_PUB_PREFIXES_CFG = {x for x in re.split(r"[,\s]+", os.getenv("SECURITY_PUBLIC_PREFIXES", "")) if x}

_DEFAULT_PUBLIC_PATHS = {
    "/", "/openapi.json", "/health", "/healthz", "/readyz",
    "/docs", "/redoc",
    "/telegram/webhook", "/telegram/callback", "/telegram/ping",
    "/provider/cryptopanic/webhook",
    "/status/ping", "/status/ws", "/status/executor", "/status/all",
    "/status/auth",
    "/debug/health",
    "/debug/env", "/debug/refresh-auth",
    "/debug/auth", "/_debug/auth",
    "/executor/status",
}
_DEFAULT_PUBLIC_PREFIXES = {"/price", "/static/", "/risk"}


# ========== Loading / Refresh ==========

def _gather_sources() -> Dict[str, List[str]]:
    env_multi: List[str] = []
    for key in ("API_TOKENS", "ALGOGPT_TOKENS"):
        env_multi += _split_tokens(os.getenv(key, ""))

    env_single: List[str] = []
    for key in ("API_BEARER_TOKEN", "API_KEY", "AUTH_TOKEN"):
        v = (os.getenv(key) or "").strip()
        if v:
            env_single.append(v)

    file_tokens = _read_file_lines(os.getenv("API_TOKENS_FILE", ""))
    return {"env_multi": env_multi, "env_single": env_single, "file_tokens": file_tokens}


def _fresh() -> None:
    """Refresh tokens set according to TTL."""
    global _T_AT, _TOKENS
    now = time.time()
    if _TOKENS and (now - _T_AT) < _TTL:
        return
    src = _gather_sources()
    combined = set(
        t.strip()
        for t in (src["env_multi"] + src["env_single"] + src["file_tokens"])
        if t and t.strip()
    )
    _TOKENS = combined
    _T_AT = now
    log.info(
        {
            "event": "auth.tokens_refreshed",
            "count": len(_TOKENS),
            "sources": {k: len(v) for k, v in src.items()},
        }
    )


def refresh_tokens_from_env() -> List[str]:
    """Force-refresh and return full token list (unmasked)."""
    global _T_AT
    _T_AT = 0.0
    _fresh()
    return sorted(_TOKENS)


def allow_all() -> bool:
    return _ALLOW_ALL


def get_loaded_tokens(mask: bool = True) -> List[str]:
    _fresh()
    arr = sorted(_TOKENS)
    if not mask:
        return arr
    return [t[:2] + "…" + t[-2:] if len(t) > 4 else "***" for t in arr]


def is_token_valid(token: Optional[str]) -> bool:
    if not token:
        return False
    _fresh()
    return token in _TOKENS


def get_public_paths() -> Dict[str, List[str]]:
    paths = set(_DEFAULT_PUBLIC_PATHS) if _PUB_STATUS else set()
    paths |= _PUB_PATHS_CFG
    prefixes = set(_DEFAULT_PUBLIC_PREFIXES) if _PUB_STATUS else set()
    prefixes |= _PUB_PREFIXES_CFG
    log.debug(
        {"event": "get_public_paths", "public_paths": sorted(paths), "public_prefixes": sorted(prefixes)}
    )
    return {"paths": sorted(paths), "prefixes": sorted(prefixes)}


# ========== Extraction ==========

_QUERY_KEYS = ("api_key", "apikey", "apiKey", "token", "key")


def _from_auth_header(authorization: Optional[str]) -> Optional[str]:
    """Extract bearer / token value out of Authorization header value (case-insensitive)."""
    if not authorization or not isinstance(authorization, str):
        return None
    s = authorization.strip()
    if not s:
        return None

    m = re.match(r"^\s*Bearer\s+(.+)\s*$", s, re.IGNORECASE)
    if m:
        return m.group(1).strip().strip('"').strip("'")

    m = re.match(r"^\s*Token\s+(.+)\s*$", s, re.IGNORECASE)
    if m:
        return m.group(1).strip().strip('"').strip("'")

    # Fallback: raw value
    return s.strip().strip('"').strip("'")


def extract_token(
    request: Request,
    authorization: Optional[str] = None,
    x_api_key: Optional[str] = None,
) -> Optional[str]:
    """Extract token from: query-param / header X-API-Key / Authorization / raw headers fallback."""
    q = request.query_params
    for k in _QUERY_KEYS:
        if k in q and q[k]:
            return str(q[k]).strip().strip('"').strip("'")

    if x_api_key and isinstance(x_api_key, str):
        return x_api_key.strip().strip('"').strip("'")

    t = _from_auth_header(authorization)
    if t:
        return t

    # Fallback to raw headers (case variants)
    ah = request.headers.get("authorization") or request.headers.get("Authorization")
    if ah:
        t = _from_auth_header(ah)
        if t:
            return t

    xh = request.headers.get("x-api-key") or request.headers.get("X-API-Key")
    if xh:
        return xh.strip().strip('"').strip("'")

    return None


# ========== FastAPI Dependency ==========

def require_api_key(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None),
) -> str:
    """
    FastAPI dependency that enforces API key auth.
    Accepts: query (?api_key=), header X-API-Key, or Authorization: Bearer/Token.
    """
    if allow_all():
        return "public"

    token = extract_token(request, authorization, x_api_key)
    if not is_token_valid(token):
        raise HTTPException(status_code=401, detail="Invalid API key")
    return token or ""















































































































































































