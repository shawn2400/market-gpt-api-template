# routes/executor_control.py
from __future__ import annotations
from fastapi import APIRouter
from utils.auto_executor import start_executor, stop_executor, is_executor_running, EXECUTOR_LAST_TS

router = APIRouter(prefix="/executor", tags=["Executor"])

@router.get("/status")
def exec_status():
    """סטטוס ריצה של ה-Auto Executor."""
    return {"ok": True, "running": is_executor_running(), "last_ts": EXECUTOR_LAST_TS}

@router.post("/start")
def exec_start():
    """הפעלת לולאת הסריקה/ביצוע."""
    if is_executor_running():
        return {"ok": True, "running": True, "note": "already running"}
    start_executor()
    return {"ok": True, "running": True}

@router.post("/stop")
def exec_stop():
    """עצירת הלולאה באופן נקי."""
    if not is_executor_running():
        return {"ok": True, "running": False, "note": "already stopped"}
    stop_executor()
    return {"ok": True, "running": False}
