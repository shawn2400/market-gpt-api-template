# main.py
from __future__ import annotations
import os
import logging
import time
from typing import List, Optional

# --- Load .env early ---
try:
    from dotenv import load_dotenv
    load_dotenv(override=False)
except Exception:
    pass

from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from starlette.responses import Response
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.gzip import GZipMiddleware

from utils.metrics import metrics_tracker
from utils.auth import require_bearer_token
from utils.response_limits import ResponseSizeLimiter
from utils import config  # ← כל ההגדרות במקום אחד

APP_VERSION = os.getenv("ALGOGPT_VERSION", config.ALGOGPT_VERSION)
LOG_LEVEL = (os.getenv("LOG_LEVEL") or config.LOG_LEVEL).upper()
CORS_ALLOW_ORIGINS = os.getenv("CORS_ALLOW_ORIGINS", config.CORS_ALLOW_ORIGINS)

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s: %(message)s",
)
logger = logging.getLogger("algogpt")

# Optional: WS Mark Price bus
_mark_bus = None
try:
    from utils.mark_ws import bus as _mark_bus  # type: ignore
    logger.info("mark_ws module available; will attempt to start on startup")
except Exception as exc:
    _mark_bus = None
    logger.warning("mark_ws not available: %s", exc)

# Core routers
from routes.ai import router as ai_router
from routes.trade import router as trade_router

def _try_import(name: str, attr: str = "router") -> Optional[object]:
    try:
        module = __import__(name, fromlist=[attr])
        obj = getattr(module, attr)
        logger.info("loaded router: %s.%s", name, attr)
        return obj
    except Exception as exc:
        logger.warning("failed to load %s.%s: %s", name, attr, exc)
        return None

_auto_exec_start = None
try:
    from utils.auto_executor import start_executor as _auto_exec_start  # type: ignore
    logger.info("auto_executor available")
except Exception as exc:
    logger.warning("auto_executor not available: %s", exc)

# FastAPI app
app = FastAPI(
    title="AlgoGPT API",
    description="AlgoGPT — Binance Futures LIVE (Scan/AI/Trades/Backtest/News/Grid/Risk).",
    version=APP_VERSION,
)

# CORS
allow_origins: List[str] = ["*"] if CORS_ALLOW_ORIGINS == "*" else [
    o.strip() for o in CORS_ALLOW_ORIGINS.split(",") if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Middlewares: GZip + Response guard (413 אם גדול מדי)
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(ResponseSizeLimiter, max_bytes=config.RESPONSE_MAX_BYTES)

# Static (optional)
if os.path.isdir(".well-known"):
    app.mount("/.well-known", StaticFiles(directory=".well-known"), name="static-plugin")
if os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

# Metrics middleware
@app.middleware("http")
async def _metrics_middleware(request: Request, call_next):
    t0 = time.perf_counter()
    status_code = 500
    try:
        response: Response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        dt_ms = (time.perf_counter() - t0) * 1000.0
        try:
            metrics_tracker.observe_request(
                status_code=status_code, duration_ms=dt_ms,
                method=request.method, path=request.url.path
            )
        except TypeError:
            metrics_tracker.observe_request(status_code=status_code, duration_ms=dt_ms)

# Exception handlers
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

@app.exception_handler(Exception)
async def _unhandled_exc_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error")
    metrics_tracker.inc_err()
    return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})

# Basics (public)
@app.get("/", operation_id="getRootStatus", tags=["Config"])
def root():
    return {"status": "ok", "version": app.version}

@app.get("/metrics", operation_id="getBasicMetrics", tags=["Config"])
async def get_metrics():
    return metrics_tracker.get_metrics()

@app.get("/__routes", tags=["Debug"], operation_id="getRegisteredRoutes", include_in_schema=False)
def list_routes():
    out = []
    for r in app.routes:
        try:
            methods = sorted(list(getattr(r, "methods", set())))
            path = getattr(r, "path", None) or getattr(r, "path_format", None)
            out.append({"path": path, "methods": methods})
        except Exception:
            pass
    return {"count": len(out), "routes": out}

# Public health router first
health_router = _try_import("routes.health", "router")
if health_router:
    app.include_router(health_router)

# Protected routers (token/header/query)
protected_dep = [Depends(require_bearer_token)]
app.include_router(ai_router,    prefix="/ai",    tags=["AI"],    dependencies=protected_dep)
app.include_router(trade_router, prefix="/trade", tags=["Trades"], dependencies=protected_dep)

for mod in [
    "routes.backtest", "routes.ai_analyze", "routes.news", "routes.grid",
    "routes.dashboard", "routes.routes_indicators", "routes.price",
    "routes.multi_scan", "routes.risk", "routes.snapshot",
    "routes.analytics", "routes.ai_health", "routes.executor",
    "routes.orderflow",
]:
    r = _try_import(mod, "router")
    if r:
        app.include_router(r, dependencies=protected_dep)

# scan_top_volume has two routers
_scan_router = _try_import("routes.scan_top_volume", "router")
if _scan_router:
    app.include_router(_scan_router, dependencies=protected_dep)
_scan_sym_router = _try_import("routes.scan_top_volume", "router_symbols")
if _scan_sym_router:
    app.include_router(_scan_sym_router, dependencies=protected_dep)

# analytics compat (/macro)
_analytics_compat = _try_import("routes.analytics", "router_compat")
if _analytics_compat:
    app.include_router(_analytics_compat, dependencies=protected_dep)

# Lifecycle
@app.on_event("startup")
async def on_startup():
    logger.info("AlgoGPT API started (v%s)", APP_VERSION)

    try:
        from utils.ai_client import ai_client  # type: ignore
        await ai_client.warmup()
        logger.info("AI warmup: ready=%s", ai_client.ready)
    except Exception as e:
        logger.warning("AI warmup failed (ignored): %s", e)

    if getattr(config, "AUTO_RUN", False) and _auto_exec_start:
        try:
            _auto_exec_start()
            logger.info("AUTO_RUN=true → auto executor started")
        except Exception as e:
            logger.warning("AUTO_RUN requested but failed to start executor: %s", e)

    try:
        if _mark_bus and hasattr(_mark_bus, "start"):
            _mark_bus.start()
            logger.info("Mark WS bus started")
    except Exception as e:
        logger.warning("Failed to start Mark WS bus: %s", e)

@app.on_event("shutdown")
async def on_shutdown():
    logger.info("AlgoGPT API shutting down")
    try:
        if _mark_bus and hasattr(_mark_bus, "stop"):
            _mark_bus.stop()
            logger.info("Mark WS bus stopped")
    except Exception as e:
        logger.warning("Failed to stop Mark WS bus: %s", e)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "10000")),
        log_level=LOG_LEVEL.lower(),
    )



















































































































































































































































































































































































