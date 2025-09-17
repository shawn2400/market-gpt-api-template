from __future__ import annotations
import os, time
from typing import List, Dict, Optional
from fastapi import Request, HTTPException

_TOKENS: List[str] = []
_LAST_LOAD_TS: float = 0.0

def _split_multi(s: str) -> List[str]:
    import re
    return [x for x in re.split(r"[,\n\r\t ]+", (s or "").strip()) if x]

def _mask(tok: str) -> str:
    if not tok:
        return ""
    return tok[:2] + "…" + tok[-2:] if len(tok) > 6 else tok[0] + "…" + tok[-1]

def _load_tokens(force: bool = False) -> None:
    global _TOKENS, _LAST_LOAD_TS
    if not force and _TOKENS:
        return
    toks: List[str] = []
    single = os.getenv("API_TOKEN", "").strip()
    if single:
        toks.append(single)
    toks += _split_multi(os.getenv("API_TOKENS", ""))
    tok_file = os.getenv("TOKENS_FILE", "/app/tokens.txt").strip()
    try:
        if os.path.isfile(tok_file):
            with open(tok_file, "r", encoding="utf-8") as f:
                for line in f:
                    t = line.strip()
                    if t:
                        toks.append(t)
    except Exception:
        pass
    _TOKENS = list(dict.fromkeys(toks))
    _LAST_LOAD_TS = time.time()

def refresh_tokens() -> Dict[str, int]:
    before = len(_TOKENS)
    _load_tokens(force=True)
    return {"count": len(_TOKENS), "was": before}

def get_loaded_tokens(mask: bool = True):
    _load_tokens()
    return [_mask(t) if mask else t for t in _TOKENS]

def allow_all() -> bool:
    return os.getenv("SECURITY_ALLOW_ALL", "0").lower() in ("1", "true", "yes", "on")

def extract_token(request: Request, auth_header: Optional[str], x_api_key: Optional[str]) -> Optional[str]:
    q = request.query_params.get("api_key")
    if q: return q.strip()
    if x_api_key: return x_api_key.strip()
    if auth_header:
        parts = auth_header.strip().split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1].strip()
    return None

def token_matches(token: Optional[str]) -> bool:
    if allow_all():
        return True
    if not token:
        return False
    _load_tokens()
    return token in _TOKENS

def require_api_key(request: Request) -> str:
    if allow_all():
        return "ALLOW_ALL"
    a = request.headers.get("authorization") or request.headers.get("Authorization")
    x = request.headers.get("x-api-key") or request.headers.get("X-API-Key")
    tok = extract_token(request, a, x)
    if not token_matches(tok):
        raise HTTPException(status_code=401, detail="Invalid API key")
    return tok

def get_public_paths():
    return {"paths": [], "prefixes": []}




















































































































































































