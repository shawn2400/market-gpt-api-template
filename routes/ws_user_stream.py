# routes/ws_user_stream.py
from __future__ import annotations
from fastapi import APIRouter
from typing import Any, Dict

router = APIRouter(prefix="/ws-user", tags=["WS"])

def _try_import():
    try:
        from utils import ws_user_stream as wsus
        return wsus
    except Exception:
        return None

@router.get("/status")
def status() -> Dict[str, Any]:
    wsus = _try_import()
    if not wsus:
        return {"ok": True, "stats": {"running": False, "error": "module_not_loaded"}}
    return {"ok": True, "stats": wsus.status()}

@router.post("/start")
async def start():
    wsus = _try_import()
    if not wsus:
        return {"ok": False, "error": "module_not_loaded"}
    wsus.start()
    return {"ok": True, "started": True}

@router.post("/stop")
async def stop():
    wsus = _try_import()
    if not wsus:
        return {"ok": False, "error": "module_not_loaded"}
    await wsus.stop_async()
    return {"ok": True, "stopped": True}


