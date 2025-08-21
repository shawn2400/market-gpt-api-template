# main.py
from __future__ import annotations
import os
import asyncio
import logging
from collections import deque
from datetime import datetime, timezone
import json
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import time

# Utils
from utils.response_limits import ResponseSizeLimiter
from utils.json_logger import setup_json_logging
from utils.ws_fallback import auto_price_updater, LAST_PRICE_CACHE, update_price
from utils.redis_client import redis_client
from utils.watchlist_utils import load_watchlist
from utils.binance_client import futures_mark_price
from utils.anchor import evaluate_anchor
from utils.rate_limit import RateLimitMiddleware

# --- Env ---
load_dotenv(override=True)
APP_VERSION = os.getenv("ALGOGPT_VERSION", "2.14.4")

# --- Logging (JSON structured) ---
logger = setup_json_logging()

# ✅ In-memory log buffer
LOG_BUFFER_SIZE = int(os.getenv("LOG_BUFFER_SIZE", 200))
LOG_BUFFER = deque(maxlen=LOG_BUFFER_SIZE)


class MemoryLogHandler(logging.Handler):
    def emit(self, record):
        LOG_BUFFER.append({
            "time": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage()
        })


logger.addHandler(MemoryLogHandler())

# --- FastAPI ---
app = FastAPI(
    title="AlgoGPT API",
    version=APP_VERSION,
    description="AlgoGPT — מערכת מסחר אלגוריתמי בזמן אמת (Binance Futures/Spot/Grid/AI/Backtest/Analytics/News/Indicators/Risk/Orders/Debug)"
)

# --- Middlewares ---
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(ResponseSizeLimiter, max_bytes=2_097_152)

