# routes/status.py
from __future__ import annotations
import os
import time
from typing import Any, Dict
from fastapi import APIRouter

# מקורות סטטוס קיימים (נשתמש אם זמינים)
try:
    from utils.runtime_counters import get_ws_status, get_exec_status  # type: ignore
except Exception:
    def get_ws_status() -> Dict[str, Any]:
        return {}
    def get_exec_status() -> Dict[str, Any]:
        return {}

# ------- עזר: ספירת טוקנים טעונים -------
def _tokens_count() -> int:
    """
    מנסה להשתמש ב-utils.auth.get_loaded_tokens; אם לא קיים – נופל חזרה ל-ENV/KV בקובץ.
    """
    # ניסיון להשתמש במימוש הקיים, אם זמין
    try:
        from utils.auth import get_loaded_tokens  # type: ignore
        return len(get_loaded_tokens(mask=False))  # לא חושף ערכים, רק ספירה
    except Exception:
        pass

    # Fallback: ENV + קובץ
    tokens: list[str] = []
    raw = os.getenv("API_TOKENS", "")
    if raw:
        tokens += [t.strip() for t in raw.split(",") if t.strip()]

    fpath = os.getenv("API_TOKENS_FILE")
    if fpath and os.path.exists(fpath):
        try:
            with open(fpath, "r", encoding="utf-8") as fh:
                tokens += [ln.strip() for ln in fh if ln.strip()]
        except Exception:
            pass

    # הסרה של כפילויות
    seen: set[str] = set()
    uniq = []
    for t in tokens:
        if t not in seen:
            uniq.append(t)
            seen.add(t)
    return len(uniq)

def _public_config() -> Dict[str, Any]:
    """קורא את קונפיג הציבור מה-ENV (לנראות מה נטען לתהליך)."""
    def _as_bool(v: str | None) -> bool:
        return (v or "").lower() in ("1", "true", "yes", "on")
    def _split(v: str | None) -> list[str]:
        return [p.strip() for p in (v or "").split(",") if p.strip()]

    return {
        "enabled": _as_bool(os.getenv("SECURITY_PUBLIC_STATUS")),
        "paths": _split(os.getenv("SECURITY_PUBLIC_PATHS")),
        "prefixes": _split(os.getenv("SECURITY_PUBLIC_PREFIXES")),
    }

router = APIRouter(prefix="/status", tags=["Status"])

# --------- Endpoints ציבוריים מומלצים ---------
@router.get("/ping")
async def status_ping() -> Dict[str, Any]:
    return {"ok": True, "ts": int(time.time())}

@router.get("/ws")
async def status_ws() -> Dict[str, Any]:
    return {"ok": True, "status": get_ws_status()}

@router.get("/executor")
async def status_executor() -> Dict[str, Any]:
    return {"ok": True, "status": get_exec_status()}

@router.get("/all")
async def status_all() -> Dict[str, Any]:
    return {
        "ok": True,
        "ts": int(time.time()),
        "ws": get_ws_status(),
        "executor": get_exec_status(),
        "public": _public_config(),
    }

# בדיקת auth ללא חשיפת ערכי טוקנים — רק ספירה + קונפיג public
@router.get("/auth")
async def status_auth() -> Dict[str, Any]:
    return {
        "ok": True,
        "tokens_count": _tokens_count(),
        "public": _public_config(),
    }

# --------- אליאסים תואמי-עבר (לא שוברים לקוחות קיימים) ---------
@router.get("/ws-user/status")
async def ws_user_status() -> Dict[str, Any]:
    return {"ok": True, "status": get_ws_status()}

@router.get("/executor/status")
async def executor_status() -> Dict[str, Any]:
    return {"ok": True, "status": get_exec_status()}




