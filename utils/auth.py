# utils/auth.py
from __future__ import annotations
import os, hmac, json, logging, re
from typing import Set, Optional, List, Tuple
from threading import RLock
from fastapi import Header, HTTPException, status, Request

logger = logging.getLogger("algogpt.auth")

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────
def _truthy(v: str | None) -> bool:
    return str(v or "").strip().lower() in {"1", "true", "yes", "on"}

def _split_tokens(val: str) -> Set[str]:
    """
    מפרק CSV / רווחים / נקודה-פסיק / שורות – לרשימת טוקנים.
    """
    parts = re.split(r"[,\n;\s]+", (val or "").strip())
    return {p for p in (s.strip() for s in parts) if p}

def _mask_token(t: str) -> str:
    if not t:
        return ""
    if len(t) <= 6:
        return "***"
    return f"{t[:3]}…{t[-3:]}"

def _const_eq(a: str, b: str) -> bool:
    try:
        return hmac.compare_digest(a, b)
    except Exception:
        return a == b

def _extract_bearer(authorization: Optional[str]) -> Optional[str]:
    """
    Authorization: Bearer <token>
    """
    if not authorization:
        return None
    parts = authorization.strip().split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip() or None
    return None

def _parse_tokens_blob(blob: str) -> Set[str]:
    """
    תומך גם ב-JSON (רשימה/אובייקט) וגם בטקסט חופשי (CSV/שורות).
    """
    blob = (blob or "").strip()
    if not blob:
        return set()
    # JSON?
    try:
        js = json.loads(blob)
        if isinstance(js, list):
            return {str(x).strip() for x in js if str(x).strip()}
        if isinstance(js, dict):
            # אפשר לקחת keys כאסופה של שמות/טוקנים
            return {str(k).strip() for k in js.keys() if str(k).strip()}
    except Exception:
        pass
    # אחרת: CSV/שורות/רווחים
    return _split_tokens(blob)

# ──────────────────────────────────────────────────────────────────────────────
# Token store (in-memory; reloadable)
# ──────────────────────────────────────────────────────────────────────────────
_TOKENS_LOCK = RLock()
_TOKENS: Set[str] = set()
_ALLOW_ALL: bool = False

# נתיבי בריאות ציבוריים (ניתן להרחיב ב-ENV)
_DEFAULT_PUBLIC_PATHS: Tuple[str, ...] = ("/ping", "/status", "/executor/ping", "/executor/status")
def _load_public_paths() -> Tuple[str, ...]:
    raw = (os.getenv("SECURITY_PUBLIC_PATHS") or "").strip()
    if not raw:
        return _DEFAULT_PUBLIC_PATHS
    items = [x.strip() for x in raw.split(",") if x.strip()]
    return tuple(items) if items else _DEFAULT_PUBLIC_PATHS

_PUBLIC_PATHS: Tuple[str, ...] = _load_public_paths()
_PUBLIC_STATUS: bool = _truthy(os.getenv("SECURITY_PUBLIC_STATUS", "1"))

def _load_tokens_from_env() -> Set[str]:
    """
    קורא טוקנים ממספר שמות ENV (וגם *_FILE / קבצי סודות).
    תומך ב-CSV / שורות / JSON.
    """
    keys = (
        "API_BEARER_TOKEN",
        "API_BEARER_TOKEN_ALT",
        "API_BEARER_TOKENS",
        "ALGOGPT_TOKEN",
        "ALGOGPT_TOKENS",
        "API_BEARER",
        "API_TOKENS",
    )
    file_keys = tuple(f"{k}_FILE" for k in keys) + ("ALLOWED_TOKENS_FILE", "TOKENS_FILE")

    toks: Set[str] = set()

    # 1) קבצים (Docker secrets וכד')
    for fk in file_keys:
        path = (os.getenv(fk) or "").strip()
        if not path:
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                toks |= _parse_tokens_blob(f.read())
        except Exception as e:
            logger.debug("[Auth] ignore %s (%s)", fk, e)

    # 2) ערכי ENV ישירים
    for k in keys:
        v = (os.getenv(k) or "").strip()
        if v:
            toks |= _parse_tokens_blob(v)

    # סינון פלייסהולדרים נפוצים
    bad = {"PUT_REAL_API_TOKEN", "<PUT_YOUR_TOKEN_HERE>", "CHANGE_ME"}
    toks = {t for t in toks if t and t not in bad}
    return toks

