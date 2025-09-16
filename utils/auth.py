# utils/auth.py
from __future__ import annotations
import os, hmac, logging, re
from typing import Set, Optional, List, Iterable
from threading import RLock
from fastapi import Header, HTTPException, status, Request

logger = logging.getLogger("algogpt.auth")

# ───────────────────────── helpers ─────────────────────────
def _truthy(v: str | None) -> bool:
    return str(v or "").strip().lower() in {"1", "true", "yes", "on"}

def _split_multi(val: str) -> List[str]:
    # מפריד פסיקים/שורות/נקודה-פסיק/רווחים
    return [s.strip() for s in re.split(r"[,\n;\s]+", (val or "").strip()) if s.strip()]

def _mask_token(t: str) -> str:
    if not t:
        return ""
    return "***" if len(t) <= 6 else f"{t[:3]}…{t[-3:]}"

def _const_eq(a: str, b: str) -> bool:
    try:
        return hmac.compare_digest(a, b)
    except Exception:
        return a == b

def _extract_bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    parts = authorization.strip().split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip() or None
    return None

def _header_any(request: Request, names: Iterable[str]) -> Optional[str]:
    # dict של FastAPI הוא case-insensitive, אבל לנוחיות מורידים ל-lower
    for n in names:
        v = request.headers.get(n) or request.headers.get(n.lower())
        if v and v.strip():
            return v.strip()
    return None

# ───────────────────────── config store ─────────────────────────
_TOKENS_LOCK = RLock()
_TOKENS: Set[str] = set()
_ALLOW_ALL: bool = False

_PUBLIC_STATUS: bool = _truthy(os.getenv("SECURITY_PUBLIC_STATUS", "1"))
_PUBLIC_PATHS: Set[str] = set()  # נתיבים מותרים ללא Auth (אם _PUBLIC_STATUS=1)

def _load_public_paths_from_env() -> Set[str]:
    raw = os.getenv("SECURITY_PUBLIC_PATHS", "").strip()
    items = set(_split_multi(raw))
    # ברירת מחדל ידידותית אם לא הוגדר:
    if not items:
        items = {"/ping", "/status"}
    # normalize
    return {p if p.startswith("/") else f"/{p}" for p in items}

def _is_public_path(path: str) -> bool:
    if not _PUBLIC_STATUS:
        return False
    p = path or "/"
    # התאמה מדויקת או עם סיומת '*': prefix
    for pat in _PUBLIC_PATHS:
        if pat.endswith("*"):
            if p.startswith(pat[:-1]):
                return True
        elif p == pat:
            return True
    return False

def _load_tokens_from_env_vars() -> Set[str]:
    keys = (
        "API_BEARER_TOKEN",
        "API_BEARER_TOKEN_ALT",
        "API_BEARER_TOKENS",
        "ALGOGPT_TOKEN",
        "ALGOGPT_TOKENS",
        "API_BEARER",
        "API_TOKENS",
    )
    out: Set[str] = set()
    for k in keys:
        v = os.getenv(k) or ""
        if v.strip():
            out.update(_split_multi(v))
    return {t for t in out if t}

def _load_tokens_from_file() -> Set[str]:
    file_keys = (
        "API_TOKENS_FILE",
        "ALGOGPT_TOKENS_FILE",
        "API_BEARER_TOKENS_FILE",
    )
    path = None
    for k in file_keys:
        v = os.getenv(k)
        if v and v.strip():
            path = v.strip()
            break
    if not path:
        # ברירת מחדל נפוצה בסודות Docker (אם קיים)
        if os.path.exists("/run/secrets/api_tokens"):
            path = "/run/secrets/api_tokens"
        else:
            return set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = f.read()
        return set(_split_multi(data))
    except Exception as e:
        logger.warning("[Auth] failed reading tokens file %s: %s", path, e)
        return set()

