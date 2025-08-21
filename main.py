# main.py
from __future__ import annotations
import os, asyncio, logging, json, time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles

# --- Env ---
load_dotenv(override=True)

# --- Config (בודק/מנרמל פרמטרים ומספק קבועים) ---
from utils.config import (
    check_config,
    dump_config_sanitized,
    LOG_LEVEL,
    WS_UPDATE_INTERVAL,
    PRICE_MONITOR_INTERVAL,
    PRICE_WS_FRESH_TTL,
    PRICE_MONITOR_DISABLE,
)

# Utils
from utils.response_limits import ResponseSizeLimiter
from utils.json_logger import setup_json_logging
from utils.ws_fallback import auto_price_updater, LAST_PRICE_CACHE, update_price
from utils.watchlist_utils import load_watchlist
from utils.binance_client import futures_mark_price
from utils.anchor import evaluate_anchor
from utils.rate_limit import RateLimitMiddleware
from utils import cache_fallback as redis_store
from utils.auth import require_api_key   # ✅ API-Key auth

# --- App Version ---
APP_VERSION = os.getenv("ALGOGPT_VERSION", "2.14.5")

# --- Logging (JSON + זיכרון) ---
logger = setup_json_logging()
logging.getLogger().setLevel(LOG_LEVEL)

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

# בדיקות קונפיג קריטיות (יזרוק RuntimeError בפרוד)
check_config()
logger.info({"event": "config_snapshot", **dump_config_sanitized()})

# --- FastAPI ---
app = FastAPI(
    title="AlgoGPT API",
    version=APP_VERSION,
    description="AlgoGPT — מערכת מסחר אלגוריתמי בזמן אמת"
)

# --- Middlewares ---
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(ResponseSizeLimiter, max_bytes=int(os.getenv("RESPONSE_MAX_BYTES", 2_097_152)))

# ✅ Rate-limit config (config/rate_limits.json אם קיים)
rate_limits_config = {"default": {"limit": 60, "window": 60}, "endpoints": {}}
config_file = Path("config/rate_limits.json")
if config_file.exists():
    try:
        rate_limits_config = json.loads(config_file.read_text())
        logger.info({"event": "rate_limit_config_loaded", "file": str(config_file)})
    except Exception as e:
        logger.error({"event": "rate_limit_config_error", "error": str(e)})

endpoint_limits = {
    pattern: (cfg["limit"], cfg["window"])
    for pattern, cfg in rate_limits_config.get("endpoints", {}).items()
}

app.add_middleware(
    RateLimitMiddleware,
    limit=rate_limits_config["default"]["limit"],
    window=rate_limits_config["default"]["window"],
    endpoint_limits=endpoint_limits
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("CORS_ALLOW_ORIGINS", "*")],
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
from routes.anchor import router as anchor_router   # ✅ Anchor

# ✅ Protected routers (נדרש API-Key)
protected_routers = [
    (ai_router, "/ai", ["AI"]),
    (scan_router, "", ["Scan"]),
    (trade_router, "/trade", ["Trade"]),
    (backtest_router, "/backtest", ["Backtest"]),
    (grid_router, "/grid", ["Grid"]),
    (orderflow_router, "/orderflow", ["Orderflow"]),
    (scan_top_volume_router, "/scan", ["Scan"]),
    (strategy_router, "/strategy", ["Strategy"]),
    (news_router, "/news", ["News"]),
    (indicators_router, "/indicators", ["Indicators"]),
    (analytics_router, "/analytics", ["Analytics"]),
    (risk_router, "/risk", ["Risk"]),
    (snapshot_router, "/snapshot", ["Snapshots"]),
    (dashboard_router, "/dashboard", ["Dashboard"]),
    (orders_router, "/orders", ["Orders"]),
    (ws_router, "/ws", ["Websocket"]),
    (debug_binance_router, "", ["Debug"]),
    (executor_router, "", ["Executor"]),
    (price_router, "", ["Price"]),
    (market_router, "", ["Market"]),
    (scan_utils_router, "/scan", ["Scan"]),
    (utils_router, "", ["Utils"]),
    (anchor_router, "", ["Anchor"]),
]

for router, prefix, tags in protected_routers:
    app.include_router(router, prefix=prefix, tags=tags, dependencies=[Depends(require_api_key)])

# ✅ Debug router פתוח (ללא API-Key)
app.include_router(debug_router, prefix="/debug", tags=["Debug"])

