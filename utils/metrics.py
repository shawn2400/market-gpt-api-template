import time
from typing import Dict

class MetricsTracker:
    def __init__(self) -> None:
        self.boot_ts = int(time.time())
        self.requests = 0
        self.errors = 0

    def record_request(self) -> None:
        self.requests += 1

    def record_error(self) -> None:
        self.errors += 1

    def get_metrics(self) -> Dict[str, int]:
        now = int(time.time())
        return {
            "boot_ts": self.boot_ts,
            "uptime_sec": now - self.boot_ts,
            "requests": self.requests,
            "errors": self.errors,
        }

metrics_tracker = MetricsTracker()


