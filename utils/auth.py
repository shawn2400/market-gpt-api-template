# utils/auth.py  — clean Pydantic-free auth helpers for FastAPI
from __future__ import annotations
import os, re, time, logging, pathlib
from typing import Optional, List, Dict, Set
from fastapi import Request, Header, HTTPException

log = logging.getLogger("algogpt.auth")

# ───────────────────────── helpers ─────────────────────────
def _b(v) -> bool:
    return str(v or "").strip().lower() in ("1", "true", "yes", "on")

def _split_tokens(s: str) -> List[str]:
    out: List[str] = []
    for part in re.split(r"[,\s]+", (s or "").strip()):
        p = part.strip()
        if p:
            out.append(p)
    return out

def _mask(tok: str) -> str:
    if not tok:
        return ""
    if len(tok) <= 4:
        return "*" * len(tok)
    return f"{tok[:2]}…{tok[-2:]}"

# ───────────────────────── state ─────────────────────────
_TOKENS: Set[str] = set()
_T_AT: float = 0.0  # last refresh ts

# env config (evaluated in _fresh() so hot-reload via TTL עובד)
def _ttl() -> float:
    try:
        return float(os.getenv("AUTH_TOKENS_TTL", "60"))
    except Exception:
        return 60.0

# public paths config (rebuilt in _fresh)
_PUB_STATUS: bool = False
_PUB_PATHS: Set[str] = set()
_PUB_PREFIXES: Set[str] = set()
_ALLOW_ALL: bool = False

def _effective_public_defaults() -> tuple[Set[str], Set[str]]:
    paths = {
        "/", "/openapi.json", "/docs", "/redoc",
        "/health", "/healthz", "/readyz",
        "/status/ping", "/status/ws", "/status/executor", "/status/all", "/status/auth",
        "/_debug/auth", "/debug/auth", "/debug/health",
        "/provider/cryptopanic/webhook",
        "/telegram/webhook", "/telegram/callback", "/telegram/ping",
    }
    prefixes = {"/price", "/static/", "/risk"}
    # metrics public toggled via METRICS_PUBLIC
    if _b(os.getenv("METRICS_PUBLIC", "1")):
        paths.add("/metrics")
    return paths, prefixes

def _fresh() -> None:
    global _T_AT, _TOKENS, _ALLOW_ALL, _PUB_STATUS, _PUBLISH_LOG_DONE
    global _PUB_PATHS, _PUB_PREFIXES

    now = time.time()
    if now - _T_AT < _ttl():
        return

    # 1) tokens
    toks: Set[str] = set()
    env_tokens = _split_tokens(os.getenv("API_TOKENS", ""))
    toks.update(env_tokens)

    token_file = (os.getenv("API_TOKENS_FILE") or "").strip()
    if token_file:
        p = pathlib.Path(token_file)
        if p.exists():
            try:
                for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
                    s = line.strip()
                    if not s or s.startswith("#"):
                        continue
                    toks.add(s)
            except Exception as e:
                log.warning({"event": "tokens.file_read_failed", "file": token_file, "error": str(e)})

    # 2) flags + public
    _ALLOW_ALL = _b(os.getenv("SECURITY_ALLOW_ALL", "0"))
    _PUB_STATUS = _b(os.getenv("SECURITY_PUBLIC_STATUS", "1"))

    def _split_multi(s: str) -> List[str]:
        return [x for x in re.split(r"[,\s]+", (s or "").strip()) if x]

    defpaths, defprefixes = _effective_public_defaults()
    _PUB_PATHS = set(defpaths) if _PUB_STATUS else set()
    _PUB_PREFIXES = set(defprefixes) if _PUB_STATUS else set()

    cfg_paths = set(_split_multi(os.getenv("SECURITY_PUBLIC_PATHS", "")))
    cfg_pfx   = set(_split_multi(os.getenv("SECURITY_PUBLIC_PREFIXES", "")))
    _PUB_PATHS |= cfg_paths
    _PUB_PREFIXES |= cfg_pfx

    # 3) commit
    _TOKENS = toks
    _T_AT = now

    log.info({"event": "auth.tokens_refreshed", "count": len(_TOKENS)})
    log.info({
        "event": "public_paths_config",
        "public_status": _PUB_STATUS,
        "paths": sorted(_PUB_PATHS),
        "prefixes": sorted(_PUB_PREFIXES),
        "allow_all": _ALLOW_ALL,
    })

# ───────────────── introspection ─────────────────
def get_loaded_tokens(mask: bool = True) -> List[str]:
    _fresh()
    arr = sorted(_TOKENS)
    return [ _mask(t) if mask else t for t in arr ]

def get_public_paths() -> Dict[str, List[str]]:
    _fresh()
    return {"paths": sorted(_PUB_PATHS), "prefixes": sorted(_PUB_PREFIXES)}

def get_public_config() -> Dict[str, object]:
    _fresh()
    return {"allow_all": _ALLOW_ALL, **get_public_paths()}

# ───────────────── token extraction/check ─────────────────
def extract_token(request: Request,
                  authorization_header: Optional[str] = None,
                  x_api_key_header: Optional[str] = None) -> Optional[str]:
    # precedence: header Bearer -> X-API-Key -> query (?api_key|key|token|access_token)
    if authorization_header:
        a = str(authorization_header).strip()
        if a.lower().startswith("bearer "):
            return a.split(" ", 1)[1].strip()
    if x_api_key_header:
        x = str(x_api_key_header).strip()
        if x:
            return x
    q = request.query_params
    for k in ("api_key", "key", "token", "access_token"):
        if k in q and q[k]:
            return q[k]
    return None

def token_matches(tok: Optional[str]) -> bool:
    _fresh()
    ok = bool(tok and tok in _TOKENS)
    log.debug({"event": "token_check", "input": _mask(tok or ""), "tokens_loaded": [ _mask(t) for t in sorted(_TOKENS) ]})
    return ok

# ───────────────── FastAPI dependency ─────────────────
async def require_api_key(request: Request,
                          authorization: Optional[str] = Header(None),
                          x_api_key: Optional[str] = Header(None)) -> bool:
    _fresh()
    # 1) CORS preflight
    if request.method.upper() == "OPTIONS":
        return True

    path = request.url.path

    # 2) public exact / prefixes
    if path in _PUB_PATHS or any(path.startswith(p) for p in _PUB_PREFIXES):
        return True

    # 3) allow_all mode
    if _ALLOW_ALL:
        return True

    # 4) token check
    tok = extract_token(request, authorization, x_api_key)
    if not token_matches(tok):
        raise HTTPException(status_code=401, detail="Invalid API key")
    return True

# convenience
def allow_all() -> bool:
    _fresh()
    return _ALLOW_ALL






















































































































































































