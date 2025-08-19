# routes/executor.py
from __future__ import annotations
from typing import Any, Dict
from fastapi import APIRouter, Depends

try:
    from utils.auth import require_bearer_token  # type: ignore
except Exception:
    def require_bearer_token():
        return None

router = APIRouter(tags=["Scan"], dependencies=[Depends(require_bearer_token)])

@router.get("/executor/status", operation_id="getExecutorStatus")
def executor_status() -> Dict[str, Any]:
    try:
        from utils.auto_executor import is_executor_running
        running = bool(is_executor_running())
    except Exception:
        running = False
    return {"ok": True, "running": running}

@router.post("/executor/start", operation_id="postExecutorStart")
async def executor_start():
    try:
        from utils.auto_executor import start_executor
        start_executor()
        return {"ok": True, "status": "started"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@router.post("/executor/stop", operation_id="postExecutorStop")
async def executor_stop():
    try:
        from utils.auto_executor import stop_executor
        stop_executor()
        return {"ok": True, "status": "stopped"}
    except Exception as e:
        return {"ok": False, "error": str(e)}



