# routes/status.py
from __future__ import annotations
import time
from typing import Dict, Any
from fastapi import APIRouter, Depends
from utils.auth import require_api_key

router = APIRouter(tags=["Status"], dependencies=[Depends(require_api_key)])

@router.get("/ws-user/status")
def ws_user_status() -> Dict[str, Any]:
    try:
        from utils import ws_user_stats
        st = ws_user_stats.status()
    except Exception as e:
        st = {"error": str(e), "note": "ws_user_stats module not available"}
    return {"ok": True, "time": time.time(), "ws_user": st}

@router.get("/executor/status")
def executor_status() -> Dict[str, Any]:
    try:
        import utils.auto_executor as ae
        from utils.metrics import snapshot
        st = {
            "running": bool(getattr(ae, "EXECUTOR_RUNNING", False)),
            "last_tick_ts": getattr(ae, "EXECUTOR_LAST_TS", None),
            "logs_size": len(getattr(ae, "EXECUTOR_LOGS", [])),
            "metrics": snapshot("exec."),
        }
    except Exception as e:
        st = {"error": str(e)}
    return {"ok": True, "time": time.time(), "executor": st}
