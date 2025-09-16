# routes/executor_control.py
from __future__ import annotations
from fastapi import APIRouter, Depends
from utils.auth import require_api_key

try:
    from utils.auto_executor import start_executor, stop_executor, is_executor_running, EXECUTOR_LAST_TS
except Exception:
    def start_executor(): ...
    def stop_executor(): ...
    def is_executor_running() -> bool: return False
    EXECUTOR_LAST_TS = None

router = APIRouter(prefix="/executor", tags=["Executor"], dependencies=[Depends(require_api_key)])

@router.post("/start")
def start():
    start_executor()
    return {"ok": True, "running": is_executor_running(), "last_ts": EXECUTOR_LAST_TS}

@router.post("/stop")
def stop():
    stop_executor()
    return {"ok": True, "running": is_executor_running(), "last_ts": EXECUTOR_LAST_TS}



