# utils/runtime_counters.py
from __future__ import annotations
import os, time, math, threading
from collections import deque
from typing import Dict, Any, Optional

# ==== ENV ====
METRICS_WINDOW_SIZE      = int(os.getenv("METRICS_WINDOW_SIZE", "2000"))
WS_LAT_EWMA_ALPHA        = float(os.getenv("WS_LAT_EWMA_ALPHA", "0.2"))
EXEC_TICK_EWMA_ALPHA     = float(os.getenv("EXEC_TICK_EWMA_ALPHA", "0.2"))

# Ops / Drift (נגיש למדיניות מינוף)
_PRICE_DRIFT_LAST_BPS: float = 0.0
_PRICE_DRIFT_LAST_TS: float = 0.0

# ==== WS counters (user-stream) ====
_ws_lock = threading.Lock()
_ws_up: int = 0
_ws_last_event_ts: float = 0.0
_ws_reconnects: int = 0
_ws_ewma_lat_ms: float = 0.0

def ws_note_up(up: bool) -> None:
    global _ws_up
    with _ws_lock:
        _ws_up = 1 if up else 0

def ws_note_reconnect() -> None:
    global _ws_reconnects
    with _ws_lock:
        _ws_reconnects += 1

def ws_note_event(latency_ms: Optional[float] = None) -> None:
    global _ws_last_event_ts, _ws_ewma_lat_ms
    now = time.time()
    with _ws_lock:
        _ws_last_event_ts = now
        if latency_ms is not None:
            _ws_ewma_lat_ms = (1.0 - WS_LAT_EWMA_ALPHA) * _ws_ewma_lat_ms + WS_LAT_EWMA_ALPHA * float(latency_ms)

def ws_get_counters() -> Dict[str, Any]:
    with _ws_lock:
        return {
            "ws_up": _ws_up,
            "reconnects": _ws_reconnects,
            "ewma_latency_ms": round(_ws_ewma_lat_ms, 2),
            "last_event_age_sec": round(max(0.0, time.time() - _ws_last_event_ts), 2) if _ws_last_event_ts else None,
        }

# ==== EXEC counters (auto-executor) ====
_exec_lock = threading.Lock()
_exec_ewma_dt_ms: float = 0.0
_exec_last_tick_ts: float = 0.0
_exec_dt_hist: deque = deque(maxlen=METRICS_WINDOW_SIZE)
_exec_timeouts_burst: int = 0
_exec_no_trade_streak: int = 0
_exec_current_interval: int = 0

def exec_on_tick_stop(*, dt_ms: float, current_interval: int, no_trade_streak: int) -> None:
    global _exec_ewma_dt_ms, _exec_last_tick_ts, _exec_timeouts_burst, _exec_no_trade_streak, _exec_current_interval
    now = time.time()
    with _exec_lock:
        _exec_last_tick_ts = now
        _exec_dt_hist.append(float(dt_ms))
        _exec_ewma_dt_ms = (1.0 - EXEC_TICK_EWMA_ALPHA) * _exec_ewma_dt_ms + EXEC_TICK_EWMA_ALPHA * float(dt_ms)
        _exec_no_trade_streak = int(no_trade_streak)
        _exec_current_interval = int(current_interval)

def exec_on_batch_timeout() -> None:
    global _exec_timeouts_burst
    with _exec_lock:
        _exec_timeouts_burst += 1

def exec_on_trade_sent(symbol: str) -> None:
    # hook אופציונלי; לא נחזיר כלום. נשמר לעתיד.
    return None

def exec_get_counters() -> Dict[str, Any]:
    with _exec_lock:
        p95 = _percentile(_exec_dt_hist, 95.0)
        p99 = _percentile(_exec_dt_hist, 99.0)
        return {
            "tick_ewma_ms": round(_exec_ewma_dt_ms, 2),
            "tick_p95_ms": round(p95, 2) if p95 is not None else None,
            "tick_p99_ms": round(p99, 2) if p99 is not None else None,
            "last_tick_age_sec": round(max(0.0, time.time() - _exec_last_tick_ts), 2) if _exec_last_tick_ts else None,
            "timeouts_burst": _exec_timeouts_burst,
            "no_trade_streak": _exec_no_trade_streak,
            "current_interval": _exec_current_interval,
        }

def _percentile(d: deque, p: float) -> Optional[float]:
    if not d:
        return None
    arr = sorted(d)
    if len(arr) == 1:
        return arr[0]
    k = (len(arr)-1) * (float(p)/100.0)
    f = math.floor(k); c = math.ceil(k)
    if f == c: return float(arr[int(k)])
    return float(arr[f] + (k - f) * (arr[c] - arr[f]))

# ==== Ops tick safe ====
def ops_tick_safe() -> None:
    # שמור כריק; במערכת שלך אתה כבר מחשב דריפט/אזהרות. משאירים hook תואם.
    return None

# ==== Price drift getters/setters (למדיניות מינוף) ====
def price_set_last_drift_bps(bps: float) -> None:
    global _PRICE_DRIFT_LAST_BPS, _PRICE_DRIFT_LAST_TS
    _PRICE_DRIFT_LAST_BPS = float(bps)
    _PRICE_DRIFT_LAST_TS = time.time()

def price_get_last_drift_bps(max_age_sec: int = 60) -> float:
    if _PRICE_DRIFT_LAST_TS == 0.0:
        return 0.0
    age = time.time() - _PRICE_DRIFT_LAST_TS
    return _PRICE_DRIFT_LAST_BPS if age <= max_age_sec else 0.0







