from __future__ import annotations
import os, re, time, logging, pathlib
from typing import Optional, List, Dict, Any
from fastapi import Request, Header
from fastapi.responses import JSONResponse

log = logging.getLogger("algogpt.auth")

def _b(v: object) -> bool:
    return str(v or "").strip().lower() in ("1", "true", "yes", "on")

def _split_tokens(s: str) -> List[str]:
    return [t.strip() for t in re.split(r"[,\s]+", (s or "").strip()) if t.strip()]

def _read_file_lines(p: str) -> List[str]:
    try:
        path = pathlib.Path(p)
        if not path.exists():
            log.warning({"event": "tokens_file_missing", "path": p})
            return []
        content = path.read_text(encoding="utf-8")
        log.debug({"event": "tokens_file_read", "path": p, "content": content})
        return [ln.strip() for ln in content.splitlines() if ln.strip()]
    except Exception as e:
        log.warning({"event": "tokens_file_read_failed", "path": p, "error": str(e)})
        return []

_TOKENS: set[str] = set()
_T_AT: float = 0.0
_TTL: float = float(os.getenv("AUTH_TOKENS_TTL", "60") or 60)
_ALLOW_ALL = _b(os.getenv("SECURITY_ALLOW_ALL", os.getenv("AUTH_ALLOW_ALL", "0")))
_PUB_STATUS = _b(os.getenv("SECURITY_PUBLIC_STATUS", "1"))
_PUB_PATHS_CFG = set(x for x in re.split(r"[,\s]+", os.getenv("SECURITY_PUBLIC_PATHS", "")) if x)
_PUB_PREFIXES_CFG = set(x for x in re.split(r"[,\s]+", os.getenv("SECURITY_PUBLIC_PREFIXES", "")) if x)

_DEFAULT_PUBLIC_PATHS = {
    "/", "/openapi.json", "/health", "/healthz", "/readyz",
    "/docs", "/redoc",
    "/telegram/webhook", "/telegram/callback", "/telegram/ping",
    "/provider/cryptopanic/webhook",
    "/status/ping", "/status/ws", "/status/executor", "/status/all",
    "/status/auth",
    "/debug/health",
    "/debug/auth", "/_debug/auth",
}
_DEFAULT_PUBLIC_PREFIXES = {"/price", "/static/", "/risk"}

def _fresh() -> None:
    global _T_AT, _TOKENS
    now = time.time()
    if now - _T_AT < _TTL and _TOKENS:
        return
    env_tokens = _split_tokens(os.getenv("API_TOKENS", ""))
    file_tokens = _read_file_lines(os.getenv("API_TOKENS_FILE", ""))
    _TOKENS = {t.strip() for t in (env_tokens + file_tokens) if t.strip()}
    _T_AT = now
    log.info({"event": "auth.tokens_refreshed", "count": len(_TOKENS), "tokens": sorted(_TOKENS), "env_tokens": env_tokens, "file_tokens": file_tokens})

def refresh_tokens_from_env() -> List[str]:
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

def get_public_paths() -> Dict[str, List[str]]:
    paths = set(_DEFAULT_PUBLIC_PATHS) if _PUB_STATUS else set()
    paths |= _PUB_PATHS_CFG
    prefixes = set(_DEFAULT_PUBLIC_PREFIXES) if _PUB_STATUS else set()
    prefixes |= _PUB_PREFIXES_CFG
    log.debug({"event": "get_public_paths", "public_paths": sorted(paths), "public_prefixes": sorted(prefixes)})
    return {"paths": sorted(paths), "prefixes": sorted(prefixes)}

_QUERY_KEYS = ("api_key", "apikey", "apiKey", "token", "key")

def _from_auth_header(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    s = authorization.strip()
    m = re.match(r"^\s*Bearer\s+(.+)\s*$", s, re.IGNORECASE)
    if m:
        return m.group(1).strip().strip('"').strip("'")
    m = re.match(r"^\s*Token\s+(.+)\s*$", s, re.IGNORECASE)
    if m:
        return m.group(1).strip().strip('"').strip("'")
    return s.strip().strip('"').strip("'")

def extract_token(request: Request, authorization: Optional[str] = None, x_api_key: Optional[str] = None) -> Optional[str]:
    q = request.query_params
    for k in _QUERY_KEYS:
        if k in q and q[k]:
            return str(q[k]).strip().strip('"').strip("'")
    if x_api_key:
        return x_api_key.strip().strip('"').strip("'")
    t = _from_auth_header(authorization)
    if t:
        return t
    ah = request.headers.get("authorization") or request.headers.get("Authorization")
    if ah:
        t = _from_auth_header(ah)
        if t:
            return t
    xh = request.headers.get("x-api-key") or request.headers.get("X-API-Key")
    if xh:
        return xh.strip().strip('"').strip("'")
    return None

def token_matches(tok: Optional[str]) -> bool:
    _fresh()
    log.debug({"event": "token_check", "input_token": tok, "tokens_loaded": sorted(_TOKENS)})
    return bool(tok and tok in _TOKENS)

async def require_api_key(request: Request, authorization: Optional[str] = Header(None), x_api_key: Optional[str] = Header(None)) -> bool:
    if request.method.upper() == "OPTIONS":
        log.debug({"event": "auth_skipped", "path": request.url.path, "reason": "OPTIONS_request"})
        return True
    p = request.url.path
    pub = get_public_paths()
    log.debug({"event": "auth_check", "path": p, "public_paths": pub["paths"], "public_prefixes": pub["prefixes"]})
    if p in set(pub["paths"]) or any(p.startswith(pr) for pr in pub["prefixes"]):
        log.debug({"event": "auth_skipped", "path": p, "reason": "public_path"})
        return True
    if allow_all():
        log.debug({"event": "auth_skipped", "path": p, "reason": "allow_all"})
        return True
    tok = extract_token(request, authorization, x_api_key)
    if not token_matches(tok):
        log.debug({"event": "auth_failed", "path": p, "token": tok})
        raise RuntimeError("Unauthorized")
    log.debug({"event": "auth_success", "path": p, "token": tok})
    return True

async def guard_or_401(request: Request) -> Optional[JSONResponse]:
    try:
        await require_api_key(request)
        return None
    except Exception:
        return JSONResponse(status_code=401, content={"detail": "Invalid API key"})




















































































































































































