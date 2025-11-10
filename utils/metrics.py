# utils/metrics.py
from __future__ import annotations

import time
import threading
from typing import Dict, Any, Optional

try:  # pragma: no cover - Prometheus is optional in some environments
    from prometheus_client import Counter, Gauge  # type: ignore
except Exception:  # pragma: no cover
    class _NoopCounter:
        def inc(self, amount: float = 1.0) -> None:
            return None
    class _NoopGauge:
        def set(self, value: float) -> None:
            return None
        def set_function(self, fn):  # noqa: ANN001 - keep signature simple
            return None
    def Counter(*_args, **_kwargs):  # type: ignore
        return _NoopCounter()
    def Gauge(*_args, **_kwargs):  # type: ignore
        return _NoopGauge()


class _MetricsTracker:
    """
    Tracker קל משקל למטריקות JSON פנימיות (מקביל/משלים ל-Prometheus).
    משמר ספירות וגייג'ים לזמינות גם ללא Prometheus.
    """

    def __init__(self, max_series: int = 500):
        self._lock = threading.RLock()
        self._counters: Dict[str, float] = {}
        self._gauges: Dict[str, float] = {}
        self._meta: Dict[str, Any] = {"started_ts": time.time()}
        self._max_series = max_series

    # --- helpers ---
    @staticmethod
    def _lblkey(labels: Optional[Dict[str, Any]]) -> str:
        if not labels:
            return ""
        items = sorted((str(k), str(v)) for k, v in labels.items())
        return "|".join(f"{k}={v}" for k, v in items)

    @staticmethod
    def _compose(name: str, labels: Optional[Dict[str, Any]]) -> str:
        lk = _MetricsTracker._lblkey(labels)
        return name if not lk else f"{name}|{lk}"

    def _gc_if_needed(self, store: Dict[str, float]) -> None:
        if len(store) > self._max_series:
            for i, key in enumerate(sorted(store.keys())):
                if i * 2 >= len(store):
                    break
                store.pop(key, None)

    # --- counters ---
    def inc_counter(self, name: str, value: float = 1.0, labels: Optional[Dict[str, Any]] = None) -> None:
        key = self._compose(name, labels)
        with self._lock:
            self._counters[key] = self._counters.get(key, 0.0) + float(value)
            self._gc_if_needed(self._counters)

    # --- gauges ---
    def set_gauge(self, name: str, value: float, labels: Optional[Dict[str, Any]] = None) -> None:
        key = self._compose(name, labels)
        with self._lock:
            self._gauges[key] = float(value)
            self._gc_if_needed(self._gauges)

    # --- export ---
    def get_metrics(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "ok": True,
                "started_ts": self._meta.get("started_ts"),
                "now_ts": time.time(),
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
            }


# סינגלטון לשימוש פנימי/legacy
metrics_tracker = _MetricsTracker()


# Prometheus counters (לפי ההנחיות; Prometheus מוסיף _total ברילוד)
SL_REPLACE_ATTEMPT = Counter(
    "algogpt_sl_replace_attempt_total",
    "Safe SL replace attempts (place-then-cancel strategy).",
)
STOP_VALIDATION_FAIL = Counter(
    "algogpt_stop_validation_fail_total",
    "Failed stop validation (distance/tick) rejects.",
)
RISK_BLOCK = Counter(
    "algogpt_risk_block_total",
    "Requests blocked by risk/cooldown/BTC gate.",
)

ALGOGPT_UPTIME_SECONDS = Gauge(
    "algogpt_uptime_seconds",
    "Process uptime seconds.",
)
ALGOGPT_UPTIME_SECONDS.set_function(lambda: time.time() - metrics_tracker._meta.get("started_ts", time.time()))


__all__ = [
    "metrics_tracker",
    "SL_REPLACE_ATTEMPT",
    "STOP_VALIDATION_FAIL",
    "RISK_BLOCK",
    "ALGOGPT_UPTIME_SECONDS",
    "register_metrics",
]

_REGISTERED = False


def register_metrics() -> bool:
    """
    Placeholder hook so the host process can ensure module import occurred.
    Prometheus counters are singletons per process, so this function simply
    toggles a flag the first time it's called.
    """
    global _REGISTERED  # noqa: PLW0603
    if not _REGISTERED:
        _REGISTERED = True
    return _REGISTERED
