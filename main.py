from __future__ import annotations
import os
import logging
import time
from typing import List, Optional
from dotenv import load_dotenv
load_dotenv(override=True)

from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, PlainTextResponse
from starlette.responses import Response
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.gzip import GZipMiddleware

from utils.metrics import metrics_tracker
from utils.auth import require_bearer_token
from utils.response_limits import ResponseSizeLimiter
from utils import config as cfg

APP_VERSION = os.getenv("ALGOGPT_VERSION", "2.14.3")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
CORS_ALLOW_ORIGINS = os.getenv("CORS_ALLOW_ORIGINS", "*")

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s: %(message)s",
)
logger = logging.getLogger("algogpt")

# optional mark_ws
_mark_bus = None
try:
    from utils.mark_ws import bus as _mark_bus  # type: ignore
except Exception:
    pass

from routes.ai import router as ai_router
from routes.trade import router as trade_router
from routes import debug


def _try_import(name: str, attr: str = "router") -> Optional[object]:
    try:
        module = __import__(name, fromlist=[attr])
        return getattr(module, attr)
    except Exception:
        return None


_auto_exec_start = None
try:
    from utils.auto_executor import start_executor as _auto_exec_start
except Exception:
    pass

app = FastAPI(
    title="AlgoGPT API",
    description="AlgoGPT — Binance Futures LIVE",
    version=APP_VERSION,
)

# Middleware
allow_origins: List[str] = ["*"] if CORS_ALLOW_ORIGINS == "*" else [
    o.strip() for o in CORS_ALLOW_ORIGINS.split(",") if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(ResponseSizeLimiter, max_bytes=cfg.RESPONSE_MAX_BYTES)

if os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")


@app.middleware("http")
async def _metrics_middleware(request: Request, call_next):
    t0 = time.perf_counter()
    response: Response | None = None
    try:
        response = await call_next(request)
        return response
    finally:
        dt_ms = (time.perf_counter() - t0) * 1000.0
        try:
            metrics_tracker.observe_request(
                status_code=response.status_code if response else 500,
                duration_ms=dt_ms,
            )
        except Exception as e:
            logger.warning("metrics_tracker failed: %s", e)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(Exception)
async def _unhandled_exc_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error")
    metrics_tracker.inc_err()
    return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})


@app.get("/")
def root():
    return {"status": "ok", "version": app.version}


@app.get("/metrics")
async def get_metrics():
    return metrics_tracker.get_metrics()


@app.get("/metrics/prometheus")
async def get_metrics_prometheus():
    return PlainTextResponse(metrics_tracker.render_prometheus())


# Routers
app.include_router(ai_router, prefix="/ai", dependencies=[Depends(require_bearer_token)])
app.include_router(trade_router, prefix="/trade", dependencies=[Depends(require_bearer_token)])
app.include_router(debug.router, prefix="/debug")

for mod in [
    "routes.backtest", "routes.ai_analyze", "routes.news", "routes.grid",
    "routes.dashboard", "routes.routes_indicators", "routes.price",
    "routes.multi_scan", "routes.risk", "routes.snapshot",
    "routes.analytics", "routes.ai_health", "routes.executor",
    "routes.orderflow", "routes.scan_top_volume",
]:
    r = _try_import(mod, "router")
    if r:
        app.include_router(r, dependencies=[Depends(require_bearer_token)])


@app.on_event("startup")
async def on_startup():
    try:
        from utils.ai_client import ai_client
        await ai_client.warmup()
    except Exception as e:
        logger.warning("AI warmup failed: %s", e)

    if getattr(cfg, "AUTO_RUN", False) and _auto_exec_start:
        try:
            _auto_exec_start()
        except Exception:
            pass


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "10000")))



























































































































































































































































































































































