# --- Price Monitor Loop (דלג אם WS טרי; ניתן לכיבוי מלא ב-ENV) ---
async def price_monitor_loop(interval: int = PRICE_MONITOR_INTERVAL):
    """
    מושך Mark Price ב-REST רק לסימבולים שלא קיבלו עדכון WS טרי ב-TTL.
    ניתן לכבות לחלוטין עם PRICE_MONITOR_DISABLE=true.
    """
    while True:
        try:
            now_iso = datetime.now(timezone.utc).isoformat()
            for sym, rec in list(LAST_PRICE_CACHE.items()):
                try:
                    ts = float(rec.get("ts") or 0.0)
                except Exception:
                    ts = 0.0

                # אם היה עדכון WS לאחרונה → דלג על REST
                if (time.time() - ts) < PRICE_WS_FRESH_TTL:
                    continue

                try:
                    price_val = futures_mark_price(sym)  # float יציב (כולל רוטציית דומיינים)
                    if price_val and price_val > 0:
                        update_price(sym, float(price_val))
                        logger.info({"event": "price_monitor", "symbol": sym, "price": float(price_val), "time": now_iso})
                except Exception as e:
                    logger.error({"event": "price_monitor_error", "symbol": sym, "error": str(e)})
        except Exception as e:
            logger.error({"event": "price_monitor_loop_error", "error": str(e)})
        await asyncio.sleep(interval)

# --- Anchor Snapshot Loop ---
async def anchor_snapshot_loop(interval: int = int(os.getenv("ANCHOR_SNAPSHOT_INTERVAL", "30"))):
    sides = ["LONG", "SHORT"]
    while True:
        try:
            now = int(datetime.now(timezone.utc).timestamp())
            for side in sides:
                try:
                    dec = evaluate_anchor(side)
                    key = "anchor:history"
                    item = {"ts": now, "side": side, "bias": dec.bias, "score": dec.score, "allow": dec.allow}
                    await redis_store.lpush(key, json.dumps(item))
                    await redis_store.ltrim(key, 0, 200)
                    logger.info({"event": "anchor_snapshot", **item})
                except Exception as e:
                    logger.error({"event": "anchor_snapshot_error", "side": side, "error": str(e)})
        except Exception as e:
            logger.error({"event": "anchor_snapshot_loop_error", "error": str(e)})
        await asyncio.sleep(interval)

# --- Cache Cleaner ---
CACHE_DIR = Path("static/cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

async def cache_cleaner(interval: int = 3600, max_files: int = 100, max_age: int = 86400):
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
    # Watchlist + Anchor
    watchlist = load_watchlist()
    symbols = [it["symbol"] for it in watchlist]
    if "BTCUSDT" not in [s.upper() for s in symbols]:
        symbols.insert(0, "BTCUSDT")
        logger.info({"event": "watchlist", "msg": "BTCUSDT enforced as anchor"})

    # WS updater (מקור עיקרי למחירים)
    asyncio.create_task(auto_price_updater(symbols, interval=WS_UPDATE_INTERVAL))

    # REST polling (גיבוי) — ניתן לכיבוי מלא דרך ENV
    if not PRICE_MONITOR_DISABLE:
        asyncio.create_task(price_monitor_loop(interval=PRICE_MONITOR_INTERVAL))
    else:
        logger.warning({"event": "price_monitor_disabled"})

    # Anchor snapshots + ניקוי קבצים
    asyncio.create_task(anchor_snapshot_loop(interval=int(os.getenv("ANCHOR_SNAPSHOT_INTERVAL", "30"))))
    asyncio.create_task(cache_cleaner(interval=3600, max_files=100, max_age=86400))

# --- Root / Status ---
@app.get("/", tags=["Config"])
async def root_status():
    return {"status": "ok", "version": APP_VERSION}

# --- Error handler ---
@app.exception_handler(Exception)
async def handle_exception(request: Request, exc: Exception):
    logger.error({"event": "exception", "error": str(exc), "path": request.url.path})
    return JSONResponse({"detail": str(exc)}, status_code=500)

# --- Health endpoints (no API-Key needed) ---
@app.get("/health", tags=["Health"])
async def health():
    return {"status": "ok", "version": APP_VERSION}

@app.get("/health/live", tags=["Health"])
async def health_live():
    return {"status": "live"}

# ✅ Debug logs endpoint (no API-Key)
@app.get("/debug/health", tags=["Debug"])
async def debug_health(limit: int = Query(50), level: str | None = None, logger_name: str | None = None):
    logs = list(LOG_BUFFER)[-limit:]
    if level:
        logs = [log for log in logs if log["level"] == level.upper()]
    if logger_name:
        logs = [log for log in logs if log["logger"] == logger_name]
    return {"count": len(logs), "logs": logs}

# --- Entrypoint (לוקאלי בלבד; בפרוד רץ דרך Gunicorn) ---
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)), reload=os.getenv("APP_ENV","production")!="production")



































































































































































































































































































































































































































