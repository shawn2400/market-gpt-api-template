# /app/utils/auth.py
from __future__ import annotations
import os, re, time, logging
from typing import Optional, List, Set, Dict, Any

from fastapi import Request, Header, HTTPException

log = logging.getLogger("algogpt.auth")

# ---- helpers ---------------------------------------------------------------
def _b(val: Any) -> bool:
    return str(val or "").strip().lower() in ("1", "true", "yes", "on")

def _split_tokens(s: str) -> List[str]:
    # מפריד בפסיקים/רווחים/שורות; מתעלם מריקים
    return [t.strip() for t in re.split(r"[,\s]+", (s or "").strip()) if t.strip()]

def _read_file_lines(path: str | None) -> List[str]:
    if not path:
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return [ln.strip() for ln in f.readlines() if ln.strip()]
    except Exception as e:
        log.warning({"event": "auth.tokens_file_read_failed", "file": path, "error": str(e)})
        return []

_TOKENS: Set[str] = set()
_T_AT: float = 0.0
_TTL: float = float(os.getenv("AUTH_TOKENS_TTL", "60"))

def _fresh() -> None:
    """רענון מטמון הטוקנים לפי ENV/FILE עם TTL פשוט."""
    global _T_AT, _TOKENS
    now = time.time()
    if _TOKENS and now - _T_AT < _TTL:
        return
    env_tokens = _split_tokens(os.getenv("API_TOKENS", ""))
    file_tokens = _read_file_lines(os.getenv("API_TOKENS_FILE", ""))
    _TOKENS = {t for t in (env_tokens + file_tokens) if t}
    _T_AT = now
    log.info({"event": "auth.tokens_refreshed", "count": len(_TOKENS)})

def refresh_tokens_from_env() -> List[str]:
    global _T_AT
    _T_AT = 0.0
    _fresh()
    return sorted(_TOKENS)

def allow_all() -> bool:
    return _b(os.getenv("SECURITY_ALLOW_ALL", "0"))

# ---- public paths (for /status/auth display/use) ---------------------------
def _split_multi(s: str) -> List[str]:
    return [x for x in re.split(r"[,\s]+", (s or "").strip()) if x]

def get_public_paths() -> Dict[str, List[str]]:
    paths = _split_multi(os.getenv("SECURITY_PUBLIC_PATHS", ""))
    prefixes = _split_multi(os.getenv("SECURITY_PUBLIC_PREFIXES", ""))
    # נוח לדיבוג – אם תרצי להוסיף ברירת מחדל ממש פה
    return {"paths": sorted(paths), "prefixes": sorted(prefixes)}

def get_public_config() -> Dict[str, List[str]]:
    # שומר תאימות – מחזיר אותו הדבר
    return get_public_paths()

# ---- token extraction & check ---------------------------------------------
_QUERY_KEYS = ("api_key", "apikey", "apiKey", "token", "key")

def _from_auth_header(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    s = authorization.strip()
    m = re.match(r"^\s*Bearer\s+(.+?)\s*$", s, re.IGNORECASE)
    if m:
        return m.group(1).strip().strip('"').strip("'")
    m = re.match(r"^\s*Token\s+(.+?)\s*$", s, re.IGNORECASE)
    if m:
        return m.group(1).strip().strip('"').strip("'")
    # נופלים חזרה – אם מישהו שלח סתם את הטוקן בגוף ההדר
    return s.strip().strip('"').strip("'")

def extract_token(request: Request,
                  authorization: Optional[str] = None,
                  x_api_key: Optional[str] = None) -> Optional[str]:
    # סדר עדיפויות: query -> X-API-Key -> Authorization
    for k in _QUERY_KEYS:
        qv = request.query_params.get(k)
        if qv:
            return qv.strip()
    if x_api_key:
        return x_api_key.strip()
    if authorization:
        return _from_auth_header(authorization)
    return None

def token_matches(tok: Optional[str]) -> bool:
    _fresh()
    ok = bool(tok and tok in _TOKENS)
    log.debug({"event": "auth.token_check", "ok": ok})
    return ok

# ---- FastAPI dependency ----------------------------------------------------
async def require_api_key(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None),
) -> bool:
    # מסלולים ציבוריים מאופשרים ע"י ה-middleware הראשי/ENV; כאן רק בודקים טוקן
    if request.method.upper() == "OPTIONS":
        return True
    if allow_all():
        return True

    tok = extract_token(request, authorization, x_api_key)
    if token_matches(tok):
        return True
    raise HTTPException(status_code=401, detail="Invalid API key")

# ---- Introspection for /status/auth ---------------------------------------
def get_loaded_tokens(mask: bool = True) -> List[str]:
    _fresh()
    arr = sorted(_TOKENS)
    if not mask:
        return arr
    # מסכה "AB…23"
    def _mask(t: str) -> str:
        return (t[:2] + "…" + t[-2:]) if len(t) >= 4 else "***"
    return [_mask(t) for t in arr]























































































































































































