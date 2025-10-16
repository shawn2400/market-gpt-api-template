# utils/auth.py
from __future__ import annotations
import os
import logging
from typing import List, Optional, Dict, Any
from fastapi import Header, HTTPException, Request, status

logger = logging.getLogger("algogpt.auth")

def _coerce_bool(val: Optional[str]) -> bool:
    return str(val or "").strip().lower() in ("1", "true", "yes", "on", "y")

def _split_multi(s: str) -> List[str]:
    import re
    return [x for x in re.split(r"[,\s]+", (s or "").strip()) if x]

def _mask(tok: str) -> str:
    if not tok: return ""
    if len(tok) <= 4: return tok[0] + "…" + tok[-1]
    return tok[:2] + "…" + tok[-2:]

_TOKENS: List[str] = []
_ALLOW_ALL: bool = False

def _extend_with_api_tokens(toks: List[str]) -> List[str]:
    for k in ("AUTH_TOKENS", "API_TOKENS", "ALGOGPT_API_TOKENS", "ALGOGPT_TOKENS"):
        v = os.getenv(k, "")
        if v.strip():
            toks.extend(_split_multi(v))
    for k in ("PRIMARY_API_TOKEN","API_BEARER_TOKEN","API_BEARER","ALGOGPT_API_TOKEN","ALGOGPT_TOKEN","API_TOKEN","TOKEN"):
        v = os.getenv(k, "").strip()
        if v:
            toks.append(v)
    for file_env in ("AUTH_TOKENS_FILE", "API_TOKENS_FILE"):
        path = os.getenv(file_env, "").strip()
        if not path: continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    t = line.strip()
                    if t: toks.append(t)
        except Exception as e:
            logger.warning({"event":"auth.tokens_file_read_failed","file":path,"error":str(e)})
    toks = [t for t in toks if t]
    return list(dict.fromkeys(toks))

def load_tokens_from_env() -> List[str]:
    toks: List[str] = []
    toks = _extend_with_api_tokens(toks)
    return toks

def refresh_tokens_from_env() -> Dict[str, Any]:
    global _TOKENS, _ALLOW_ALL
    _TOKENS = load_tokens_from_env()
    _ALLOW_ALL = _coerce_bool(os.getenv("ALLOW_ALL", os.getenv("AUTH_ALLOW_ALL", "0")))
    logger.info({"event":"auth.tokens_loaded","allow_all":_ALLOW_ALL,"count":len(_TOKENS),"tokens":[_mask(t) for t in _TOKENS]})
    return {"ok": True, "count": len(_TOKENS), "allow_all": _ALLOW_ALL}

def refresh_tokens() -> Dict[str, Any]:
    return refresh_tokens_from_env()

refresh_tokens_from_env()

def get_loaded_tokens(mask: bool = True) -> List[str]:
    return [_mask(t) for t in _TOKENS] if mask else list(_TOKENS)

def allow_all() -> bool:
    return _ALLOW_ALL

def _extract_bearer_from_auth_header(h: Optional[str]) -> Optional[str]:
    if not h: return None
    parts = h.strip().split(None, 1)
    if len(parts) == 2 and parts[0].lower() in ("bearer", "token", "jwt"):
        return parts[1].strip()
    if len(parts) == 1 and parts[0]:
        return parts[0].strip()
    return None

def extract_token(request: Request, auth_header: Optional[str], x_api_key: Optional[str]) -> Optional[str]:
    if x_api_key:
        return x_api_key.strip()
    tok = _extract_bearer_from_auth_header(auth_header or "")
    if tok:
        return tok
    try:
        qtok = request.query_params.get("token")
        if qtok:
            return qtok.strip()
    except Exception:
        pass
    return None

def token_matches(token: Optional[str]) -> bool:
    if allow_all(): return True
    if not token: return False
    return token in _TOKENS

def require_bearer_token(
    Authorization: Optional[str] = Header(default=None),
    X_API_Key: Optional[str] = Header(default=None, alias="X-API-Key"),
):
    tok = X_API_Key or _extract_bearer_from_auth_header(Authorization)
    if not token_matches(tok):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    return tok

require_api_key = require_bearer_token

def _split_env(s: str) -> List[str]:
    return [x for x in _split_multi(s)]

def get_public_paths() -> Dict[str, Any]:
    paths = set(_split_env(os.getenv("SECURITY_PUBLIC_PATHS", "")))
    prefixes = set(_split_env(os.getenv("SECURITY_PUBLIC_PREFIXES", "")))
    return {"paths": sorted(paths), "prefixes": sorted(prefixes)}

def _is_public(path: str) -> bool:
    cfg = get_public_paths()
    paths = set(cfg["paths"])
    prefixes = tuple(cfg["prefixes"])
    always = {"/", "/health", "/readyz", "/status/ping", "/debug/health",
              "/metrics", "/metrics-json", "/openapi.json", "/docs", "/redoc"}
    if path in always or path in paths:
        return True
    return any(path.startswith(p) for p in prefixes)

async def validate_token(request: Request, call_next):
    try:
        path = request.url.path
        if _is_public(path):
            return await call_next(request)

        if not _TOKENS and not _ALLOW_ALL:
            return await call_next(request)

        tok = request.headers.get("X-API-Key") or _extract_bearer_from_auth_header(request.headers.get("Authorization"))
        if not token_matches(tok):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

        return await call_next(request)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("validate_token: middleware call_next failed for %s: %s", request.url.path, e)
        try:
            return await call_next(request)
        except Exception:
            raise HTTPException(status_code=500, detail="middleware_error")































































































































































































