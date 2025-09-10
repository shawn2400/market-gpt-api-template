# routes/executor_status.py
from __future__ import annotations
import time, os
from fastapi import APIRouter

router = APIRouter(prefix="/executor", tags=["status"])

def _rc_exec_snapshot():
    """
    מנסה למשוך counters מ-runtime_counters אם קיים; נופל חן אם לא.
    מחזיר dict או None.
    """
    # שמות אפשריים – ננסה לפי סדר:
    for name in ("exec_get_counters", "exec_snapshot", "get_exec_counters"):
        try:
            from utils import runtime_counters as rc  # type: ignore
            fn = getattr(rc, name, None)
            if callable(fn):
                return fn()
        except Exception:
            pass
    return None

def _is_running():
    try:
        from utils.auto_executor import is_executor_running
        return bool(is_executor_running())
    except Exception:
        return False

@router.get("/status")
def executor_status():
    """
    מחזיר סטטוס של ה-Auto Executor:
    - running: האם הלולאה החיה
    - counters: אם runtime_counters זמין – יחזיר EWMA/P95/timeouts/last_tick וכד'.
    - env: חשיפת ספי אופס מרכזיים (קריא בלבד).
    """
    counters = _rc_exec_snapshot() or {}
    env = {
        "EXEC_TIMEOUT_BURST_ALERT": int(os.getenv("EXEC_TIMEOUT_BURST_ALERT", "3")),
        "OPS_TICK_ENABLE": int(os.getenv("OPS_TICK_ENABLE", "1")),
        "PRICE_DRIFT_BPS_ALERT": float(os.getenv("PRICE_DRIFT_BPS_ALERT", "25")),
        "OPS_TTL_ALERT_TELEGRAM": int(os.getenv("OPS_TTL_ALERT_TELEGRAM", "1")),
        "OPS_TIMEOUT_BURST_TELEGRAM": int(os.getenv("OPS_TIMEOUT_BURST_TELEGRAM", "1")),
        "OPS_DRIFT_ALERT_TELEGRAM": int(os.getenv("OPS_DRIFT_ALERT_TELEGRAM", "1")),
        "OPS_ALERT_COOLDOWN_SEC": int(os.getenv("OPS_ALERT_COOLDOWN_SEC", "120")),
    }
    return {
        "ok": True,
        "ts_ms": int(time.time() * 1000),
        "running": _is_running(),
        "counters": counters,
        "env": env,
    }

  
