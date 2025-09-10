from __future__ import annotations
import time
from typing import Any, Dict
from fastapi import APIRouter

router = APIRouter(prefix="", tags=["status"])

# runtime counters (Executor + Ops)
try:
    from utils.runtime_counters import executor_status, ops_status
except Exception:
    def executor_status() -> Dict[str, Any]:  # type: ignore
        return {}
    def ops_status() -> Dict[str, Any]:  # type: ignore
        return {}

# is executor running?
try:
    from utils.auto_executor import is_executor_running
except Exception:
    def is_executor_running() -> bool:  # type: ignore
        return False

@router.get("/executor/status")
async def get_executor_status():
    return {
        "ts": int(time.time()),
        "running": bool(is_executor_running()),
        "executor": executor_status(),   # tick_ewma/p95/p99, timeouts_recent_count, interval, streak
    }

@router.get("/ops/status")
async def get_ops_status():
    return {
        "ts": int(time.time()),
        "ops": ops_status(),             # ttl_bad/drift_bps/degrade_active/cap/last_alerts
    }
