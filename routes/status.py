# routes/status.py
from __future__ import annotations
from fastapi import APIRouter
from utils.runtime_counters import get_ws_status, get_exec_status

router = APIRouter(tags=["status"])

@router.get("/ws-user/status")
async def ws_user_status():
    return {"ok": True, "status": get_ws_status()}

@router.get("/executor/status")
async def executor_status():
    return {"ok": True, "status": get_exec_status()}



