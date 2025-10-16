# utils/metrics_utils.py
from __future__ import annotations
import time
from typing import Callable, TypeVar, Any, Optional
try:
    from utils.metrics_tracker import observe_http_latency
except Exception:
    def observe_http_latency(_s: float) -> None:  # no-op fallback
        pass

F = TypeVar("F", bound=Callable[..., Any])

def observe_http(func: F) -> F:
    """
    דקורטור למדידת השהיית פונקציה (בד"כ IO/HTTP) והזנת ההיסטוגרמה.
    שימוש:
        @observe_http
        async def fetch(...): ...
    או סינכרוני. אין תלות חיצונית.
    """
    if hasattr(func, "__call__"):
        if getattr(func, "__code__", None) and func.__code__.co_flags & 0x80:  # async
            async def _aw(*args, **kwargs):
                t0 = time.perf_counter()
                try:
                    return await func(*args, **kwargs)
                finally:
                    observe_http_latency(time.perf_counter() - t0)
            return _aw  # type: ignore[return-value]
        else:
            def _w(*args, **kwargs):
                t0 = time.perf_counter()
                try:
                    return func(*args, **kwargs)
                finally:
                    observe_http_latency(time.perf_counter() - t0)
            return _w  # type: ignore[return-value]
    return func

class http_timer:
    """
    קונטקסט־מנג'ר למדידה נקודתית:
        with http_timer():
            ...code...
    """
    def __enter__(self):
        self._t0 = time.perf_counter()
        return self
    def __exit__(self, exc_type, exc, tb):
        observe_http_latency(time.perf_counter() - self._t0)
        return False
