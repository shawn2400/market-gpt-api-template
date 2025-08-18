# routes/grid.py
from __future__ import annotations
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from typing import Any

# מגן Bearer גלובלי לראוטר הזה
try:
    from utils.auth import require_bearer_token
except Exception as e:  # הגנה אם auth לא נטען
    def require_bearer_token():
        raise HTTPException(status_code=401, detail="Unauthorized")
    
router = APIRouter(prefix="/grid", tags=["Health"], dependencies=[Depends(require_bearer_token)])

# נסיון להתחבר לטרקר/אקסקיוטור אם קיימים בפרויקט
_HAS_TRACKER = False
_get_status = None
try:
    # אם יש לך פונקציה כזו—נשתמש בה; אחרת ניפול לפולבאק
    from utils.grid_tracker import get_status as _get_status  # type: ignore
    _HAS_TRACKER = True
except Exception:
    _HAS_TRACKER = False
    _get_status = None

@router.get("/status")
async def grid_status() -> dict[str, Any]:
    payload: dict[str, Any] | None = None

    if _HAS_TRACKER and _get_status:
        try:
            # תומך בפונקציה sync/async
            if getattr(_get_status, "__await__", None):
                payload = await _get_status()  # type: ignore
            else:
                payload = _get_status()  # type: ignore
        except Exception:
            payload = None

    if not payload:
        # פולבאק בטוח אם אין טרקר
        payload = {
            "ok": True,
            "running": False,
            "workers": 0,
            "queue_size": 0,
            "concurrency": 16,
        }

    payload.setdefault("ok", True)
    payload.setdefault("last_heartbeat", datetime.now(timezone.utc).isoformat())
    return payload











