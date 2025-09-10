# utils/ws_user_stats.py
from __future__ import annotations
import time
from typing import Any, Dict, Optional
from .metrics import inc, set_gauge, observe_ms, mark, snapshot

_last_event_ts: Optional[float] = None
_last_heartbeat_ts: Optional[float] = None
_last_reconnect_ts: Optional[float] = None

def record_event(server_ts_ms: Optional[float] = None) -> None:
    global _last_event_ts
    now = time.time()
    _last_event_ts = now
    mark("ws.last_event")
    inc("ws.events")
    if server_ts_ms is not None:
        lag_ms = max(0.0, now * 1000.0 - float(server_ts_ms))
        observe_ms("ws.latency_ms", lag_ms)

def record_heartbeat() -> None:
    global _last_heartbeat_ts
    _last_heartbeat_ts = time.time()
    mark("ws.last_heartbeat")

def record_reconnect() -> None:
    global _last_reconnect_ts
    _last_reconnect_ts = time.time()
    inc("ws.reconnects")

def set_price_ttl(ttl_sec: float) -> None:
    set_gauge("ws.price_ttl_sec", ttl_sec)

def status() -> Dict[str, Any]:
    return {
        "last_event_ts": _last_event_ts,
        "last_heartbeat_ts": _last_heartbeat_ts,
        "last_reconnect_ts": _last_reconnect_ts,
        "metrics": snapshot("ws."),
    }