# ✅ Rate-limit: כללי 60/דקה, מותאם פר־endpoint
ENDPOINT_LIMITS = {
    "/backtest/": (10, 60),     # בקושי – 10 קריאות לדקה
    "/health": (300, 60),       # בריאות – נדיב
    "/health/live": (300, 60),
}
app.add_middleware(
    RateLimitMiddleware,
    limit=60,
    window=60,
    endpoint_limits=ENDPOINT_LIMITS
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Static files ---
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


# --- Price Monitor Loop (LIVE) ---
async def price_monitor_loop(interval: int = 30):
    while True:
        try:
            now = datetime.now(timezone.utc).isoformat()
            for sym in list(LAST_PRICE_CACHE.keys()):
                try:
                    data = futures_mark_price(sym)
                    price = float(data["markPrice"]) if isinstance(data, dict) and "markPrice" in data else None
                    if price:
                        update_price(sym, price)
                        logger.info({
                            "event": "price_monitor",
                            "symbol": sym,
                            "price": price,
                            "time": now
                        })
                except Exception as e:
                    logger.error({
                        "event": "price_monitor_error",
                        "symbol": sym,
                        "error": str(e)
                    })
        except Exception as e:
            logger.error({"event": "price_monitor_loop_error", "error": str(e)})

        await asyncio.sleep(interval)


# --- Anchor Snapshot Loop ---
async def anchor_snapshot_loop(interval: int = 30):
    sides = ["LONG", "SHORT"]
    while True:
        try:
            now = int(datetime.now(timezone.utc).timestamp())
            for side in sides:
                try:
                    dec = evaluate_anchor(side)
                    if redis_client:
                        key = "anchor:history"
                        item = {
                            "ts": now,
                            "side": side,
                            "bias": dec.bias,
                            "score": dec.score,
                            "allow": dec.allow,
                        }
                        redis_client.lpush(key, json.dumps(item))
                        redis_client.ltrim(key, 0, 200)
                    logger.info({
                        "event": "anchor_snapshot",
                        "side": side,
                        "bias": dec.bias,
                        "score": dec.score,
                        "allow": dec.allow,
                        "time": now
                    })
                except Exception as e:
                    logger.error({
                        "event": "anchor_snapshot_error",
                        "side": side,
                        "error": str(e)
                    })
        except Exception as e:
            logger.error({"event": "anchor_snapshot_loop_error", "error": str(e)})

        await asyncio.sleep(interval)


# --- Cache Cleaner ---
CACHE_DIR = Path("static/cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

async def cache_cleaner(interval: int = 3600, max_files: int = 100, max_age: int = 86400):
    """
    מנקה קבצי cache ישנים:
    - מוחק קבצים בני יותר מ־24 שעות (max_age)
    - משאיר רק 100 קבצים אחרונים
    """
    while True:
        try:
            files = sorted(CACHE_DIR.glob("backtest_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
            now = time.time()

            for f in files:
                if now - f.stat().st_mtime > max_age:
                    f.unlink(missing_ok=True)

            for f in files[max_files:]:
                f.unlink(missing_ok=True)

        except Exception as e:
            logger.error({"event": "cache_cleaner_error", "error": str(e)})

        await asyncio.sleep(interval)


# --- Startup tasks ---
@app.on_event("startup")
async def startup_event():
    if redis_client:
        logger.info({"event": "startup", "msg": "✅ Connected to Redis"})

    watchlist = load_watchlist()
    symbols = [it["symbol"] for it in watchlist]
    if "BTCUSDT" not in [s.upper() for s in symbols]:
        symbols.insert(0, "BTCUSDT")
        logger.info({"event": "watchlist", "msg": "BTCUSDT enforced as anchor"})

    updater_interval = int(os.getenv("WS_UPDATE_INTERVAL", 15))
    asyncio.create_task(auto_price_updater(symbols, interval=updater_interval))
    logger.info({
        "event": "startup",
        "msg": f"✅ Auto price updater started for {len(symbols)} symbols every {updater_interval}s"
    })

    monitor_interval = int(os.getenv("PRICE_MONITOR_INTERVAL", 30))
    asyncio.create_task(price_monitor_loop(interval=monitor_interval))
    logger.info({"event": "startup", "msg": f"✅ Price monitor loop started ({monitor_interval}s)"})

    anchor_interval = int(os.getenv("ANCHOR_SNAPSHOT_INTERVAL", 30))
    asyncio.create_task(anchor_snapshot_loop(interval=anchor_interval))
    logger.info({"event": "startup", "msg": f"✅ Anchor snapshot loop started ({anchor_interval}s)"})

    asyncio.create_task(cache_cleaner(interval=3600, max_files=100, max_age=86400))
    logger.info({"event": "startup", "msg": "✅ Cache cleaner started"})


# --- Root / Status ---
@app.get("/", tags=["Config"], operation_id="getRootStatus")
async def root_status():
    return {"status": "ok", "version": APP_VERSION}


# --- Error handler ---
@app.exception_handler(Exception)
async def handle_exception(request: Request, exc: Exception):
    logger.error({"event": "exception", "error": str(exc), "path": request.url.path})
    return JSONResponse({"detail": str(exc)}, status_code=500)


# --- Health endpoints ---
@app.get("/health", tags=["Health"], operation_id="getHealth")
async def health():
    return {"status": "ok", "version": APP_VERSION}


@app.get("/health/live", tags=["Health"], operation_id="getHealthLive")
async def health_live():
    return {"status": "live"}


# ✅ Debug logs endpoint
@app.get("/debug/health", tags=["Debug"], operation_id="getDebugHealth")
async def debug_health(
    limit: int = Query(50, description="Number of logs to return"),
    level: str | None = Query(None, description="Filter by log level"),
    logger_name: str | None = Query(None, description="Filter by logger name")
):
    logs = list(LOG_BUFFER)[-limit:]

    if level:
        level = level.upper()
        logs = [log for log in logs if log["level"] == level]

    if logger_name:
        logs = [log for log in logs if log["logger"] == logger_name]

    return {"count": len(logs), "logs": logs}


# --- Entrypoint (local run only) ---
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)), reload=True)






























































































































































































































































































































































































































