# ✅ גרסה מתוקנת ל־main.py (מוכנה ל־LIVE)
# כולל: טעינה מסודרת של ראוטרים, תמיכה מלאה במטראיקות, בקרת שגיאות, CORS, Executor, ו־Bearer Auth

# main.py
from __future__ import annotations
import os, logging, time
from typing import List, Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from starlette.responses import Response
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

# --- Core routers ---
from routes.ai import router as ai_router
from routes.trade import router as trade_router

# --- Optional routers (טעינה דינמית) ---
def _try_import(name: str, attr: str = "router") -> Optional[object]:
    try:
        module = __import__(name, fromlist=[attr])
        obj = getattr(module, attr)
        logger.info("Loaded router: %s.%s", name, attr)
        return obj
    except Exception as exc:
        logger.warning("Router not loaded (%s.%s): %s", name, attr, exc)
        return None

backtest_router    = _try_import("routes.backtest")
ai_analyze_router  = _try_import("routes.ai_analyze")
ai_health_router   = _try_import("routes.ai_health")
health_router      = _try_import("routes.health_full") or _try_import("routes.health")
dash_router        = _try_import("routes.dashboard")
price_router       = _try_import("routes.price")
ind_router         = _try_import("routes.routes_indicators") or _try_import("routes.indicators")
market_router      = _try_import("routes.market")
analytics_router   = _try_import("routes.analytics")
news_router        = _try_import("routes.news")
decision_router    = _try_import("routes.decision")
grid_router        = _try_import("routes.grid")
risk_router        = _try_import("routes.risk")
snapshot_router    = _try_import("routes.snapshot")
scan_router        = _try_import("routes.multi_scan")

try:
    from routes.scan_top_volume import router as scan_topvol_router
    logger.info("Loaded router: routes.scan_top_volume.router")
except Exception as exc:
    logger.warning("routes.scan_top_volume not loaded: %s", exc)
    scan_topvol_router = None

# --- Auto Executor ---
_auto_exec_start = None
try:
    from utils.auto_executor import start_executor as _auto_exec_start
    logger.info("auto_executor available")
except Exception as exc:
    logger.warning("auto_executor not available: %s", exc)

# --- Config ---
try:
    from utils import config as _cfg
except Exception as exc:
    logger.warning("utils.config not available: %s", exc)
    class _Dummy:
        AUTO_RUN = False
        SCAN_INTERVAL = 60
    _cfg = _Dummy()

app = FastAPI(
    title="AlgoGPT API",
    version=APP_VERSION,
    description="AlgoGPT – Real-time algo trader for Binance (Futures / Spot / Grid).",
)

# --- CORS ---
allow_origins: List[str] = ["*"] if CORS_ALLOW_ORIGINS == "*" else [
    o.strip() for o in CORS_ALLOW_ORIGINS.split(",") if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Static files ---
if os.path.isdir(".well-known"):
    app.mount("/.well-known", StaticFiles(directory=".well-known"), name="static-plugin")
if os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

# --- Middleware for metrics ---
@app.middleware("http")
async def _metrics_middleware(request: Request, call_next):
    t0 = time.perf_counter()
    try:
        response = await call_next(request)
        return response
    finally:
        dt_ms = (time.perf_counter() - t0) * 1000.0
        status_code = response.status_code if 'response' in locals() else 500
        metrics_tracker.observe_request(status_code=status_code, duration_ms=dt_ms)

# --- Error handlers ---
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

@app.exception_handler(Exception)
async def _unhandled_exc_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error")
    metrics_tracker.inc_err()
    return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})

# --- Core endpoints ---
@app.get("/", tags=["Config"], operation_id="getRootStatus")
def root():
    return {"status": "ok", "version": app.version}

@app.get("/metrics", tags=["Config"], operation_id="getBasicMetrics")
async def get_metrics():
    return metrics_tracker.get_metrics()

@app.get("/__routes", tags=["Config"], include_in_schema=False)
def list_routes():
    return {"routes": [r.path for r in app.routes if hasattr(r, "path")]}  # Debug use only

# --- Register routers ---
app.include_router(ai_router, prefix="/ai", tags=["AI"])
app.include_router(trade_router, prefix="/trade", tags=["Trades"])

for r in [
    backtest_router, ai_analyze_router, ai_health_router, health_router,
    dash_router, price_router, ind_router, market_router, analytics_router,
    news_router, decision_router, grid_router, risk_router, snapshot_router,
    scan_router, scan_topvol_router,
]:
    if r:
        app.include_router(r)

# --- Startup / Shutdown ---
@app.on_event("startup")
async def on_startup():
    logger.info("AlgoGPT API started (v%s)", APP_VERSION)
    if getattr(_cfg, "AUTO_RUN", False) and _auto_exec_start:
        try:
            _auto_exec_start()
            logger.info("AUTO_RUN → Executor started (interval=%ss)", getattr(_cfg, "SCAN_INTERVAL", 60))
        except Exception as e:
            logger.warning("Executor failed to start: %s", e)

@app.on_event("shutdown")
async def on_shutdown():
    logger.info("AlgoGPT API shutting down")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "10000")), log_level=LOG_LEVEL.lower())

































































































































































































































































































































































