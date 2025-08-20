# utils/metrics.py
from __future__ import annotations
import time
import threading
from collections import deque
from typing import Dict, Any


class _Metrics:
    """
    מטריקות פרודקשן קלילות ללא תלות חיצונית:
    - uptime, סה״כ בקשות/שגיאות
    - חלוקה לפי קודי סטטוס / method / path
    - RPS אחרונה (5s/60s)
    - זמני תגובה: ממוצע/מינ/מקס/חציון/95%
    """
    def __init__(self, window_size: int = 1000):
        self.boot_ts = int(time.time())
        self._lock = threading.Lock()

        # Counters
        self.total_requests = 0
        self.total_errors = 0
        self.by_status: Dict[int, int] = {}
        self.by_method: Dict[str, int] = {}
        self.by_path: Dict[str, int] = {}

        # Latency samples (ms)
        self.latencies = deque(maxlen=window_size)

        # Timestamps for RPS
        self.recent_ts = deque(maxlen=5000)  # שניות אחרונות

    # --- Internal helpers ---
    @staticmethod
    def _percentile(samples, p: float) -> float:
        if not samples:
            return 0.0
        s = sorted(samples)
        k = max(0, min(len(s)-1, int(round((p/100.0) * (len(s)-1)))))
        return float(s[k])

    @staticmethod
    def _median(samples) -> float:
        if not samples:
            return 0.0
        s = sorted(samples)
        n = len(s)
        mid = n // 2
        if n % 2 == 1:
            return float(s[mid])
        return float((s[mid-1] + s[mid]) / 2.0)

    # --- Public API used by middleware ---
    def observe_request(self, status_code: int, duration_ms: float,
                        method: str | None = None, path: str | None = None) -> None:
        with self._lock:
            self.total_requests += 1
            self.by_status[status_code] = self.by_status.get(status_code, 0) + 1
            self.latencies.append(float(duration_ms))
            self.recent_ts.append(time.time())

            if method:
                self.by_method[method] = self.by_method.get(method, 0) + 1
            if path:
                self.by_path[path] = self.by_path.get(path, 0) + 1

            if status_code >= 500:
                self.total_errors += 1

    def inc_err(self) -> None:
        with self._lock:
            self.total_errors += 1

    # --- Snapshot for endpoint ---
    def get_metrics(self) -> Dict[str, Any]:
        now = int(time.time())
        with self._lock:
            lat_list = list(self.latencies)
            count = len(lat_list)
            avg = sum(lat_list) / count if count else 0.0
            mn = min(lat_list) if count else 0.0
            mx = max(lat_list) if count else 0.0
            p50 = self._median(lat_list)
            p95 = self._percentile(lat_list, 95)

            # RPS: חלון 5s ו-60s
            tlist = list(self.recent_ts)
            cutoff_5 = time.time() - 5
            cutoff_60 = time.time() - 60
            r5 = sum(1 for t in tlist if t >= cutoff_5) / 5.0 if tlist else 0.0
            r60 = sum(1 for t in tlist if t >= cutoff_60) / 60.0 if tlist else 0.0

            return {
                "boot_ts": self.boot_ts,
                "uptime_sec": now - self.boot_ts,
                "requests": {
                    "total": self.total_requests,
                    "errors_total": self.total_errors,
                    "by_status": dict(sorted(self.by_status.items())),
                    "by_method": dict(sorted(self.by_method.items())),
                    "top_paths": dict(sorted(self.by_path.items(),
                                             key=lambda kv: kv[1], reverse=True)[:20]),
                    "rps_5s": round(r5, 3),
                    "rps_60s": round(r60, 3),
                },
                "latency_ms": {
                    "count": count,
                    "avg": round(avg, 3),
                    "min": round(mn, 3),
                    "max": round(mx, 3),
                    "p50": round(p50, 3),
                    "p95": round(p95, 3),
                },
            }


metrics_tracker = _Metrics()



