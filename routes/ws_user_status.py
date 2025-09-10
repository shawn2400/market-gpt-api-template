# routes/ws_user_status.py
from __future__ import annotations
import time
from fastapi import APIRouter
from typing import Any, Dict

router = APIRouter(prefix="/status", tags=["status"])

# counters from runtime_counters
try:
    from utils.runtime_counters import ws_get_counters as _ws_get_counters
except Exception:
    def _ws_get_counters() -> Dict[str, Any]:
        return {"ws_up": 0, "reconnects": 0, "ewma_latency_ms": 0.0, "last_event_age_sec": None}

try:
    from utils.runtime_counters import exec_get_counters as _exec_get_counters
except Exception:
    def _exec_get_counters() -> Dict[str, Any]:
        return {"tick_ewma_ms": 0.0, "tick_p95_ms": None, "tick_p99_ms": None,
                "last_tick_age_sec": None, "timeouts_burst": 0,
                "no_trade_streak": 0, "current_interval": 0}

@router.get("/ws", summary="WebSocket user-stream counters (runtime)")
def ws_user_status() -> Dict[str, Any]:
    """
    מחזיר counters חיים של ה־WS מה־runtime_counters (טעינת-יתר קרובה לאפס).
    """
    return _ws_get_counters()

@router.get("/all", summary="Combined status (WS + Executor)")
def status_all() -> Dict[str, Any]:
    return {
        "ws": _ws_get_counters(),
        "executor": _exec_get_counters(),
        "ts": int(time.time())
    }

@router.get("/ping", summary="Liveness ping")
def ping() -> Dict[str, Any]:
    return {"ok": True, "ts": int(time.time())}







