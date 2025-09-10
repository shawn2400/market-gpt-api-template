# utils/metrics.py
from __future__ import annotations
import os, time
from collections import deque
from typing import Optional, Dict, Any

try:
    from prometheus_client import Histogram, Counter, Gauge
except Exception:
    Histogram = Counter = Gauge = None  # type: ignore

def _percentile(values: deque[float], q: float) -> Optional[float]:
    if not values:
        return None
    arr = sorted(values)
    k = max(0, min(len(arr) - 1, int(round(q * (len(arr) - 1)))))
    return float(arr[k])

class _Noop:
    def labels(self, *a, **k): return self
    def observe(self, *a, **k): pass
    def inc(self, *a, **k): pass
    def set(self, *a, **k): pass

class MetricsTracker:
    def __init__(self):
        self.rolling_n = int(os.getenv("METRICS_ROLLING_N", "4096"))

        # Histograms (Prometheus). אפשר חישוב P95/P99 בצד PromQL (histogram_quantile)
        if Histogram:
            self.order_latency_ms = Histogram(
                "order_latency_ms",
                "Latency per order (ms)",
                buckets=(5,10,20,30,50,75,100,150,200,300,500,750,1000,2000,5000)
            )
            self.request_duration_ms = Histogram(
                "request_duration_ms",
                "Scan/request duration (ms)",
                ["status_code"],
                buckets=(10,20,30,50,75,100,150,200,300,500,750,1000,2000,5000,8000,12000)
            )
            self.order_latency_p95 = Gauge("order_latency_p95_ms", "Rolling P95 order latency (ms)")
            self.order_latency_p99 = Gauge("order_latency_p99_ms", "Rolling P99 order latency (ms)")
            self.request_p95 = Gauge("request_duration_p95_ms", "Rolling P95 request (ms)")
            self.request_p99 = Gauge("request_duration_p99_ms", "Rolling P99 request (ms)")
        else:
            self.order_latency_ms = self.request_duration_ms = _Noop()
            self.order_latency_p95 = self.order_latency_p99 = _Noop()
            self.request_p95 = self.request_p99 = _Noop()

        # Rolling windows (לגייג'ים)
        self._order_lat_samples: deque[float] = deque(maxlen=self.rolling_n)
        self._req_samples: deque[float] = deque(maxlen=self.rolling_n)

        # Counters כלליים
        if Counter:
            self.requests_total = Counter("requests_total", "Total requests", ["status_code"])
            self.orders_total = Counter("orders_total", "Total orders", ["result"])
        else:
            self.requests_total = self.orders_total = _Noop()

    def observe_order_latency(self, ms: float, result: str = "sent") -> None:
        try:
            self.order_latency_ms.observe(ms)
        except Exception:
            pass
        self._order_lat_samples.append(float(ms))
        # Rolling p95/p99
        p95 = _percentile(self._order_lat_samples, 0.95)
        p99 = _percentile(self._order_lat_samples, 0.99)
        if p95 is not None:
            try: self.order_latency_p95.set(p95)
            except Exception: pass
        if p99 is not None:
            try: self.order_latency_p99.set(p99)
            except Exception: pass
        try:
            self.orders_total.labels(result=result).inc()
        except Exception:
            pass

    def observe_request(self, status_code: int, ms: float) -> None:
        try:
            self.request_duration_ms.labels(status_code=str(status_code)).observe(ms)
        except Exception:
            pass
        self._req_samples.append(float(ms))
        p95 = _percentile(self._req_samples, 0.95)
        p99 = _percentile(self._req_samples, 0.99)
        if p95 is not None:
            try: self.request_p95.set(p95)
            except Exception: pass
        if p99 is not None:
            try: self.request_p99.set(p99)
            except Exception: pass
        try:
            self.requests_total.labels(status_code=str(status_code)).inc()
        except Exception:
            pass

    def get_snapshot(self) -> Dict[str, Any]:
        return {
            "order_latency_ms": {
                "p50": _percentile(self._order_lat_samples, 0.50),
                "p95": _percentile(self._order_lat_samples, 0.95),
                "p99": _percentile(self._order_lat_samples, 0.99),
                "n": len(self._order_lat_samples),
            },
            "request_duration_ms": {
                "p50": _percentile(self._req_samples, 0.50),
                "p95": _percentile(self._req_samples, 0.95),
                "p99": _percentile(self._req_samples, 0.99),
                "n": len(self._req_samples),
            },
        }

# אינסטנס יחיד
metrics_tracker = MetricsTracker()








