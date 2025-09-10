# routes/ws_user_status.py
from __future__ import annotations
from fastapi import APIRouter
from utils.runtime_counters import get_ws_status

router = APIRouter(prefix="", tags=["status"])

@router.get("/ws-user/status")
async def ws_user_status():
    """
    מחזיר: ewma latency, reconnects, last_event_ts, ttl_sec, up.
    """
    return {"ok": True, "status": get_ws_status()}
