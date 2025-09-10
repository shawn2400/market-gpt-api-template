# routes/ws_user_status.py
from __future__ import annotations
import os, time
from typing import Any, Dict
from fastapi import APIRouter, Response

router = APIRouter(prefix="/status", tags=["status"])

# Fallback-safe imports
try:
    from utils.runtime_counters import ws_get_counters as _ws_get_counters
except Exception:
    def _ws_get_counters() -> Dict[str, Any]:
        return {"ws_up": 0, "reconnects": 0, "ewma_latency_ms": 0.0, "last_event_age_sec": None}

try:
    from utils.runtime_counters import exec_get_counters as _exec_get_counters
except Exception:
    def _exec_get_counters() -> Dict[str, Any]:
        return {
            "tick_ewma_ms": 0.0,
            "tick_p95_ms": None,
            "tick_p99_ms": None,
            "last_tick_age_sec": None,
            "timeouts_burst": 0,
            "no_trade_streak": 0,
            "current_interval": 0,
        }

# Thresholds (ENV-aligned)
TTL_WARN_SEC            = int(os.getenv("STATUS_PRICE_TTL_ALERT_SEC", "10"))
EXEC_TICK_STALE_WARN_SEC= int(os.getenv("EXEC_TICK_STALE_WARN_SEC", "30"))
TIMEOUT_BURST_ALERT     = int(os.getenv("EXEC_TIMEOUT_BURST_ALERT", "3"))

def _classify_ws(c: Dict[str, Any]) -> Dict[str, Any]:
    state = "OK"
    reasons: list[str] = []
    if int(c.get("ws_up") or 0) == 0:
        state = "PAUSE"
        reasons.append("ws_down")
    ttl = c.get("last_event_age_sec")
    if isinstance(ttl, (int, float)) and ttl is not None:
        if ttl > TTL_WARN_SEC * 3:
            state = "PAUSE"
            reasons.append(f"ttl>{TTL_WARN_SEC*3}")
        elif ttl > TTL_WARN_SEC and state != "PAUSE":
            state = "WARN"
            reasons.append(f"ttl>{TTL_WARN_SEC}")
    return {"state": state, "reasons": reasons or ["healthy"]}

def _classify_executor(c: Dict[str, Any]) -> Dict[str, Any]:
    state = "OK"
    reasons: list[str] = []
    age = c.get("last_tick_age_sec")
    if isinstance(age, (int, float)) and age is not None and age > EXEC_TICK_STALE_WARN_SEC:
        state = "WARN"
        reasons.append(f"last_tick_age_sec>{EXEC_TICK_STALE_WARN_SEC}")
    tb = int(c.get("timeouts_burst") or 0)
    if tb >= TIMEOUT_BURST_ALERT:
        state = "WARN"
        reasons.append(f"timeouts_burst>={TIMEOUT_BURST_ALERT}")
    return {"state": state, "reasons": reasons or ["healthy"]}

def _combine_state(ws_state: str, exec_state: str) -> str:
    # PAUSE > WARN > OK
    order = {"PAUSE": 3, "WARN": 2, "OK": 1}
    return ws_state if order[ws_state] >= order[exec_state] else exec_state

@router.get("/ws", summary="WebSocket user-stream counters (runtime)")
def ws_user_status(response: Response) -> Dict[str, Any]:
    """
    מחזיר Counters חיים של ה־WS עם סיווג מצב (OK/WARN/PAUSE).
    """
    response.headers["Cache-Control"] = "no-store, max-age=0"
    ws = _ws_get_counters()
    cls = _classify_ws(ws)
    return {
        "ok": True,
        "ts": int(time.time()),
        "version": os.getenv("ALGOGPT_VERSION", ""),
        "ws": ws,
        **cls,
    }

@router.get("/all", summary="Combined status (WS + Executor)")
def status_all(response: Response) -> Dict[str, Any]:
    """
    סטטוס משולב (WS + Executor) עם דירוג מצב ומקורות.
    """
    response.headers["Cache-Control"] = "no-store, max-age=0"
    ws = _ws_get_counters()
    ex = _exec_get_counters()

    ws_cls = _classify_ws(ws)
    ex_cls = _classify_executor(ex)
    combined_state = _combine_state(ws_cls["state"], ex_cls["state"])

    return {
        "ok": True,
        "ts": int(time.time()),
        "version": os.getenv("ALGOGPT_VERSION", ""),
        "state": combined_state,
        "components": {
            "ws": {"data": ws, **ws_cls},
            "executor": {"data": ex, **ex_cls},
        },
    }

@router.get("/ping", summary="Liveness ping")
def ping(response: Response) -> Dict[str, Any]:
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return {"ok": True, "ts": int(time.time())}








