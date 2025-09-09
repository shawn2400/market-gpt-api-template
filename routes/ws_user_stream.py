# routes/ws_user_stream.py
from __future__ import annotations
from fastapi import APIRouter, Depends
from utils.auth import require_api_key
from utils import ws_user_stream as userws

router = APIRouter(prefix="/ws-user", tags=["WS"], dependencies=[Depends(require_api_key)])

@router.get("/status")
def ws_status():
    return {"ok": True, "stats": userws.get_stats()}

@router.post("/start")
def ws_start():
    userws.start()
    return {"ok": True, "started": userws.is_running()}

@router.post("/stop")
def ws_stop():
    userws.stop()
    return {"ok": True, "stopped": True}


