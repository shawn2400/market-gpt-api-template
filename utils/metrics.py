# utils/metrics.py
from __future__ import annotations
import time, threading
from collections import deque
from typing import Dict, Any

class _Metrics:
    def __init__(self, window_size: int = 1000):
        self.boot_ts = int(time.time())
        self._lock = threading.Lock()
        self.total_requests = 0
        self.total_errors = 0
        self.by_status: Dict[int, int] = {}
        self.latencies = deque(maxlen=window_size)
        self.recent_ts = deque(maxlen=5000)
        # NEW: trade cost metrics
        self.slippages = deque(maxlen=window_size)
        self.order_latencies = deque(maxlen=window_size)

    @staticmethod
    def _percentile(samples, p: float) -> float:
        if not samples: return 0.0
        s = sorted(samples)
        k = max(0, min(len(s)-1, int(round((p/100.0)*(len(s)-1)))))
        return float(s[k])

    @staticmethod
    def _median(samples) -> float:
        if not samples: return 0.0
        s, n = sorted(samples), len(samples)
        mid = n//2
        return float(s[mid]) if n%2 else float((s[mid-1]+s[mid])/2.0)

    def observe_request(self, status_code: int, duration_ms: float) -> None:
        with self._lock:
            self.total_requests += 1
            self.by_status[status_code] = self.by_status.get(status_code, 0)+1
            self.latencies.append(float(duration_ms))
            self.recent_ts.append(time.time())
            if status_code >= 500: self.total_errors += 1

    def observe_slippage(self, bps: float) -> None:
        with self._lock: self.slippages.append(float(bps))

    def observe_order_latency(self, ms: float) -> None:
        with self._lock: self.order_latencies.append(float(ms))

    def inc_err(self) -> None:
        with self._lock: self.total_errors += 1

    def get_metrics(self) -> Dict[str, Any]:
        now = int(time.time())
        with self._lock:
            lat_list = list(self.latencies)
            slip_list = list(self.slippages)
            ord_lat = list(self.order_latencies)
            avg_lat = sum(lat_list)/len(lat_list) if lat_list else 0.0
            mn, mx = (min(lat_list), max(lat_list)) if lat_list else (0.0,0.0)
            return {
                "boot_ts": self.boot_ts,
                "uptime_sec": now-self.boot_ts,
                "requests": {
                    "total": self.total_requests,
                    "errors_total": self.total_errors,
                    "by_status": dict(sorted(self.by_status.items())),
                    "rps_5s": round(sum(1 for t in self.recent_ts if t>=time.time()-5)/5.0,3),
                    "rps_60s": round(sum(1 for t in self.recent_ts if t>=time.time()-60)/60.0,3),
                },
                "latency_ms": {
                    "count": len(lat_list),
                    "avg": round(avg_lat,3),
                    "min": round(mn,3),
                    "max": round(mx,3),
                    "p50": round(self._median(lat_list),3),
                    "p95": round(self._percentile(lat_list,95),3),
                },
                "slippage_bps": {
                    "avg": round(sum(slip_list)/len(slip_list),3) if slip_list else 0.0,
                    "p95": round(self._percentile(slip_list,95),3) if slip_list else 0.0,
                },
                "order_latency_ms": {
                    "avg": round(sum(ord_lat)/len(ord_lat),2) if ord_lat else 0.0,
                    "p95": round(self._percentile(ord_lat,95),2) if ord_lat else 0.0,
                }
            }

metrics_tracker = _Metrics()






