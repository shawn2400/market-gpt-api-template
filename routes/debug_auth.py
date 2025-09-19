# routes/debug_auth.py
from __future__ import annotations
import time
from typing import Dict, Any

from fastapi import APIRouter, Request

from utils.config import get_settings, strip_bearer_prefix as _strip
from utils.auth import get_loaded_tokens, token_matches, allow_all

router = APIRouter(tags=["debug"])

def _extract_token(request: Request) -> str | None:
    s = get_settings()
    # headers (לפי סדר ההגדרות בקונפיג)
    for h in s.AUTH_HEADER_CANDIDATES:
        if h in request.headers:
            raw = request.headers.get(h)
            if not raw:
                continue
            tok = _strip(raw)
            if tok:
                return tok
    # query params fallback
    for q in s.AUTH_QUERY_KEYS:
        if q in request.query_params:
            raw = request.query_params.get(q)
            if raw:
                return _strip(raw)
    return None

@router.get("/_debug/auth")
def debug_auth(request: Request) -> Dict[str, Any]:
    s = get_settings()
    auth_hdr = request.headers.get("Authorization")
    x_api_key = request.headers.get("X-API-Key")
    extracted = _extract_token(request)
    return {
        "ok": True,
        "ts": int(time.time()),
        "allow_all": allow_all(),
        "auth_header": auth_hdr,
        "x_api_key": x_api_key,
        "query": dict(request.query_params),
        "extracted_token": extracted,
        "matches": bool(token_matches(extracted)),
        "tokens_loaded": get_loaded_tokens(mask=True),
        "config": {
            "AUTH_ALLOW_ALL": s.AUTH_ALLOW_ALL,
            "AUTH_HEADER_CANDIDATES": s.AUTH_HEADER_CANDIDATES,
            "AUTH_QUERY_KEYS": s.AUTH_QUERY_KEYS,
            "TOKENS_COUNT": len(s.API_TOKENS),
        },
    }

# אליאס נוח: /status/auth
@router.get("/status/auth")
def status_auth(request: Request) -> Dict[str, Any]:
    return debug_auth(request)
