# routes/executor.py
from fastapi import APIRouter, Depends, HTTPException
from auto_executor import is_executor_running, start_executor, stop_executor

router = APIRouter(prefix="/executor", tags=["Executor"])

@router.get("/status")
async def status():
    return {"running": is_executor_running()}

@router.post("/start")
async def start():
    ok = start_executor()
    return {"running": is_executor_running(), "ok": ok}

@router.post("/stop")
async def stop():
    ok = stop_executor()
    return {"running": is_executor_running(), "ok": ok}
