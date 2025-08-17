# utils/metrics.py
import time
import threading

class _Metrics:
    def __init__(self):
        self._lock = threading.Lock()
        self.boot_ts = int(time.time())
        self.requests = 0
        self.errors = 0

    def record_request(self):
        with self._lock:
            self.requests += 1

    def record_error(self):
        with self._lock:
            self.errors += 1

    def get_metrics(self):
        with self._lock:
            return {
                "boot_ts": self.boot_ts,
                "uptime_sec": int(time.time()) - self.boot_ts,
                "requests": self.requests,
                "errors": self.errors,
            }

metrics_tracker = _Metrics()

