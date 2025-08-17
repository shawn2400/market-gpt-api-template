# utils/metrics.py
from __future__ import annotations
import time
import threading

class _Metrics:
    def __init__(self):
        self.boot = int(time.time())
        self._lock = threading.Lock()
        self.requests = 0
        self.errors = 0

    def inc_req(self):
        with self._lock:
            self.requests += 1

    def inc_err(self):
        with self._lock:
            self.errors += 1

    def get_metrics(self):
        now = int(time.time())
        return {
            "boot_ts": self.boot,
            "uptime_sec": now - self.boot,
            "requests": self.requests,
            "errors": self.errors,
        }

metrics_tracker = _Metrics()


