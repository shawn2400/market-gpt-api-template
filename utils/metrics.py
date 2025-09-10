# utils/metrics.py
from __future__ import annotations
import time, threading
from collections import deque
from typing import Dict, Any, Deque, List, Optional

class _Metrics:
    def __init__(self, window_size: int = 2000):
        self.boot_ts = int(time.time())
        self._lock = threading.Lock()

        # Requests / API
        self.total_requests = 0
        self.total_errors = 0
        self.by_status: Dict[int, int] = {}
        self.latencies: Deque[float] = deque(maxlen=window_size)
        self.recent_ts: Deque[float] = deque(maxlen=5000)

        # Trade costs / ops
        self.slippages: Deque[float] = deque(maxlen=window_size)
        self.order_latencies: Deque[float] = deque(maxlen=window_size)

        # General counters & gauges (free-form)
        self.counters: Dict[str, int] = {}
        self.gauges: Dict[str, float] = {}

    @staticmethod
    def _percentile(samples: List[float], p: float) -> float:
        if not samples: return 0.0
        s = sorted(samples)
        k = max(0, min(len(s)-1, int(round((p/100.0)*(len(s)-1)))))
        return float(s[k])

    @staticmethod
    def _median(samples: List[float]) -> float:
        if not samples: return 0.0
        s, n = sorted(samples), len(samples)
        mid = n//2
        return float(s[mid]) if n%2 else float((s[mid-1]+s[mid])/2.0)

    # ===== Observers =====
    def observe_request(self, status_code: int, duration_ms: float) -> None:
        now = time.time()
        with self._lock:
            self.total_requests += 1
            self.by_status[status_code] = self.by_status.get(status_code, 0) + 1
            self.latencies.append(float(duration_ms))
            self.recent_ts.append(now)
            if status_code >= 500:
                self.total_errors += 1

    def observe_slippage(self, bps: float) -> None:
        with self._lock:
            self.slippages.append(float(bps))

    def observe_order_latency(self, ms: float) -> None:
        with self._lock:
            self.order_latencies.append(float(ms))

    # ===== Free-form counters & gauges =====
    def inc(self, key: str, n: int = 1) -> None:
        with self._lock:
            self.counters[key] = self.counters.get(key, 0) + int(n)

    def set_gauge(self, key: str, val: float) -> None:
        with self._lock:
            self.gauges[key] = float(val)

    # ===== Readout =====
    def get_metrics(self) -> Dict[str, Any]:
        now = int(time.time())
        with self._lock:
            lat_list = list(self.latencies)
            slip_list = list(self.slippages)
            ord_lat = list(self.order_latencies)

            avg_lat = (sum(lat_list)/len(lat_list)) if lat_list else 0.0
            mn, mx = (min(lat_list), max(lat_list)) if lat_list else (0.0, 0.0)

            return {
                "boot_ts": self.boot_ts,
                "uptime_sec": now - self.boot_ts,
                "requests": {
                    "total": self.total_requests,
                    "errors_total": self.total_errors,
                    "by_status": dict(sorted(self.by_status.items())),
                    "rps_5s": round(sum(1 for t in self.recent_ts if t >= time.time()-5)/5.0, 3),
                    "rps_60s": round(sum(1 for t in self.recent_ts if t >= time.time()-60)/60.0, 3),
                },
                "latency_ms": {
                    "count": len(lat_list),
                    "avg": round(avg_lat, 3),
                    "min": round(mn, 3),
                    "max": round(mx, 3),
                    "p50": round(self._median(lat_list), 3),
                    "p95": round(self._percentile(lat_list, 95), 3),
                    "p99": round(self._percentile(lat_list, 99), 3),
                },
                "slippage_bps": {
                    "avg": round(sum(slip_list)/len(slip_list), 3) if slip_list else 0.0,
                    "p95": round(self._percentile(slip_list, 95), 3) if slip_list else 0.0,
                },
                "order_latency_ms": {
                    "avg": round(sum(ord_lat)/len(ord_lat), 2) if ord_lat else 0.0,
                    "p95": round(self._percentile(ord_lat, 95), 2) if ord_lat else 0.0,
                    "p99": round(self._percentile(ord_lat, 99), 2) if ord_lat else 0.0,
                },
                "counters": dict(self.counters),
                "gauges": dict(self.gauges),
            }

metrics_tracker = _Metrics()







