# utils/time_sync.py
from __future__ import annotations
import time, threading, logging, os
from typing import Optional
import httpx

logger = logging.getLogger("algogpt.time_sync")

_BINANCE_BASE = (os.getenv("BINANCE_FUTURES_HTTP_BASE") or "https://fapi.binance.com").rstrip("/")

_offset_ms: float = 0.0
_last_sync_mono: float = 0.0
_lock = threading.Lock()

_RECV_WINDOW_MS = int(os.getenv("BINANCE_RECV_WINDOW", "45000"))
_SYNC_TIMEOUT = float(os.getenv("TIME_SYNC_TIMEOUT_SEC", "3.0"))
_SYNC_SKEW_LIMIT_MS = int(os.getenv("TIME_SYNC_SKEW_LIMIT_MS", "2000"))

def _local_time_ms() -> int:
    return int(time.time() * 1000)

def _fetch_server_time_ms() -> int:
    with httpx.Client(timeout=_SYNC_TIMEOUT) as c:
        r = c.get(f"{_BINANCE_BASE}/fapi/v1/time")
        r.raise_for_status()
        js = r.json()
        return int(js.get("serverTime"))

def sync_now() -> None:
    global _offset_ms, _last_sync_mono
    try:
        t0 = _local_time_ms()
        srv = _fetch_server_time_ms()
        t1 = _local_time_ms()
        mid = (t0 + t1) // 2
        est_offset = float(srv - mid)
        with _lock:
            _offset_ms = est_offset
            _last_sync_mono = time.monotonic()
        if abs(est_offset) > _SYNC_SKEW_LIMIT_MS:
            logger.warning({"event": "time_sync_skew_large", "offset_ms": est_offset})
        else:
            logger.info({"event": "time_sync_ok", "offset_ms": round(est_offset, 2)})
    except Exception as e:
        logger.warning({"event": "time_sync_failed", "error": str(e)})

def start_background_sync(interval_sec: int = 1800) -> None:
    def _bg():
        while True:
            try:
                time.sleep(max(60, interval_sec))
                sync_now()
            except Exception:
                time.sleep(60)
    threading.Thread(target=_bg, name="time_sync_bg", daemon=True).start()

def ensure_fresh_sync(max_age_sec: int = 3600) -> None:
    with _lock:
        age = time.monotonic() - _last_sync_mono
    if age > max(30, max_age_sec):
        sync_now()

def server_time_ms() -> int:
    with _lock:
        off = _offset_ms
    return int(_local_time_ms() + off)

def last_server_time_ms() -> Optional[int]:
    with _lock:
        seen = _last_sync_mono
    if seen <= 0:
        return None
    return server_time_ms()

def recv_window_ms() -> int:
    return int(_RECV_WINDOW_MS)

__all__ = [
    "sync_now", "start_background_sync", "ensure_fresh_sync",
    "server_time_ms", "last_server_time_ms", "recv_window_ms",
]


