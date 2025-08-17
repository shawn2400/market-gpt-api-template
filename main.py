# main.py
from __future__ import annotations
import os
import logging
import time
from typing import List, Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from starlette.responses import Response

from utils.metrics import metrics_tracker

# --- Config / ENV ---
APP_VERSION = os.getenv("ALGOGPT_VERSION", "2.14.0")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
CORS_ALLOW_ORIGINS = os.getenv("CORS_ALLOW_ORIGINS", "*")

# --- Logging ---
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s: %(message)s",
)
logger = logging.getLogger("algogpt")

# --- Required routers ---
from routes.ai import router as ai_router            # /ai/*
from routes.trade import router as trade_router      # /trade/*

# --- Optional routers (defensive import) ---
backtest_router: Optional[object] = None
scan_router: Optional[object] = None
ai_analyze_router: Optional[object] = None
ai_health_router: Optional[object] = None
health_router: Optional[object] = None
dashboard_router: Optional[object] = None

# Backtest
try:
    from routes.backtest import router as backtest_router  # type: ignore
except Exception as _bt_exc:
    logger.warning("Backtest router not loaded: %s", _bt_exc)

# Scan (/scan, /scan/multi)
try:
    from routes.scan import router as scan_router  # type: ignore
except Exception as _scan_exc:
    logger.warning("Scan router not loaded: %s", _scan_exc)

# AI analyze (/ai-analyze)
try:
    from routes.ai_analyze import router as ai_analyze_router  # type: ignore
except Exception as _aia_exc:
    logger.warning("AI Analyze router not loaded: %s", _aia_exc)

# AI health (/ai/health)
try:
    from routes.ai_health import router as ai_health_router  # type: ignore
except Exception as _aih_exc:
    logger.warning("AI Health router not loaded: %s", _aih_exc)

# Health – prefer health_full; fallback ל-health
try:
    from routes.health_full import router as health_router  # type: ignore
except Exception as _hf_exc:
    try:
        from routes.health import router as health_router  # type: ignore
    except Exception as _h_exc:
        logger.warning("Health routers not loaded: health_full=%s; health=%s", _hf_exc, _h_exc)

# Dashboard (HTML קטן)
try:
    from routes.dashboard import router as dashboard_router  # type: ignore
except Exception as _db_exc:
    logger.warning("Dashboard router not loaded: %s", _db_exc)

# --- App ---
app = FastAPI(
    title="AlgoGPT API",
    description="AlgoGPT — מסחר אלגוריתמי בזמן אמת ל־Binance Futures",
    version=APP_VERSION,
)

# --- CORS ---
allow_origins: List[str]
if CORS_ALLOW_ORIGINS == "*":
    allow_origins = ["*"]
else:
    allow_origins = [o.strip() for o in CORS_ALLOW_ORIGINS.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Static mounts (optional) ---
if os.path.isdir(".well-known"):
    app.mount("/.well-known", StaticFiles(directory=".well-known"), name="static-plugin")
if os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

# --- Metrics middleware ---
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
        metrics_tracker.observe_request(status_code=status_code, duration_ms=dt_ms)

# --- Global error handler ---
@app.exception_handler(Exception)
async def _unhandled_exc_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error")
    metrics_tracker.inc_err()
    return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})

# --- Health / Metrics ---
@app.get("/", operation_id="getRootStatus", tags=["Config"])
def root():
    return {"status": "ok", "version": app.version}

@app.get("/metrics", operation_id="getBasicMetrics", tags=["Config"])
async def get_metrics():
    return metrics_tracker.get_metrics()

# --- Routers registration ---
app.include_router(ai_router, prefix="/ai", tags=["AI"])
app.include_router(trade_router, prefix="/trade", tags=["Trades"])

if ai_analyze_router:
    app.include_router(ai_analyze_router, tags=["AI"])   # /ai-analyze
else:
    logger.warning("AI Analyze route is not loaded (import failed).")

if ai_health_router:
    app.include_router(ai_health_router, tags=["AI"])     # /ai/health
else:
    logger.warning("AI Health route is not loaded (import failed).")

if scan_router:
    app.include_router(scan_router, tags=["Scan"])        # /scan, /scan/multi
else:
    logger.warning("Scan routes are not loaded (import failed).")

if backtest_router:
    app.include_router(backtest_router, tags=["Backtest"])
else:
    logger.warning("Backtest routes are not loaded (import failed).")

if dashboard_router:
    app.include_router(dashboard_router, tags=["Dashboard"])  # /dashboard
else:
    logger.warning("Dashboard route is not loaded (import failed).")

if health_router:
    app.include_router(health_router)                     # /health, /health/live, /health/strategy-version
else:
    logger.warning("Health routes are not loaded (import failed).")

# --- Lifecycle ---
@app.on_event("startup")
async def on_startup():
    logger.info("AlgoGPT API started (v%s)", APP_VERSION)

# --- Dev run ---
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "10000")),
        log_level=LOG_LEVEL.lower(),
    )































































































































































































































































































