# routes/ws_user_status.py
from __future__ import annotations
from fastapi import APIRouter
from typing import Dict, Any

router = APIRouter(prefix="/ws-user", tags=["status"])

try:
    from utils.runtime_counters import ws_get_counters
except Exception:
    def ws_get_counters() -> Dict[str, Any]:
        return {"ws_up": 0, "reconnects": 0, "ewma_latency_ms": 0.0, "last_event_age_sec": None}

@router.get("/status")
def ws_status():
    return {"ok": True, "counters": ws_get_counters()}

@router.get("/ping")
def ws_ping():
    return {"ok": True, "src": "ws_user_status", "counters": ws_get_counters()}






