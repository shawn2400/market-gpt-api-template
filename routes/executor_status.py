# routes/executor_status.py
from __future__ import annotations
import os, time
from typing import Any, Dict, Optional
from fastapi import APIRouter, Response

router = APIRouter(prefix="/status", tags=["status"])

# Fallback-safe import
try:
    from utils.runtime_counters import exec_get_counters as _exec_get_counters
except Exception:
    def _exec_get_counters() -> Dict[str, Any]:
        return {
            "tick_ewma_ms": 0.0,
            "tick_p95_ms": None,
            "tick_p99_ms": None,
            "last_tick_age_sec": None,
            "timeouts_burst": 0,
            "no_trade_streak": 0,
            "current_interval": 0,
        }

# Thresholds (ENV overrideable, עם ברירות מחדל שמרניות)
EXEC_TICK_STALE_WARN_SEC = int(os.getenv("EXEC_TICK_STALE_WARN_SEC", "30"))
TIMEOUT_BURST_ALERT      = int(os.getenv("EXEC_TIMEOUT_BURST_ALERT", "3"))

def _classify_executor(c: Dict[str, Any]) -> Dict[str, Any]:
    state = "OK"
    reasons: list[str] = []

    age = c.get("last_tick_age_sec")
    if isinstance(age, (int, float)) and age is not None and age > EXEC_TICK_STALE_WARN_SEC:
        state = "WARN"
        reasons.append(f"last_tick_age_sec>{EXEC_TICK_STALE_WARN_SEC}")

    tb = int(c.get("timeouts_burst") or 0)
    if tb >= TIMEOUT_BURST_ALERT:
        state = "WARN"
        reasons.append(f"timeouts_burst>={TIMEOUT_BURST_ALERT}")

    return {"state": state, "reasons": reasons or ["healthy"]}

@router.get("/executor", summary="Auto-executor counters (runtime)")
def executor_status(response: Response) -> Dict[str, Any]:
    """
    מחזיר Counters חיים של ה־executor + סיווג OK/WARN.
    """
    response.headers["Cache-Control"] = "no-store, max-age=0"
    counters = _exec_get_counters()
    cls = _classify_executor(counters)
    return {
        "ok": True,
        "ts": int(time.time()),
        "version": os.getenv("ALGOGPT_VERSION", ""),
        "executor": counters,
        **cls,
    }


  
