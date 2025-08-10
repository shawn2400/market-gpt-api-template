# server/metrics.py
from __future__ import annotations
import os
import time
import threading
from typing import Optional, Dict, Any, Callable

# Prometheus client
from prometheus_client import (
    Counter, Gauge, Histogram, CollectorRegistry,
    CONTENT_TYPE_LATEST, generate_latest, PROCESS_COLLECTOR, PLATFORM_COLLECTOR
)

# ===== Registry (תומך במצב מרובה-תהליכים אם צריך) =====
PROMETHEUS_MULTIPROC = os.getenv("PROMETHEUS_MULTIPROC_DIR")  # אם מגדירים => gunicorn multiproc
if PROMETHEUS_MULTIPROC:
    # במצב multiproc, לא משתמשים ב-Process/Platform collectors רגילים
    from prometheus_client import values
    values.ValueClass = values.MultiProcessValue  # type: ignore
    REGISTRY = CollectorRegistry()
else:
    REGISTRY = CollectorRegistry()
    PROCESS_COLLECTOR(REGISTRY)
    PLATFORM_COLLECTOR(REGISTRY)

# ===== Metrics =====
REQUESTS = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["handler", "method", "code"],
    registry=REGISTRY,
)
REQUEST_LATENCY = Histogram(
    "http_request_latency_seconds",
    "HTTP request latency (seconds)",
    ["handler", "method"],
    buckets=(0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 4, 8),
    registry=REGISTRY,
)

BINANCE_ERRORS = Counter(
    "binance_errors_total",
    "Total Binance API errors by code group",
    ["group"],  # e.g., 403, 418, 429, 5xx, other
    registry=REGISTRY,
)
BINANCE_PINGS_OK = Counter(
    "binance_ping_ok_total",
    "Count of successful Binance ping checks",
    registry=REGISTRY,
)
BINANCE_PINGS_FAIL = Counter(
    "binance_ping_fail_total",
    "Count of failed Binance ping checks",
    registry=REGISTRY,
)
TIME_OFFSET_MS = Gauge(
    "binance_time_offset_ms",
    "Current measured timestamp offset vs Binance (ms)",
    registry=REGISTRY,
)
WS_CONNECTED = Gauge(
    "ws_connected",
    "Is multi-stream WS connected (1) or not (0)",
    registry=REGISTRY,
)
WS_SYMBOLS = Gauge(
    "ws_symbols_count",
    "Number of symbols subscribed on WS",
    registry=REGISTRY,
)
WS_STALE_COUNT = Gauge(
    "ws_stale_symbols_count",
    "How many symbols are stale beyond threshold",
    registry=REGISTRY,
)
TRADE_RESULT = Counter(
    "trades_total",
    "Trades by status and side",
    ["status", "side"],  # status=success|error, side=LONG|SHORT|unknown
    registry=REGISTRY,
)
TRADE_LATENCY = Histogram(
    "trade_latency_seconds",
    "End-to-end trade execution latency",
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 4, 8, 16),
    registry=REGISTRY,
)
ALLOWLIST_OK = Gauge(
    "egress_ip_allowlist_ok",
    "Egress IP is in allowlist (1) or not (0)",
    registry=REGISTRY,
)

# ===== Public API (קריאות פשוטות מהקוד שלך) =====
def metrics_binance_error(http_code: int | str) -> None:
    """רשום שגיאת Binance לקבוצות עיקריות."""
    try:
        c = int(str(http_code).split()[0])
    except Exception:
        c = 0
    if c in (403, 418, 429):
        BINANCE_ERRORS.labels(str(c)).inc()
    elif 500 <= c <= 599:
        BINANCE_ERRORS.labels("5xx").inc()
    else:
        BINANCE_ERRORS.labels("other").inc()

def metrics_binance_ping(ok: bool) -> None:
    (BINANCE_PINGS_OK if ok else BINANCE_PINGS_FAIL).inc()

def metrics_time_offset_ms(offset_ms: Optional[int]) -> None:
    if offset_ms is None:
        return
    TIME_OFFSET_MS.set(int(offset_ms))

def metrics_ws_update(connected: bool, symbols_count: int, stale_count: int) -> None:
    WS_CONNECTED.set(1 if connected else 0)
    WS_SYMBOLS.set(max(0, int(symbols_count)))
    WS_STALE_COUNT.set(max(0, int(stale_count)))

def metrics_allowlist(ok: bool) -> None:
    ALLOWLIST_OK.set(1 if ok else 0)

def metrics_trade_record(status: str, side: str, latency_seconds: Optional[float] = None) -> None:
    s = status.lower().strip() if status else "unknown"
    sd = side.upper().strip() if side else "unknown"
    if s not in ("success", "error"): s = "unknown"
    TRADE_RESULT.labels(s, sd).inc()
    if latency_seconds is not None and latency_seconds >= 0:
        TRADE_LATENCY.observe(float(latency_seconds))

# ===== FastAPI integration =====
def _fastapi_middleware(app):
    from starlette.requests import Request
    from starlette.responses import Response

    @app.middleware("http")
    async def _prom_http_mw(request: Request, call_next: Callable):
        start = time.perf_counter()
        handler = request.url.path
        method = request.method
        try:
            response: Response = await call_next(request)
            code = response.status_code
            return response
        except Exception:
            code = 500
            raise
        finally:
            dur = time.perf_counter() - start
            REQUESTS.labels(handler, method, str(code)).inc()
            REQUEST_LATENCY.labels(handler, method).observe(dur)

def _fastapi_endpoint(app):
    from fastapi import Response

    @app.get("/metrics")
    def metrics():
        data = generate_latest(REGISTRY)
        return Response(content=data, media_type=CONTENT_TYPE_LATEST, status_code=200)

def register_fastapi(app) -> None:
    """קרא פעם אחת בעת אתחול FastAPI."""
    _fastapi_middleware(app)
    _fastapi_endpoint(app)

# ===== Flask integration (אם צריך) =====
def register_flask(app) -> None:
    from flask import request, Response as FlaskResponse

    @app.before_request
    def _before():
        request._prom_start = time.perf_counter()

    @app.after_request
    def _after(response):
        try:
            start = getattr(request, "_prom_start", None)
            if start is not None:
                dur = time.perf_counter() - start
                REQUESTS.labels(request.path, request.method, str(response.status_code)).inc()
                REQUEST_LATENCY.labels(request.path, request.method).observe(dur)
        finally:
            return response

    @app.route("/metrics", methods=["GET"])
    def metrics():
        data = generate_latest(REGISTRY)
        return FlaskResponse(data, mimetype=CONTENT_TYPE_LATEST, status=200)
