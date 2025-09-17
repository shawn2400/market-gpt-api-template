# /app/utils/auth.py
from __future__ import annotations

import os
import re
import time
import hmac
import logging
import pathlib
from typing import Optional, List, Dict, Any

from fastapi import Request
from fastapi.responses import JSONResponse

log = logging.getLogger("algogpt.auth")


# ---------- helpers ----------

def _b(v: object) -> bool:
    """Cast common truthy strings to bool."""
    return str(v or "").strip().lower() in ("1", "true", "yes", "on")


def _split_tokens(s: str) -> List[str]:
    """Split comma/space separated tokens and trim."""
    if not s:
        return []
    parts = re.split(r"[,\s]+", str(s).strip())
    return [p.strip().strip('"').strip("'") for p in parts if p.strip()]


def _read_file_lines(p: str) -> List[str]:
    """Read tokens from a file, one per line, ignoring comments/blank lines."""
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
                vals.append(t.strip().strip('"').strip("'"))
        return vals
    except Exception as e:
        log.warning({"event": "tokens_file_read_failed", "path": p, "error": str(e)})
        return []


# ---------- configuration ----------

_TOKENS: set[str] = set()
_T_AT: float = 0.0
_TTL: float = float(os.getenv("AUTH_TOKENS_TTL", "60") or 60)

_ALLOW_ALL = _b(os.getenv("SECURITY_ALLOW_ALL", os.getenv("AUTH_ALLOW_ALL", "0")))
_PUB_STATUS = _b(os.getenv("SECURITY_PUBLIC_STATUS", "1"))

_PUB_PATHS_CFG = {x for x in re.split(r"[,\s]+", os.getenv("SECURITY_PUBLIC_PATHS", "")) if x}
_PUB_PREFIXES_CFG = {x for x in re.split(r"[,\s]+", os.getenv("SECURITY_PUBLIC_PREFIXES", "")) if x}

