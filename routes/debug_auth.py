# routes/debug_auth.py
from __future__ import annotations
from fastapi import APIRouter, Request
from typing import Dict, Any

router = APIRouter(tags=["debug"])

# פונקציות עזר – נסה לייבא ואם אין, נשתמש בדמה בטוחה
def _noop(*a, **kw): return {}
try:
    from utils.auth import extract_token, token_matches, refresh_tokens, get_loaded_tokens  # type: ignore
except Exception:
    def extract_token(request: Request, a: str|None, x: str|None):  # type: ignore
        if a and a.lower().startswith("bearer "): return a.split(" ",1)[1].strip()
        if x: return x.strip()
        return None
    def token_matches(t: str|None): return bool(t)  # type: ignore
    def refresh_tokens(): return {"reloaded": False}  # type: ignore
    def get_loaded_tokens(mask: bool=True):  # type: ignore
        return {"tokens": [], "allow_all": False}

@router.get("/_debug/auth", include_in_schema=False)
async def _debug_auth(request: Request) -> Dict[str, Any]:
    a = request.headers.get("authorization") or request.headers.get("Authorization")
    x = request.headers.get("x-api-key") or request.headers.get("X-API-Key")
    t = extract_token(request, a, x)
    return {
        "ok": True,
        "auth_header": a,
        "x_api_key": x,
        "query": dict(request.query_params),
        "extracted_token": t,
        "matches": bool(token_matches(t)),
        "tokens_loaded": get_loaded_tokens(mask=True),
    }

@router.post("/debug/refresh-auth", include_in_schema=False)
async def _debug_refresh_auth() -> Dict[str, Any]:
    info = refresh_tokens()
    return {"ok": True, "detail": "Tokens reloaded from environment", **info, "tokens_masked": get_loaded_tokens(mask=True)}
