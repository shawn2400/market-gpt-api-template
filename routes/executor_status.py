# routes/executor_status.py
from __future__ import annotations
from fastapi import APIRouter
from typing import Dict, Any

router = APIRouter(prefix="/executor", tags=["status"])

try:
    from utils.runtime_counters import exec_get_counters
except Exception:
    def exec_get_counters() -> Dict[str, Any]:
        return {
            "tick_ewma_ms": 0.0, "tick_p95_ms": None, "tick_p99_ms": None,
            "last_tick_age_sec": None, "timeouts_burst": 0, "no_trade_streak": 0,
            "current_interval": 0,
        }

@router.get("/status")
def exec_status():
    return {"ok": True, "counters": exec_get_counters()}

  
