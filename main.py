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

APP_VERSION = os.getenv("ALGOGPT_VERSION", "2.14.2")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
CORS_ALLOW_ORIGINS = os.getenv("CORS_ALLOW_ORIGINS", "*")

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s: %(message)s",
)
logger = logging.getLogger("algogpt")

# חובה
from routes.ai import router as ai_router
from routes.trade import router as trade_router

def _try_import(name: str, attr: str = "router") -> Optional[object]:
    try:
        module = __import__(name, fromlist=[attr])
        return getattr(module, attr)
    except Exception as exc:  # pragma: no cover
        logger.warning("%s not loaded: %s", name, exc)
        return None

# אופציונלי
backtest_router    = _try_import("routes.backtest")
scan_router        = None  # מכבים את הגרסה הישנה למניעת כפילויות
multi_scan_router  = None  # מכבים (הייתה בעיית תחביר ב-indicators_ext)
scan_topvol_router = _try_import("routes.scan_top_volume")  # <<< חדש וחשוב
ai_analyze_router  = _try_import("routes.ai_analyze")
ai_health_router   = _try_import("routes.ai_health")
health_router      = _try_import("routes.health_full") or _try_import("routes.health")
dashboard_router   = _try_import("routes.dashboard")
price_router       = _try_import("routes.price")
ind_router         = _try_import("routes.routes_indicators")
market_router      = _try_import("routes.market")
analytics_router   = _try_import("routes.analytics")
news_router        = _try_import("routes.news")
decision_router    = _try_import("routes.decision")
grid_router        = _try_import("routes.grid")
risk_router        = _try_import("routes.risk")
snapshot_router    = _try_import("routes.snapshot")

app = FastAPI(
    title="AlgoGPT API",
    description=("AlgoGPT — מסחר אלגוריתמי בזמן אמת ל־Binance Futures "
                 "(Scan/AI/Trades/Backtest/News/Macro/Correlation)."),
    version=APP_VERSION,
)

# CORS
allow_origins: List[str] = ["*"] if CORS_ALLOW_ORIGINS == "*" else [o.strip() for o in CORS_ALLOW_ORIGINS.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static (לא חובה)
if os.path.isdir(".well-known"):
    app.mount("/.well-known", StaticFiles(directory=".well-known"), name="static-plugin")
if os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

# Metrics
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
            metrics_tracker.observe_request(status_code=status_code, duration_ms=dt_ms, method=request.method, path=request.url.path)
        except TypeError:
            metrics_tracker.observe_request(status_code=status_code, duration_ms=dt_ms)

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

@app.exception_handler(Exception)
async def _unhandled_exc_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error")
    metrics_tracker.inc_err()
    return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})

@app.get("/", operation_id="getRootStatus", tags=["Config"])
def root():
    return {"status": "ok", "version": app.version}

@app.get("/metrics", operation_id="getBasicMetrics", tags=["Config"])
async def get_metrics():
    return metrics_tracker.get_metrics()

# דיבוג – לראות אילו נתיבים נטענו בפועל
@app.get("/__routes", tags=["Config"], operation_id="getRegisteredRoutes", include_in_schema=False)
def get_registered_routes():
    out = []
    for r in app.routes:
        try:
            methods = sorted(list(getattr(r, "methods", set())))
            path = getattr(r, "path", None) or getattr(r, "path_format", None)
            out.append({"path": path, "methods": methods})
        except Exception:
            pass
    return {"count": len(out), "routes": out}

# Routers
app.include_router(ai_router,    prefix="/ai",    tags=["AI"])
app.include_router(trade_router, prefix="/trade", tags=["Trades"])

for r in [
    ai_analyze_router, ai_health_router, backtest_router, dashboard_router,
    health_router, price_router, ind_router, market_router,
    analytics_router, news_router, decision_router, grid_router,
    risk_router, snapshot_router, scan_topvol_router  # <<< חשוב: כאן
]:
    if r:
        app.include_router(r)

@app.on_event("startup")
async def on_startup():
    logger.info("AlgoGPT API started (v%s)", APP_VERSION)

@app.on_event("shutdown")
async def on_shutdown():
    logger.info("AlgoGPT API shutting down")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "10000")), log_level=LOG_LEVEL.lower())



























































































































































































































































































































































