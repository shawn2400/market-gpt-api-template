# routes/ws_user_status.py
from __future__ import annotations
import time
from fastapi import APIRouter

router = APIRouter(prefix="/ws-user", tags=["status"])

def _rc_ws_snapshot():
    """
    מנסה למשוך counters מ-runtime_counters אם קיים; נופל חן אם לא.
    מחזיר dict או None.
    """
    try:
        # תקרא לכל אחת מהאופציות הנפוצות; מי שקיים – ירוץ.
        from utils.runtime_counters import ws_get_counters as _f  # type: ignore
        return _f()
    except Exception:
        pass
    try:
        from utils.runtime_counters import ws_snapshot as _f  # type: ignore
        return _f()
    except Exception:
        pass
    try:
        from utils.runtime_counters import get_ws_counters as _f  # type: ignore
        return _f()
    except Exception:
        return None

def _ws_basic_status():
    try:
        from utils import ws_user_stream
        return ws_user_stream.status()
    except Exception:
        return {"running": False, "have_listen_key": False, "ws_up": 0}

@router.get("/status")
def ws_user_status():
    """
    מחזיר סטטוס חי של ה-User-Data Stream:
    - בסיס: running/listen_key/ws_up
    - אם יש runtime_counters: יכלול EWMA, reconnects, events, latency מדדים וכו'.
    """
    snap = _rc_ws_snapshot() or {}
    base = _ws_basic_status()
    return {
        "ok": True,
        "ts_ms": int(time.time() * 1000),
        "base": base,
        "counters": snap,
    }




