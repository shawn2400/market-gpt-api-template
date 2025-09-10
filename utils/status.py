# utils/status.py
from __future__ import annotations
import time
from typing import Optional, Dict, Any

_ws_user_state: Dict[str, Any] = {}
_executor_state: Dict[str, Any] = {}

def update_ws_user(*, reconnects: Optional[int] = None, last_event_ts: Optional[float] = None,
                   ttl_sec: Optional[float] = None, stream_state: Optional[str] = None) -> None:
    now = time.time()
    if reconnects is not None:
        _ws_user_state["reconnects"] = int(reconnects)
    if last_event_ts is not None:
        _ws_user_state["last_event_ts"] = float(last_event_ts)
    if ttl_sec is not None:
        _ws_user_state["ttl_sec"] = float(ttl_sec)
    if stream_state is not None:
        _ws_user_state["state"] = str(stream_state)
    _ws_user_state["updated_ts"] = now

def get_ws_user_status() -> Dict[str, Any]:
    return dict(_ws_user_state)

def update_executor(*, running: Optional[bool] = None, ewma_ms: Optional[float] = None,
                    last_tick_ms: Optional[float] = None, interval_sec: Optional[int] = None,
                    time_budget_sec: Optional[float] = None, last_tick_ts: Optional[float] = None,
                    last_batch_timeout: Optional[bool] = None, no_trade_streak: Optional[int] = None) -> None:
    now = time.time()
    if running is not None:
        _executor_state["running"] = bool(running)
    if ewma_ms is not None:
        _executor_state["ewma_ms"] = float(ewma_ms)
    if last_tick_ms is not None:
        _executor_state["last_tick_ms"] = float(last_tick_ms)
    if interval_sec is not None:
        _executor_state["interval_sec"] = int(interval_sec)
    if time_budget_sec is not None:
        _executor_state["time_budget_sec"] = float(time_budget_sec)
    if last_tick_ts is not None:
        _executor_state["last_tick_ts"] = float(last_tick_ts)
    if last_batch_timeout is not None:
        _executor_state["last_batch_timeout"] = bool(last_batch_timeout)
    if no_trade_streak is not None:
        _executor_state["no_trade_streak"] = int(no_trade_streak)
    _executor_state["updated_ts"] = now

def get_executor_status() -> Dict[str, Any]:
    return dict(_executor_state)