def _init_store() -> None:
    global _TOKENS, _ALLOW_ALL, _PUBLIC_STATUS, _PUBLIC_PATHS
    with _TOKENS_LOCK:
        _TOKENS = _load_tokens_from_env()
        _ALLOW_ALL = _truthy(os.getenv("SECURITY_ALLOW_ALL"))
        _PUBLIC_STATUS = _truthy(os.getenv("SECURITY_PUBLIC_STATUS", "1"))
        _PUBLIC_PATHS = _load_public_paths()
    logger.info("[Auth] loaded %d tokens (allow_all=%s, public_status=%s, public_paths=%s)",
                len(_TOKENS), _ALLOW_ALL, _PUBLIC_STATUS, list(_PUBLIC_PATHS))

_init_store()

def refresh_tokens_from_env() -> int:
    """
    ניתן לקרוא בזמן ריצה אחרי שינוי ENV/קבצים.
    """
    global _TOKENS, _ALLOW_ALL, _PUBLIC_STATUS, _PUBLIC_PATHS
    with _TOKENS_LOCK:
        _TOKENS = _load_tokens_from_env()
        _ALLOW_ALL  = _truthy(os.getenv("SECURITY_ALLOW_ALL"))
        _PUBLIC_STATUS = _truthy(os.getenv("SECURITY_PUBLIC_STATUS", "1"))
        _PUBLIC_PATHS = _load_public_paths()
        count = len(_TOKENS)
    logger.info("[Auth] tokens refreshed (%d loaded, allow_all=%s, public_status=%s, public_paths=%s)",
                count, _ALLOW_ALL, _PUBLIC_STATUS, list(_PUBLIC_PATHS))
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

# ──────────────────────────────────────────────────────────────────────────────
# Extraction
# ──────────────────────────────────────────────────────────────────────────────
def _header_any(request: Request, names: Tuple[str, ...]) -> Optional[str]:
    """
    מחפש בכותרות האלטרנטיביות (Case-insensitive אם זה Starlette Headers; בטסטים – דואגים למפתחות lowercase).
    """
    for n in names:
        v = request.headers.get(n)  # עבור dict רגיל בטסטים: חייב להיות lowercase; בקוד אמיתי Headers הוא case-insensitive
        if v and str(v).strip():
            return str(v).strip()
    return None

def extract_token(
    request: Request,
    authorization: Optional[str] = None,
    x_api_key: Optional[str] = None,  # לא בשימוש ישיר – נשמר לחתימה תואמת FastAPI
) -> Optional[str]:
    # 1) Authorization: Bearer <token>
    token = _extract_bearer(authorization or request.headers.get("authorization"))
    # 2) כותרות אלטרנטיביות אהובות־מפתחים
    if not token:
        hdr = _header_any(
            request,
            (
                "x-api-key",
                "x-auth-token",
                "x-token",
                "x-algogpt-token",
                "x-authorization",
            ),
        )
        token = (hdr or "").strip() or None
    # 3) Query params – וריאציות נפוצות
    if not token:
        qp = (
            request.query_params.get("api_key")
            or request.query_params.get("token")
            or request.query_params.get("apikey")
            or request.query_params.get("access_token")
        )
        token = (qp.strip() if qp else None)
    return token or None

# ──────────────────────────────────────────────────────────────────────────────
# FastAPI dependency
# ──────────────────────────────────────────────────────────────────────────────
async def require_api_key(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None),
) -> None:
    """
    תלוי ב-ENV:
      - SECURITY_ALLOW_ALL=1 → מעביר הכל.
      - SECURITY_PUBLIC_STATUS=1 → מתיר נתיבי בריאות/סטטוס ב-_PUBLIC_PATHS.
      - SECURITY_PUBLIC_PATHS="...,/healthz" → הוספת נתיבים ציבוריים.
    אחרת – מחייב טוקן תקין.
    """
    # Public health/status
    if _PUBLIC_STATUS:
        p = request.url.path
        # התאמה ישירה או endswith לנתיבים קצרים (מאפשר /executor/status וכד')
        if any(p == x or p.endswith(x) for x in _PUBLIC_PATHS):
            return

    if allow_all():
        return

    token = extract_token(request, authorization, x_api_key)
    if not token_matches(token):
        masked = _mask_token(token or "")
        logger.warning("[Auth] invalid token=%s path=%s", masked, request.url.path)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "Bearer, X-API-Key"},
        )

# שמירה על תאימות לאחור
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















































































































































































