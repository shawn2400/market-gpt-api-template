# utils/auth.py
from __future__ import annotations
import os, re, time, logging, pathlib
from typing import Optional, List, Dict, Any
from fastapi import Request, Header
from fastapi.responses import JSONResponse

log = logging.getLogger("algogpt.auth")

# ───────────────────────── helpers ─────────────────────────
def _b(v: object) -> bool:
    return str(v or "").strip().lower() in ("1", "true", "yes", "on")

def _split_tokens(s: str) -> List[str]:
    return [t.strip() for t in re.split(r"[,\s]+", (s or "").strip()) if t.strip()]

def _read_file_lines(p: str) -> List[str]:
    try:
        path = pathlib.Path(p)
        if not path.exists():
            return []
        return [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    except Exception as e:
        log.warning({"event":"tokens_file_read_failed","path":p,"error":str(e)})
        return []

# ───────────────────────── config/state ─────────────────────
_TOKENS: set[str] = set()
_T_AT: float = 0.0            # last refresh
_TTL: float = float(os.getenv("AUTH_TOKENS_TTL", "60") or 60)

_ALLOW_ALL = _b(os.getenv("SECURITY_ALLOW_ALL", os.getenv("AUTH_ALLOW_ALL", "0")))

_PUB_STATUS = _b(os.getenv("SECURITY_PUBLIC_STATUS", "1"))
_PUB_PATHS_CFG = set(x for x in re.split(r"[,\s]+", os.getenv("SECURITY_PUBLIC_PATHS","")) if x)
_PUB_PREFIXES_CFG = set(x for x in re.split(r"[,\s]+", os.getenv("SECURITY_PUBLIC_PREFIXES","")) if x)

# ברירות מחדל — מסונכרן עם main.py
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
    """(Re)load tokens if TTL elapsed."""
    global _T_AT, _TOKENS
    now = time.time()
    if now - _T_AT < _TTL and _TOKENS:
        return
    env_tokens = _split_tokens(os.getenv("API_TOKENS", ""))
    file_tokens = _read_file_lines(os.getenv("API_TOKENS_FILE",""))
    _TOKENS = {t.strip() for t in (env_tokens + file_tokens) if t.strip()}
    _T_AT = now
    log.info({"event":"auth.tokens_refreshed","count":len(_TOKENS)})

def refresh_tokens_from_env() -> List[str]:
    global _T_AT
    _T_AT = 0.0
    _fresh()
    return sorted(_TOKENS)

def allow_all() -> bool:
    return _ALLOW_ALL

# ─────────────────────── debug/introspection ─────────────────
def get_loaded_tokens(mask: bool = True) -> List[str]:
    _fresh()
    arr = sorted(_TOKENS)
    if not mask:
        return arr
    # מסכה לשיתוף מאובטח בלוגים/סטטוסים
    return [t[:2] + "…" + t[-2:] if len(t) > 4 else "***" for t in arr]

def get_public_paths() -> Dict[str, List[str]]:
    paths = set(_DEFAULT_PUBLIC_PATHS) if _PUB_STATUS else set()
    paths |= _PUB_PATHS_CFG
    prefixes = set(_DEFAULT_PUBLIC_PREFIXES) if _PUB_STATUS else set()
    prefixes |= _PUB_PREFIXES_CFG
    return {"paths": sorted(paths), "prefixes": sorted(prefixes)}

# ─────────────────────── token extraction ────────────────────
_QUERY_KEYS = ("api_key","apikey","apiKey","token","key")

def _from_auth_header(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    s = authorization.strip()
    # Bearer <token> (לא תלוי רישיות)
    m = re.match(r"^\s*Bearer\s+(.+)\s*$", s, re.IGNORECASE)
    if m:
        return m.group(1).strip().strip('"').strip("'")
    # Token <token>
    m = re.match(r"^\s*Token\s+(.+)\s*$", s, re.IGNORECASE)
    if m:
        return m.group(1).strip().strip('"').strip("'")
    # raw header (נדיר)
    return s.strip().strip('"').strip("'")

def extract_token(request: Request,
                  authorization: Optional[str] = None,
                  x_api_key: Optional[str] = None) -> Optional[str]:
    # 1) query string first (כדי לאפשר בדיקות ידניות)
    q = request.query_params
    for k in _QUERY_KEYS:
        if k in q and q[k]:
            return str(q[k]).strip().strip('"').strip("'")
    # 2) X-API-Key header
    if x_api_key:
        return x_api_key.strip().strip('"').strip("'")
    # 3) Authorization header
    t = _from_auth_header(authorization)
    if t:
        return t
    # 4) גם אם לא הועברו הפרמטרים, ננסה לקרוא מה-Headers של הבקשה
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
    return bool(tok and tok in _TOKENS)

# ───────────────────── FastAPI dependency ────────────────────
async def require_api_key(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None),
) -> bool:
    """להשתמש כ-Depends(require_api_key) בראוטרים מוגנים."""
    if request.method.upper() == "OPTIONS":
        return True

    # נתיבים ציבוריים – אל תחסום
    p = request.url.path
    pub = get_public_paths()
    if p in set(pub["paths"]) or any(p.startswith(pr) for pr in pub["prefixes"]):
        return True

    if allow_all():
        return True

    tok = extract_token(request, authorization, x_api_key)
    if not token_matches(tok):
        # אחיד ל-JSONResponse גם ב-dependency (סטטוס 401)
        raise RuntimeError("Unauthorized")  # ייתפס ע"י middleware חיצוני אם יש

    return True

# אופציונלי: handler לשימוש מחוץ ל-FastAPI dependency (במידה וצריך)
async def guard_or_401(request: Request) -> Optional[JSONResponse]:
    """להשתמש ב-middleware חיצוני אם רוצים 401 JSONResponse במקום Exception."""
    try:
        await require_api_key(request)  # type: ignore
        return None
    except Exception:
        return JSONResponse(status_code=401, content={"detail":"Invalid API key"})





















































































































































































