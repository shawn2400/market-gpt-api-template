# routes/executor_status.py
from __future__ import annotations
import time
from fastapi import APIRouter

try:
    from utils.runtime_counters import (
        exec_get_counters,
        get_degrade_cap,
        get_last_drift_snapshot,
    )
except Exception:
    def exec_get_counters(): return {}
    def get_degrade_cap(): return None
    def get_last_drift_snapshot(): return {}

router = APIRouter(prefix="/executor", tags=["executor"])

@router.get("/ping", include_in_schema=False)
async def ping():
    return {"ok": True, "ts_ms": int(time.time() * 1000)}

@router.get("/status")
async def status():
    try:
        counters = exec_get_counters()
    except Exception:
        counters = {}
    # מוסיף קצת נוחות למי שצורך את ה־API
    return {
        "ok": True,
        **counters,
        "degrade_cap": get_degrade_cap(),
        "drift": get_last_drift_snapshot(),
    }

  
