# routes/debug.py
from __future__ import annotations
from typing import Dict, Any, List
import os, platform, time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query

# נדרשת רק בדיקת הרשאות, בלי get_loaded_tokens/refresh_tokens_from_env
from utils.auth import require_api_key

router = APIRouter(
    prefix="/debug",
    tags=["Debug"],
    dependencies=[Depends(require_api_key)],
)

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _get_sys_stats() -> Dict[str, Any]:
    """סטטיסטיקות מערכת — psutil אופציונלי. אם לא מותקן, מחזירים None."""
    out: Dict[str, Any] = {"cpu_percent": None, "memory": None}
    try:
        import psutil  # type: ignore
        vm = psutil.virtual_memory()
        out["cpu_percent"] = psutil.cpu_percent(interval=0.1)
        out["memory"] = {
            "total_mb": round(vm.total / 1048576, 2),
            "used_mb": round(vm.used / 1048576, 2),
            "free_mb": round(vm.available / 1048576, 2),
            "percent": vm.percent,
        }
    except Exception:
        # psutil לא קיים או כשל — משאירים None כדי לא להפיל את ה־API
        pass
    return out

def _split_tokens(val: str | None) -> List[str]:
    if not val:
        return []
    s = val.replace("\n", ",").replace(";", ",")
    return [t.strip() for t in s.split(",") if t.strip()]

def _clean_key(s: str | None) -> str:
    return (s or "").strip().strip('"').replace("\r", "").replace("\n", "").replace("\t", "")

def _load_tokens_from_env_like_main() -> List[str]:
    """שחזור לוגיקת טעינת טוקנים כפי שנעשית ב-main.py (לקריאה בלבד)."""
    raw = [
        os.getenv("API_BEARER_TOKEN"),
        os.getenv("API_BEARER_TOKEN_ALT"),
        *_split_tokens(os.getenv("ALGOGPT_TOKENS")),
    ]
    toks: List[str] = []
    for t in raw:
        ct = _clean_key(t)
        if ct:
            toks.append(ct)
    return toks

def _mask_token(token: str) -> str:
    """מסכה לא גרסה מלאה של טוקן (Privacy)."""
    if len(token) <= 8:
        return "*" * max(0, len(token) - 2) + token[-2:]
    return f"{token[:4]}...{token[-4:]}"

@router.get("", summary="Debug multiplexer (single operation)")
def debug(op: str = Query("ping", pattern="^(ping|health|tokens)$")) -> Dict[str, Any]:
    """
    נקודת דיבוג רב-מצבית (op) כדי לשמור על פעולה אחת ב־OpenAPI:
      - op=ping   → בדיקת זמינות
      - op=health → מידע מערכת בסיסי (psutil אופציונלי)
      - op=tokens → ספירת טוקנים + מסכות (נקרא ישירות מה-ENV; לא משנה את מה שנטען ב-startup)
    """
    if op == "ping":
        return {"ok": True, "ts": time.time()}

    if op == "health":
        base = {
            "ok": True,
            "env": os.getenv("ENV", "production"),
            "platform": platform.platform(),
            "time": _now_iso(),
        }
        base.update(_get_sys_stats())
        return base

    if op == "tokens":
        toks = _load_tokens_from_env_like_main()
        return {
            "ok": True,
            "count": len(toks),
            # לא מציגים טוקנים גולמיים — רק מסכה "XXXX...YYYY"
            "tokens_masked": [_mask_token(t) for t in toks],
            "note": "הטוקנים כאן נקראים מה-ENV לצורך תצוגה בלבד. "
                    "ה־middleware משתמש בסט שנטען בזמן ה־startup; שינוי טוקנים דורש ריסטארט.",
        }

    # מקרה שלא יתפוס בגלל ה-regex, אבל נשאיר לטובת יציבות
    return {"ok": False, "error": "unknown op"}








