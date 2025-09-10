# routes/executor_status.py
from __future__ import annotations
from fastapi import APIRouter
from utils.runtime_counters import get_executor_status

router = APIRouter(prefix="", tags=["status"])

@router.get("/executor/status")
async def executor_status():
    """
    מחזיר: EWMA/p50/p95/p99 לזמן tick, timeouts_last_60s, trades_sent_60s,
    current_interval, no_trade_streak, degrade_active.
    """
    return {"ok": True, "status": get_executor_status()}
