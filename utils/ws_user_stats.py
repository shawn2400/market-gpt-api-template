# utils/ws_user_stats.py
from __future__ import annotations
import time, threading, os
from typing import Dict, Any, Optional
from collections import deque
from .metrics import metrics_tracker as mx

_LOCK = threading.Lock()
_LAST_EVENT_TS: Optional[float] = None
_LAST_HEARTBEAT_TS: Optional[float] = None
_RECONNECTS = deque(maxlen=1024)

# Degrade→Mark-only TTL
_DEGRADE_UNTIL_TS: float = 0.0

def _now() -> float: return time.time()

def record_event(server_ts_ms: Optional[float] = None) -> None:
    """לקרוא כשמגיע אירוע WS (מחיר/הזמנה)."""
    global _LAST_EVENT_TS
    now = _now()
    with _LOCK:
        _LAST_EVENT_TS = now
        if server_ts_ms is not None:
            lag_ms = max(0.0, now * 1000.0 - float(server_ts_ms))
            mx.observe_order_latency(lag_ms)  # משתמשים בזה גם ל־WS latency
        mx.inc("ws.events", 1)

def record_heartbeat() -> None:
    global _LAST_HEARTBEAT_TS
    with _LOCK:
        _LAST_HEARTBEAT_TS = _now()
        mx.inc("ws.heartbeats", 1)

def record_reconnect() -> None:
    with _LOCK:
        _RECONNECTS.append(_now())
        mx.inc("ws.reconnects", 1)

def set_price_ttl(ttl_sec: float) -> None:
    mx.set_gauge("ws.price_ttl_sec", float(ttl_sec))

def _reconnects_in_window(window_sec: int) -> int:
    ref = _now() - window_sec
    return sum(1 for t in list(_RECONNECTS) if t >= ref)

def maybe_activate_degrade() -> bool:
    """מפעיל Mark-only אוטומטי על סמך כמות reconnects בחלון זמן."""
    global _DEGRADE_UNTIL_TS
    if os.getenv("WS_DEGRADE_MARK_ONLY", "1").lower() not in ("1", "true", "yes", "on"):
        return False
    lim = int(os.getenv("WS_DEGRADE_RECONNECTS", "6"))
    win = int(os.getenv("WS_DEGRADE_WINDOW_SEC", "300"))
    ttl = int(os.getenv("WS_DEGRADE_TTL_SEC", "180"))
    if _reconnects_in_window(win) >= lim:
        _DEGRADE_UNTIL_TS = max(_DEGRADE_UNTIL_TS, _now() + ttl)
        mx.inc("ws.degrade_activations", 1)
        return True
    return False

def mark_only_mode_active() -> bool:
    if _DEGRADE_UNTIL_TS <= 0: return False
    return _now() < _DEGRADE_UNTIL_TS

def status() -> Dict[str, Any]:
    return {
        "last_event_ts": _LAST_EVENT_TS,
        "last_heartbeat_ts": _LAST_HEARTBEAT_TS,
        "reconnects_5m": _reconnects_in_window(300),
        "reconnects_30m": _reconnects_in_window(1800),
        "degrade_active": mark_only_mode_active(),
        "degrade_until": _DEGRADE_UNTIL_TS if mark_only_mode_active() else None,
        "metrics": mx.get_metrics(),
    }

