# utils/auth.py
from __future__ import annotations
import os
import time
from typing import Iterable, List, Optional, Set, Tuple

from fastapi import Depends, Header, HTTPException, Request
from fastapi.routing import APIRouter

# ─────────────────────────────────────────────────────────────────────────────
# טעינת טוקנים — תומך גם בקובץ וגם ב-ENV, באותם שמות שמשמשים ב/_debug/auth
# ─────────────────────────────────────────────────────────────────────────────

_TOKENS: Set[str] = set()
_TOKENS_MTIME: Optional[float] = None
_LAST_REFRESH: float = 0.0

_ENV_KEYS = (
    "API_TOKENS",         # comma-separated
    "ALGOGPT_TOKENS",     # comma-separated (תואם ישנים)
    "API_BEARER_TOKEN",   # יחיד
)
_FILE_ENV = "API_TOKENS_FILE"   # default: /app/tokens.txt
_DEFAULT_FILE = "/app/tokens.txt"
_AUTH_TTL_SEC = int(os.getenv("AUTH_TOKENS_TTL", "0") or "0")  # 0=לא משתמש בזמן

def _split_csv(s: str) -> Iterable[str]:
    for part in (s or "").split(","):
        p = part.strip()
        if p:
            yield p

def _read_file_tokens(path: str) -> Tuple[Set[str], Optional[float]]:
    try:
        st = os.stat(path)
        toks: Set[str] = set()
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                t = line.strip()
                if t:
                    toks.add(t)
        return toks, st.st_mtime
    except Exception:
        return set(), None

def _read_env_tokens() -> Set[str]:
    out: Set[str] = set()
    for k in _ENV_KEYS:
        v = os.getenv(k, "").strip()
        if not v:
            continue
        if k == "API_BEARER_TOKEN":
            out.add(v)
        else:
            out.update(_split_csv(v))
    return out

def _load_tokens(force: bool = False) -> None:
    global _TOKENS, _TOKENS_MTIME, _LAST_REFRESH
    now = time.time()
    if not force and _AUTH_TTL_SEC > 0 and (now - _LAST_REFRESH) < _AUTH_TTL_SEC:
        return

    path = os.getenv(_FILE_ENV, _DEFAULT_FILE)
    file_tokens, mtime = _read_file_tokens(path)
    env_tokens = _read_env_tokens()

    # קדימות: גם וגם (איחוד)
    merged = set()
    merged.update(file_tokens)
    merged.update(env_tokens)

    _TOKENS = merged
    _TOKENS_MTIME = mtime
    _LAST_REFRESH = now

def refresh_tokens() -> dict:
    _load_tokens(force=True)
    # מסכים להחזיר טוקנים מקוצרים ללוג/דיבוג
    def _short(t: str) -> str:
        return f"{t[:2]}…{t[-2:]}" if len(t) > 4 else t
    return {
        "ok": True,
        "count": len(_TOKENS),
        "tokens": sorted(_short(t) for t in _TOKENS),
        "file": os.getenv(_FILE_ENV, _DEFAULT_FILE),
        "ttl_sec": _AUTH_TTL_SEC,
    }

# ─────────────────────────────────────────────────────────────────────────────
# שליפת טוקן מהבקשה: query / header / bearer
# ─────────────────────────────────────────────────────────────────────────────

def _extract_bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    auth = authorization.strip()
    if not auth:
        return None
    parts = auth.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip() or None
    return None

def _get_token_from_request(
    request: Request,
    x_api_key: Optional[str] = Header(default=None, convert_underscores=False),
    authorization: Optional[str] = Header(default=None),
) -> Tuple[Optional[str], str]:
    """
    מחזיר (token, source) כשה-token יכול להגיע מ:
      • query param: ?api_key=...
      • header: X-API-Key: ...
      • header: Authorization: Bearer ...
    """
    # 1) query
    q = request.query_params.get("api_key")
    if q:
        return q, "query"
    # 2) X-API-Key
    if x_api_key:
        return x_api_key, "x-api-key"
    # 3) Authorization: Bearer
    b = _extract_bearer(authorization)
    if b:
        return b, "bearer"
    return None, "none"

# ─────────────────────────────────────────────────────────────────────────────
# ה-Dependency לשימוש בנתיבים מאובטחים
# ─────────────────────────────────────────────────────────────────────────────

def require_api_key(
    request: Request,
    x_api_key: Optional[str] = Header(default=None, convert_underscores=False),
    authorization: Optional[str] = Header(default=None),
):
    _load_tokens(force=False)
    token, source = _get_token_from_request(request, x_api_key, authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Missing API key")

    if token not in _TOKENS:
        # ניסיון קטן לחלץ mismatch קלאסיים
        hint = "use ?api_key=... or 'Authorization: Bearer ...' or 'X-API-Key: ...'"
        raise HTTPException(status_code=401, detail=f"Invalid API key (via {source}); {hint}")

    # החזר את הטוקן למי שצריך (אופציונלי)
    return token

# ─────────────────────────────────────────────────────────────────────────────
# מסלולי דיבוג/ריענון — אופציונלי (לתאם עם הראוטר הראשי)
# ─────────────────────────────────────────────────────────────────────────────

router = APIRouter()

@router.get("/_debug/auth")
def debug_auth(
    request: Request,
    x_api_key: Optional[str] = Header(default=None, convert_underscores=False),
    authorization: Optional[str] = Header(default=None)
):
    _load_tokens(force=False)
    token, source = _get_token_from_request(request, x_api_key, authorization)
    return {
        "ok": True,
        "source": source,
        "extracted_token": token,
        "matches": bool(token and token in _TOKENS),
        "tokens_loaded": sorted(list(_TOKENS)),
    }

@router.post("/debug/refresh-auth")
def http_refresh_auth():
    return refresh_tokens()
















































































































































































