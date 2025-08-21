# routes/executor.py
from __future__ import annotations
from typing import Any
from fastapi import APIRouter, Depends
from pydantic import BaseModel

try:
    from utils.auth import require_bearer_token
except Exception:
    def require_bearer_token():
        return None

router = APIRouter(tags=["Executor"], dependencies=[Depends(require_bearer_token)])

class ExecutorStatus(BaseModel):
    ok: bool
    running: bool

class ExecutorActionResponse(BaseModel):
    ok: bool
    status: str | None = None
    error: str | None = None

@router.get("/executor/status", response_model=ExecutorStatus)
def executor_status() -> ExecutorStatus:
    try:
        from utils.auto_executor import is_executor_running
        running = bool(is_executor_running())
    except Exception:
        running = False
    return ExecutorStatus(ok=True, running=running)

@router.post("/executor/start", response_model=ExecutorActionResponse)
async def executor_start() -> ExecutorActionResponse:
    try:
        from utils.auto_executor import start_executor
        start_executor()
        return ExecutorActionResponse(ok=True, status="started")
    except Exception as e:
        return ExecutorActionResponse(ok=False, error=str(e))

@router.post("/executor/stop", response_model=ExecutorActionResponse)
async def executor_stop() -> ExecutorActionResponse:
    try:
        from utils.auto_executor import stop_executor
        stop_executor()
        return ExecutorActionResponse(ok=True, status="stopped")
    except Exception as e:
        return ExecutorActionResponse(ok=False, error=str(e))





