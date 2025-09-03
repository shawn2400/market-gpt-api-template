# utils/limiters.py
from __future__ import annotations
import time, threading
from typing import Dict

class TokenBucket:
    """טוקן־באקט מקומי (לפי מפתח), refill לינארי, thread-safe."""
    def __init__(self, capacity: int, refill_per_sec: float):
        self.capacity = max(1, int(capacity))
        self.refill = float(refill_per_sec)
        self._tokens: Dict[str, float] = {}
        self._last: Dict[str, float] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, tokens: float = 1.0) -> bool:
        now = time.monotonic()
        with self._lock:
            cur = self._tokens.get(key, self.capacity)
            last = self._last.get(key, now)
            # refill
            cur = min(self.capacity, cur + self.refill * max(0.0, now - last))
            if cur >= tokens:
                cur -= tokens
                self._tokens[key] = cur
                self._last[key] = now
                return True
            self._tokens[key] = cur
            self._last[key] = now
            return False

class Debouncer:
    """קוֹאָלֶסֶר: דילוג על אירועים צפופים מדי לפי key+חלון."""
    def __init__(self):
        self._last: Dict[str, float] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, min_interval_sec: float) -> bool:
        """
        True אם צריך לדלג (כלומר עדיין בתוך חלון), False אם מותר לבצע.
        """
        now = time.monotonic()
        with self._lock:
            last = self._last.get(key, 0.0)
            if now - last < max(0.0, min_interval_sec):
                return True
            self._last[key] = now
            return False

class RateLimiter:
    """N אירועים לכל חלון זמן (per key)."""
    def __init__(self, max_events: int, window_sec: float):
        self.max = max(1, int(max_events))
        self.win = float(window_sec)
        self._hits: Dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            arr = self._hits.setdefault(key, [])
            # ניקוי חלון
            cutoff = now - self.win
            while arr and arr[0] < cutoff:
                arr.pop(0)
            if len(arr) < self.max:
                arr.append(now)
                return True
            return False

