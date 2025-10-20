# utils/metrics_helpers.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import asyncio, time, threading, os
from typing import Dict, Tuple, Callable, Any, Optional
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.responses import PlainTextResponse

# ======== מינימל רישטרי בסטייל Prometheus exposition ========
# Counter/Gauge עם תוויות (labels), thread-safe, בלי תלות חיצונית.

class _MetricBase:
    __slots__ = ("name", "help", "labels", "_lock", "_store")
    def __init__(self, name: str, help: str, labels: Tuple[str, ...]):
        self.name = name
        self.help = help
        self.labels = labels or tuple()
        self._lock = threading.Lock()
        # mapping: label_tuple -> value
        self._store: Dict[Tuple[str, ...], float] = {}

    def _key(self, **label_values: str) -> Tuple[str, ...]:
        if not self.labels:
            return tuple()
        return tuple(str(label_values.get(k, "")) for k in self.labels)

    def _format_samples(self) -> str:
        # # HELP / # TYPE + דגימות (samples) לפי פורמט Prometheus
        lines = []
        if self.help:
            lines.append(f"# HELP {self.name} {self.help}")
        lines.append(f"# TYPE {self.name} {self._type}")
        with self._lock:
            if not self._store:
                # גם בלי תוויות – עדיין לפלוט ערך 0 כדי לא להיעלם
                if not self.labels:
                    self._store[tuple()] = self._zero()
            for k, v in self._store.items():
                if self.labels:
                    pairs = ",".join(f'{lbl}="{val}"' for lbl, val in zip(self.labels, k))
                    lines.append(f"{self.name}{{{pairs}}} {float(v)}")
                else:
                    lines.append(f"{self.name} {float(v)}")
        return "\n".join(lines)

    def _zero(self) -> float:
        return 0.0

class Counter(_MetricBase):
    _type = "counter"
    def inc(self, value: float = 1.0, **label_values: str) -> None:
        key = self._key(**label_values)
        with self._lock:
            self._store[key] = float(self._store.get(key, 0.0)) + float(value)

class Gauge(_MetricBase):
    _type = "gauge"
    def set(self, value: float, **label_values: str) -> None:
        key = self._key(**label_values)
        with self._lock:
            self._store[key] = float(value)

# רישטרי גלובלי
_REG: Dict[str, _MetricBase] = {}
_REG_LOCK = threading.Lock()

def _get_or_create(metric: _MetricBase) -> _MetricBase:
    with _REG_LOCK:
        if metric.name in _REG:
            return _REG[metric.name]
        _REG[metric.name] = metric
        return metric

def labeled_counter(name: str, help: str, labels: Tuple[str, ...] = tuple()) -> Callable[..., None]:
    """
    מחזיר פונקציה שניתן לקרוא לה כך:
        c = labeled_counter("x_total","help",labels=("reason",))
        c(reason="cidr")   # מגדיל ב-1
        c(3, reason="score")  # מגדיל ב-3
    """
    m = _get_or_create(Counter(name, help, labels))
    def _inc(value: float = 1.0, **label_values: str) -> None:
        assert isinstance(m, Counter)
        m.inc(value, **label_values)
    return _inc

def labeled_gauge(name: str, help: str, labels: Tuple[str, ...] = tuple()) -> Callable[..., None]:
    """
    מחזיר פונקציה שניתן לקרוא לה כך:
        g = labeled_gauge("score_gauge","help",labels=("network","symbol"))
        g(42, network="eth", symbol="USDT")
    """
    m = _get_or_create(Gauge(name, help, labels))
    def _set(value: float, **label_values: str) -> None:
        assert isinstance(m, Gauge)
        m.set(value, **label_values)
    return _set

# -------- Exposition --------
def _render_exposition() -> str:
    with _REG_LOCK:
        metrics = list(_REG.values())
    lines = []
    for m in metrics:
        lines.append(m._format_samples())
    return "\n".join(lines) + "\n"

# -------- Middleware: HTTP metrics קלות --------
# נמדוד:
#   http_requests_total{method,path,status}
#   http_request_seconds_sum / count (לטנטיות), עם תוויות method,path
_http_req_total = labeled_counter(
    "http_requests_total", "Total HTTP requests", labels=("method","path","status")
)
_http_req_seconds_sum = labeled_counter(
    "http_request_seconds_sum", "Sum of request latencies in seconds", labels=("method","path")
)
_http_req_seconds_count = labeled_counter(
    "http_request_seconds_count", "Count of requests measured for latency", labels=("method","path")
)

class HttpMetricsMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, paths_as_is: Optional[Tuple[str, ...]] = None):
        super().__init__(app)
        self.paths_as_is = tuple(paths_as_is or ())

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        # כדי לא לפוצץ קארדינליות, אפשר לקצר path
        label_path = path if path in self.paths_as_is else _normalize_path_for_metrics(path)
        method = (request.method or "GET").upper()
        t0 = time.monotonic()
        status = 500
        try:
            response: Response = await call_next(request)
            status = int(getattr(response, "status_code", 200) or 200)
            return response
        finally:
            dt = max(0.0, time.monotonic() - t0)
            _http_req_total(1, method=method, path=label_path, status=str(status))
            # latency: נשמור sum ו-count (היסטוגרמה אפשרית בעתיד)
            _http_req_seconds_sum(dt, method=method, path=label_path)
            _http_req_seconds_count(1, method=method, path=label_path)

def _normalize_path_for_metrics(path: str) -> str:
    # דרך שמרנית: נחתוך IDs נפוצים
    # /ops/ui/ticket?ticket_id=... → /ops/ui/ticket
    # /ops/approve?id=... → /ops/approve
    # /price/BTCUSDT → /price/:symbol
    if "/ops/ui/ticket" in path:
        return "/ops/ui/ticket"
    if path.startswith("/ops/approve"):
        return "/ops/approve"
    if path.startswith("/ops/reject"):
        return "/ops/reject"
    # דוגמה כללית: אם יש קטע שהוא hex/uuid ארוך, מחליפים ל-:id
    import re
    path = re.sub(r"/[0-9a-fA-F]{8,}", "/:id", path)
    # סמלים
    path = re.sub(r"/[A-Z]{3,15}USDT$", "/:symbol", path)
    return path

# -------- עטיפות למדידות של ספקים חיצוניים --------
_external_total = labeled_counter(
    "external_calls_total", "External provider calls", labels=("provider","op","status")
)
_external_seconds_sum = labeled_counter(
    "external_call_seconds_sum", "Sum of external call latencies", labels=("provider","op")
)
_external_seconds_count = labeled_counter(
    "external_call_seconds_count", "Count of external calls measured", labels=("provider","op")
)

async def measure_external_async(provider: str, op: str, awaitable):
    """
    שימוש:
        r = await measure_external_async("bitquery","query", client.post(...))
    מודד זמן, מסמן הצלחה/כשל, ומחזיר את תוצאת הקריאה המקורית.
    """
    t0 = time.monotonic()
    status = "ok"
    try:
        res = await awaitable
        return res
    except Exception:
        status = "err"
        raise
    finally:
        dt = max(0.0, time.monotonic() - t0)
        _external_total(1, provider=str(provider), op=str(op), status=status)
        _external_seconds_sum(dt, provider=str(provider), op=str(op))
        _external_seconds_count(1, provider=str(provider), op=str(op))

# -------- Mount /metrics --------
def mount_metrics(app, *, route: str = "/metrics") -> None:
    """
    מגדיר endpoint שמחזיר Prometheus exposition.
    אם PUBLIC_METRICS_REQUIRE_BEARER=1 — יידרש Authorization: Bearer <METRICS_BEARER>.
    """
    from fastapi import APIRouter, Request, HTTPException

    require_bearer = os.getenv("PUBLIC_METRICS_REQUIRE_BEARER", "1").lower() in ("1","true","yes","on")
    token = (os.getenv("METRICS_BEARER") or os.getenv("API_BEARER_TOKEN") or "").strip()

    router = APIRouter()
    @router.get(route)
    async def _metrics(req: Request):
        if require_bearer:
            auth = req.headers.get("Authorization","")
            if not (auth.startswith("Bearer ") and token and auth.split(" ",1)[1].strip() == token):
                raise HTTPException(status_code=401, detail="Unauthorized")
        body = _render_exposition()
        return PlainTextResponse(body, media_type="text/plain; version=0.0.4")

    app.include_router(router)
