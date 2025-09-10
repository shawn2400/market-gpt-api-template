# routes/executor_status.py
from __future__ import annotations
from fastapi import APIRouter
from utils.runtime_counters import executor_status
try:
    from utils.auto_executor import is_executor_running
except Exception:
    def is_executor_running() -> bool:
        return False

router = APIRouter(prefix="/executor", tags=["status"])

@router.get("/status")
def get_executor_status():
    return {
        "ok": True,
        "running": bool(is_executor_running()),
        "counters": executor_status(),
    }
