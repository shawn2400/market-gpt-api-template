from __future__ import annotations
import os, logging, time
from typing import List, Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from utils.metrics import metrics_tracker

APP_VERSION = os.getenv("ALGOGPT_VERSION", "2.14.3")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
CORS_ALLOW_ORIGINS = os.getenv("CORS_ALLOW_ORIGINS", "*")

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s: %(message)s",
)
logger = logging.getLogger("algogpt")

from routes.ai import router as ai_router
from routes.trade import router as trade_router

def _try_import(name: str, attr: str = "router") -> Optional[object]:
    try:
        module = __import__(name, fromlist=[attr])
        return getattr(module, attr)
    except:
        return None

routers = [
    "routes.backtest", "routes.ai_analyze", "routes.news", "routes.grid",
    "routes.dashboard", "routes.routes_indicators", "routes.price",
    "routes.scan_top_volume", "routes.multi_scan", "routes.health"
]

app = FastAPI(title="AlgoGPT API", version=APP_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def _metrics_middleware(request: Request, call_next):
    t0 = time.perf_counter()
    response = await call_next(request)
    dt_ms = (time.perf_counter() - t0) * 1000.0
    metrics_tracker.observe_request(status_code=response.status_code, duration_ms=dt_ms)
    return response

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

@app.exception_handler(Exception)
async def _unhandled_exc_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error")
    metrics_tracker.inc_err()
    return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})

@app.get("/", tags=["Config"])
def root():
    return {"status": "ok", "version": app.version}

@app.get("/metrics", tags=["Config"])
async def get_metrics():
    return metrics_tracker.get_metrics()

@app.get("/__routes", tags=["Debug"])
def list_routes():
    return {"routes": [r.path for r in app.routes if hasattr(r, "path")]}

app.include_router(ai_router, prefix="/ai", tags=["AI"])
app.include_router(trade_router, prefix="/trade", tags=["Trades"])

for r in routers:
    router = _try_import(r)
    if router:
        app.include_router(router)

@app.on_event("startup")
async def on_startup():
    logger.info("AlgoGPT API started (v%s)", APP_VERSION)

@app.on_event("shutdown")
async def on_shutdown():
    logger.info("AlgoGPT API shutting down")


































































































































































































































































































































