def _init_store() -> None:
    global _TOKENS, _ALLOW_ALL, _PUBLIC_STATUS, _PUBLIC_PATHS
    with _TOKENS_LOCK:
        env_tokens = _load_tokens_from_env_vars()
        file_tokens = _load_tokens_from_file()
        _TOKENS = {t for t in (env_tokens | file_tokens) if t}
        _ALLOW_ALL = _truthy(os.getenv("SECURITY_ALLOW_ALL"))
        _PUBLIC_STATUS = _truthy(os.getenv("SECURITY_PUBLIC_STATUS", "1"))
        _PUBLIC_PATHS = _load_public_paths_from_env()
    logger.info(
        "[Auth] loaded %d tokens (allow_all=%s, public_status=%s, public_paths=%s)",
        len(_TOKENS), _ALLOW_ALL, _PUBLIC_STATUS, sorted(_PUBLIC_PATHS)
    )
_init_store()

# ───────────────────────── public API ─────────────────────────
def refresh_tokens_from_env() -> int:
    """רענון ידני כאשר משנים ENV/קובץ בזמן ריצה."""
    global _TOKENS, _ALLOW_ALL, _PUBLIC_STATUS, _PUBLIC_PATHS
    with _TOKENS_LOCK:
        env_tokens = _load_tokens_from_env_vars()
        file_tokens = _load_tokens_from_file()
        _TOKENS = {t for t in (env_tokens | file_tokens) if t}
        _ALLOW_ALL = _truthy(os.getenv("SECURITY_ALLOW_ALL"))
        _PUBLIC_STATUS = _truthy(os.getenv("SECURITY_PUBLIC_STATUS", "1"))
        _PUBLIC_PATHS = _load_public_paths_from_env()
        count = len(_TOKENS)
    logger.info(
        "[Auth] tokens refreshed (%d loaded, allow_all=%s, public_status=%s, public_paths=%s)",
        count, _ALLOW_ALL, _PUBLIC_STATUS, sorted(_PUBLIC_PATHS)
    )
    return count

def get_loaded_tokens(mask: bool = True) -> List[str]:
    with _TOKENS_LOCK:
        toks = list(_TOKENS)
    return [(_mask_token(t) if mask else t) for t in toks]

def allow_all() -> bool:
    with _TOKENS_LOCK:
        return _ALLOW_ALL

def token_matches(candidate: Optional[str]) -> bool:
    if not candidate:
        return False
    with _TOKENS_LOCK:
        for t in _TOKENS:
            if _const_eq(candidate, t):
                return True
    return False

def extract_token(
    request: Request,
    authorization: Optional[str] = None,
    x_api_key: Optional[str] = None,
) -> Optional[str]:
    # 1) Authorization: Bearer <token>
    token = _extract_bearer(authorization or request.headers.get("authorization"))
    # 2) מגוון כותרות חלופיות:
    if not token:
        hdr = _header_any(
            request,
            (
                "X-API-Key",
                "X-Auth-Token",
                "X-Token",
                "X-Algogpt-Token",
                "X-Authorization",
                "x-api-key",
                "x-auth-token",
                "x-token",
                "x-algogpt-token",
                "x-authorization",
            ),
        )
        token = (hdr or "").strip() or None
    # 3) query params
    if not token:
        qp = request.query_params.get("api_key") or request.query_params.get("token")
        token = (qp.strip() if qp else None)
    return token or None

# ───────────────────────── FastAPI dependency ─────────────────────────
async def require_api_key(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None),
) -> None:
    # לפתוח נתיבי בריאות/בדיקות:
    if _is_public_path(request.url.path):
        return
    # מעקף מלא (ל־dev/testing)
    if allow_all():
        return
    token = extract_token(request, authorization, x_api_key)
    if not token_matches(token):
        masked = (token[:6] + "...") if token else None
        logger.warning("[Auth] invalid token=%s path=%s", masked, request.url.path)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "Bearer, X-API-Key"},
        )

# תאימות לאחור
require_bearer_token = require_api_key

__all__ = [
    "require_api_key",
    "require_bearer_token",
    "refresh_tokens_from_env",
    "get_loaded_tokens",
    "extract_token",
    "allow_all",
    "token_matches",
]
















































































































































































