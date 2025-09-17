# utils/auth.py
from __future__ import annotations
import os
import time
import logging
from typing import Iterable, List, Optional, Set, Dict

from fastapi import Request, HTTPException, Depends

_log = logging.getLogger("algogpt.auth")

# === טעינת טוקנים ===
_TOKENS: Set[str] = set()
_TOKENS_MASKED: List[str] = []
_TOKENS_LAST_REFRESH_TS = 0.0

def _truthy(val: str | None) -> bool:
    return str(val or "").strip().lower() in ("1", "true", "yes", "on")

def _split_multi(s: str | None) -> List[str]:
    import re
    return [x for x in re.split(r"[,\n\r\t ]+", (s or "").strip()) if x]

def _mask(tok: str) -> str:
    if len(tok) <= 6:
        return tok
    return f"{tok[:2]}…{tok[-2:]}"

def refresh_tokens() -> Dict[str, int]:
    """טוען מחדש טוקנים מה-ENV/קובץ. מחזיר מונה לפי מקור."""
    global _TOKENS, _TOKENS_MASKED, _TOKENS_LAST_REFRESH_TS
    sources = {"env_multi": 0, "env_single": 0, "file_tokens": 0}
    toks: Set[str] = set()

    # ENV: API_TOKENS (רב ערכי)
    for t in _split_multi(os.getenv("API_TOKENS")):
        toks.add(t.strip())
        sources["env_multi"] += 1

    # ENV: API_TOKEN (בודד)
    t_single = os.getenv("API_TOKEN", "").strip()
    if t_single:
        toks.add(t_single)
        sources["env_single"] += 1

    # FILE: TOKENS_FILE (ברירת מחדל /app/tokens.txt)
    path = os.getenv("TOKENS_FILE", "/app/tokens.txt").strip()
    try:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    tok = line.strip()
                    if tok:
                        toks.add(tok)
                        sources["file_tokens"] += 1
    except Exception as e:
        _log.warning({"event": "auth.read_tokens_file_failed", "file": path, "error": str(e)})

    _TOKENS = toks
    _TOKENS_MASKED = [_mask(t) for t in toks]
    _TOKENS_LAST_REFRESH_TS = time.time()
    _log.info({"event": "auth.tokens_refreshed", "count": len(_TOKENS), "sources": sources})
    return sources

# ריענון ראשון בזמן ייבוא
try:
    refresh_tokens()
except Exception:
    pass

def get_loaded_tokens(mask: bool = True) -> List[str]:
    return list(_TOKENS_MASKED if mask else _TOKENS)

def get_public_paths() -> Dict[str, Iterable[str]]:
    paths = _split_multi(os.getenv("SECURITY_PUBLIC_PATHS"))
    prefixes = _split_multi(os.getenv("SECURITY_PUBLIC_PREFIXES"))
    return {"paths": paths, "prefixes": prefixes}

def allow_all() -> bool:
    return _truthy(os.getenv("SECURITY_ALLOW_ALL"))

# === חילוץ טוקן מהבקשה ===
def extract_token(request: Request, auth_header: Optional[str] = None, x_api_key: Optional[str] = None) -> Optional[str]:
    # העדיפות: X-API-Key > Authorization: Bearer > query ?api_key=
    if x_api_key:
        return x_api_key.strip()
    a = (auth_header or "").strip()
    if a.lower().startswith("bearer "):
        return a.split(" ", 1)[1].strip()
    q = request.query_params.get("api_key")
    if q:
        return q.strip()
    return None

def token_matches(token: Optional[str]) -> bool:
    if allow_all():
        return True
    if not token:
        return False
    return token in _TOKENS

# === FastAPI dependency ===
async def _require_api_key_impl(request: Request) -> str:
    if allow_all():
        # מצב פתוח לגמרי (למשל בסביבות dev)
        return "ALLOW_ALL"
    a_hdr = request.headers.get("authorization") or request.headers.get("Authorization")
    x_hdr = request.headers.get("x-api-key") or request.headers.get("X-API-Key")
    tok = extract_token(request, a_hdr, x_hdr)
    if not token_matches(tok):
        raise HTTPException(status_code=401, detail="Invalid API key")
    return tok or ""

def require_api_key(dep: Request = Depends()):
    # עטיפה נוחה ל-Depends
    return Depends(_require_api_key_impl)

# תואם לחתימה ששימשה ב-routes/executor וכו'
def require_api_key_sync(request: Request) -> str:
    if allow_all():
        return "ALLOW_ALL"
    a_hdr = request.headers.get("authorization") or request.headers.get("Authorization")
    x_hdr = request.headers.get("x-api-key") or request.headers.get("X-API-Key")
    tok = extract_token(request, a_hdr, x_hdr)
    if not token_matches(tok):
        raise HTTPException(status_code=401, detail="Invalid API key")
    return tok or ""

















































































































































































