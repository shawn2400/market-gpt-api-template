# utils/metrics.py
from __future__ import annotations
import threading, time
from typing import Any, Dict, List, Optional, Tuple

class _MetricsTracker:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._counters: Dict[str, float] = {}
        self._gauges: Dict[str, float] = {}
        self._hists: Dict[str, List[float]] = {}
        self._labels: Dict[str, Dict[Tuple[str, ...], float]] = {}  # name -> {(k=v, ...): val}

    def inc_counter(self, name: str, value: float = 1.0, labels: Optional[Dict[str,str]] = None) -> None:
        with self._lock:
            if labels:
                L = tuple(sorted((k, str(v)) for k, v in labels.items()))
                d = self._labels.setdefault(name, {})
                d[L] = d.get(L, 0.0) + value
            else:
                self._counters[name] = self._counters.get(name, 0.0) + value

    def set_gauge(self, name: str, value: float, labels: Optional[Dict[str,str]] = None) -> None:
        with self._lock:
            if labels:
                L = tuple(sorted((k, str(v)) for k, v in labels.items()))
                d = self._labels.setdefault(name, {})
                d[L] = float(value)
            else:
                self._gauges[name] = float(value)

    def observe_hist(self, name: str, value: float) -> None:
        with self._lock:
            arr = self._hists.setdefault(name, [])
            arr.append(float(value))
            # שמירה על זיכרון: נגביל ל-5000 דגימות לכל היותר
            if len(arr) > 5000:
                del arr[:len(arr) - 5000]

    def get_metrics(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "generated_ts": int(time.time()),
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "hists": {k: {"count": len(v),
                              "min": min(v) if v else None,
                              "max": max(v) if v else None,
                              "avg": (sum(v)/len(v)) if v else None}
                          for k, v in self._hists.items()},
                "labels": {
                    name: [{"labels": dict(L), "value": val} for L, val in d.items()]
                    for name, d in self._labels.items()
                }
            }

metrics_tracker = _MetricsTracker()









