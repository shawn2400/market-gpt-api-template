# main.py
from __future__ import annotations
import os, asyncio
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles

from utils.response_limits import ResponseSizeLimiter
from utils.json_logger import setup_json_logging
from utils.ws_fallback import price_monitor_loop

# --- Env ---
load_dotenv(override=True)
APP_VERSION = os.getenv("ALGOGPT_VERSION", "2.14.3")

# --- Logging (JSON structured) ---
logger = setup_json_logging()

# --- FastAPI ---
app = FastAPI(
    title="AlgoGPT API",
    version=APP_VERSION,
    description="AlgoGPT — מסחר אלגוריתמי בזמן אמת ב-Binance "
                "(Futures/Spot/Grid/AI/Backtest/Analytics/News/Indicators/Risk/Orders/Debug).",
)

# --- Middlewares ---
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(ResponseSizeLimiter, max_bytes=2_097_152)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Static ---
app.mount("/static", StaticFiles(directory="static"), name="static")

# --- Routers ---
from routes.ai import router as ai_router
from routes.multi_scan import router as scan_router
from routes.trade import router as trade_router
from routes.backtest import router as backtest_router
from routes.grid import router as grid_router
from routes.orderflow import router as orderflow_router
from routes.scan_top_volume import router as scan_top_volume_router
from routes.strategy import router as strategy_router
from routes.news import router as news_router
from routes.indicators import router as indicators_router
from routes.analytics import router as analytics_router
from routes.risk import router as risk_router
from routes.snapshot import router as snapshot_router
from routes.dashboard import router as dashboard_router
from routes.orders import router as orders_router
from routes.ws import router as ws_router
from routes.debug import router as debug_router
from routes.debug_binance import router as debug_binance_router
from routes.executor import router as executor_router
from routes.price import router as price_router
from routes.market import router as market_router
from routes.scan import router as scan_utils_router
from routes.utils import router as utils_router

# ✅ Include routers
app.include_router(ai_router, prefix="/ai", tags=["AI"])
app.include_router(scan_router, tags=["Scan"])
app.include_router(trade_router, prefix="/trade", tags=["Trade"])
app.include_router(backtest_router, prefix="/backtest", tags=["Backtest"])
app.include_router(grid_router, prefix="/grid", tags=["Grid"])
app.include_router(orderflow_router, prefix="/orderflow", tags=["Orderflow"])
app.include_router(scan_top_volume_router, prefix="/scan", tags=["Scan"])
app.include_router(strategy_router, prefix="/strategy", tags=["Strategy"])
app.include_router(news_router, prefix="/news", tags=["News"])
app.include_router(indicators_router, prefix="/indicators", tags=["Indicators"])
app.include_router(analytics_router, prefix="/analytics", tags=["Analytics"])
app.include_router(risk_router, prefix="/risk", tags=["Risk"])
app.include_router(snapshot_router, prefix="/snapshot", tags=["Snapshots"])
app.include_router(dashboard_router, prefix="/dashboard", tags=["Dashboard"])
app.include_router(orders_router, prefix="/orders", tags=["Orders"])
app.include_router(ws_router, prefix="/ws", tags=["Websocket"])
app.include_router(debug_router, prefix="/debug", tags=["Debug"])
app.include_router(debug_binance_router, tags=["Debug"])
app.include_router(executor_router, tags=["Executor"])
app.include_router(price_router, tags=["Price"])
app.include_router(market_router, tags=["Market"])
app.include_router(scan_utils_router, prefix="/scan", tags=["Scan"])
app.include_router(utils_router, tags=["Utils"])

# --- Startup: Background tasks ---
@app.on_event("startup")
async def startup_event():
    asyncio.create_task(price_monitor_loop())
    logger.info({"event": "startup", "msg": "✅ Price monitor loop started"})

# --- Root / Status ---
@app.get("/", tags=["Config"], operation_id="getRootStatus")
async def root_status():
    return {"status": "ok", "version": APP_VERSION}

# --- Error handler ---
@app.exception_handler(Exception)
async def handle_exception(request: Request, exc: Exception):
    logger.error({"event": "exception", "error": str(exc), "path": request.url.path})
    return JSONResponse({"detail": str(exc)}, status_code=500)

# --- Health ---
@app.get("/health", tags=["Health"], operation_id="getHealth")
async def health():
    return {"status": "ok", "version": APP_VERSION}

@app.get("/health/live", tags=["Health"], operation_id="getHealthLive")
async def health_live():
    return {"status": "live"}

# --- Entrypoint (local run) ---
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)), reload=True)













































































































































































































































































































































































































