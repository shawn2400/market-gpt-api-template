# utils/metrics.py
from __future__ import annotations
import time, threading
from typing import Dict, Any, Optional, Tuple

class _MetricsTracker:
    """
    טרקר קל משקל למטריקות JSON פנימיות (מקביל/משלים ל-Prometheus).
    תומך: counter, gauge, עם/בלי labels (לייבלים נשמרים כמפתח משורשר).
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
        if not labels: return ""
        # סדר דטרמיניסטי כדי ליצור מפתח יציב
        items = sorted((str(k), str(v)) for k, v in labels.items())
        return "|".join(f"{k}={v}" for k, v in items)

    @staticmethod
    def _compose(name: str, labels: Optional[Dict[str, Any]]) -> str:
        lk = _MetricsTracker._lblkey(labels)
        return name if not lk else f"{name}|{lk}"

    def _gc_if_needed(self, store: Dict[str, float]) -> None:
        # הגבלת קרדינליות פנימית (failsafe)
        if len(store) > self._max_series:
            # מוחקים את הישנים ביותר לפי זמן התחלה (פשוט: נחתוך חצי)
            # לשמירה על פשטות, נמחק את החצי הראשון של הרשימה הממוינת אלפביתית.
            for i, k in enumerate(sorted(store.keys())):
                if i * 2 >= len(store): break
                store.pop(k, None)

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

# סינגלטון
metrics_tracker = _MetricsTracker()