_DEFAULT_PUBLIC_PATHS = {
    "/", "/openapi.json",
    "/health", "/healthz", "/readyz",
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


def _gather_sources() -> Dict[str, List[str]]:
    """Collect tokens from env (multi + single) and optional file."""
    env_multi: List[str] = []
    for key in ("API_TOKENS", "ALGOGPT_TOKENS"):
        env_multi += _split_tokens(os.getenv(key, ""))

    env_single: List[str] = []
    for key in ("API_BEARER_TOKEN", "API_KEY", "AUTH_TOKEN"):
        v = (os.getenv(key) or "").strip().strip('"').strip("'")
        if v:
            env_single.append(v)

    file_tokens = _read_file_lines(os.getenv("API_TOKENS_FILE", ""))
    return {"env_multi": env_multi, "env_single": env_single, "file_tokens": file_tokens}


def _fresh() -> None:
    """Refresh tokens set from sources if TTL expired."""
    global _T_AT, _TOKENS
    now = time.time()
    if _TOKENS and (now - _T_AT) < _TTL:
        return
    src = _gather_sources()
    combined = set(t for t in (src["env_multi"] + src["env_single"] + src["file_tokens"]) if t)
    _TOKENS = combined
    _T_AT = now
    log.info({
        "event": "auth.tokens_refreshed",
        "count": len(_TOKENS),
        "sources": {k: len(v) for k, v in src.items()},
        "ttl": _TTL,
    })


# ---------- public API ----------

def refresh_tokens_from_env() -> List[str]:
    """Force refresh and return unmasked tokens (for internal/debug use)."""
    global _T_AT
    _T_AT = 0.0
    _fresh()
    return sorted(_TOKENS)


def allow_all() -> bool:
    return _ALLOW_ALL


def get_loaded_tokens(mask: bool = True) -> List[str]:
    """
    Return loaded tokens.
    NOTE: This is for display/logging. DO NOT use this list for comparisons.
    Use token_matches(token) instead.
    """
    _fresh()
    arr = sorted(_TOKENS)
    if not mask:
        return arr
    return [t[:2] + "…" + t[-2:] if len(t) > 4 else "***" for t in arr]


def get_public_paths() -> Dict[str, List[str]]:
    """Return effective public paths and prefixes (defaults + configured)."""
    paths = set(_DEFAULT_PUBLIC_PATHS) if _PUB_STATUS else set()
    paths |= _PUB_PATHS_CFG
    prefixes = set(_DEFAULT_PUBLIC_PREFIXES) if _PUB_STATUS else set()
    prefixes |= _PUB_PREFIXES_CFG
    log.debug({"event": "get_public_paths", "public_paths": sorted(paths), "public_prefixes": sorted(prefixes)})
    return {"paths": sorted(paths), "prefixes": sorted(prefixes)}


def is_public_path(path: str) -> bool:
    """Check if a path is publicly accessible."""
    if not path:
        return False
    cfg = get_public_paths()
    if path in cfg["paths"]:
        return True
    return any(path.startswith(pfx) for pfx in cfg["prefixes"])


_QUERY_KEYS = ("api_key", "apikey", "apiKey", "token", "key")


def _from_auth_header(authorization: Optional[str]) -> Optional[str]:
    """Extract token from Authorization header value."""
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
    # Fall back to raw value (some clients send just the token)
    return s.strip().strip('"').strip("'")


def extract_token(request: Request, authorization: Optional[str] = None, x_api_key: Optional[str] = None) -> Optional[str]:
    """
    Extract token from (priority):
      1) query param: api_key/apikey/apiKey/token/key
      2) explicit x_api_key param
      3) explicit authorization param
      4) request headers: Authorization
      5) request headers: X-API-Key
    """
    # 1) query
    q = request.query_params
    for k in _QUERY_KEYS:
        if k in q and q[k]:
            return str(q[k]).strip().strip('"').strip("'")

    # 2) explicit X-API-Key param
    if x_api_key and isinstance(x_api_key, str):
        return x_api_key.strip().strip('"').strip("'")

    # 3) explicit Authorization param
    t = _from_auth_header(authorization)
    if t:
        return t

    # 4) headers: Authorization
    ah = request.headers.get("authorization") or request.headers.get("Authorization")
    if ah:
        t = _from_auth_header(ah)
        if t:
            return t

    # 5) headers: X-API-Key
    xh = request.headers.get("x-api-key") or request.headers.get("X-API-Key")
    if xh:
        return xh.strip().strip('"').strip("'")

    return None


def token_matches(token: Optional[str]) -> bool:
    """
    Compare a provided token to the loaded set (constant-time where possible).
    ALWAYS use this for authorization checks (do NOT compare to get_loaded_tokens()).
    """
    if not token:
        return False
    _fresh()
    for t in _TOKENS:
        # hmac.compare_digest avoids timing leaks and handles length differences safely
        if hmac.compare_digest(token, t):
            return True
    return False


def require_token(request: Request, authorization: Optional[str] = None, x_api_key: Optional[str] = None) -> Optional[JSONResponse]:
    """
    Lightweight guard for route handlers:
        resp = require_token(request, authorization, x_api_key)
        if isinstance(resp, JSONResponse): return resp
        # authorized -> continue
    """
    try:
        if allow_all() or is_public_path(request.url.path):
            return None
        tok = extract_token(request, authorization=authorization, x_api_key=x_api_key)
        if tok and token_matches(tok):
            return None
        return JSONResponse({"detail": "Invalid API key"}, status_code=401)
    except Exception as e:
        log.exception({"event": "auth.guard_error", "error": str(e)})
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)


# ---------- debug utilities ----------

def debug_state(request: Request, authorization: Optional[str] = None, x_api_key: Optional[str] = None) -> Dict[str, Any]:
    """
    Helper for /_debug/auth endpoint responses.
    Returns introspection data without leaking full tokens.
    """
    tok = extract_token(request, authorization=authorization, x_api_key=x_api_key)
    ok = token_matches(tok)
    return {
        "ok": True,
        "auth_header": authorization,
        "x_api_key": x_api_key,
        "query": dict(request.query_params),
        "extracted_token": tok,
        "matches": ok,
        "tokens_loaded": get_loaded_tokens(mask=True),
    }















































































































































































