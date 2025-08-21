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

# --- Env ---
load_dotenv(override=True)
APP_VERSION = os.getenv("ALGOGPT_VERSION", "2.14.5")  # העלאה קלה בגרסה

# --- Logging ---
logger = setup_json_logging()
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
    description="AlgoGPT — מערכת מסחר אלגוריתמי בזמן אמת"
)

# --- Middlewares ---
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(ResponseSizeLimiter, max_bytes=2_097_152)

# ✅ Rate-limit config
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
from routes.anchor import router as anchor_router   # ✅ Anchor

# ✅ Protected routers (API-Key required)
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

# ✅ Debug router נשאר פתוח (לא חייב API-Key)
app.include_router(debug_router, prefix="/debug", tags=["Debug"])

# --- Price Monitor Loop (smart skip & disable) ---
PRICE_WS_FRESH_TTL = int(os.getenv("PRICE_WS_FRESH_TTL", "20"))  # שניות

async def price_monitor_loop(interval: int = 30):
    """
    מושך Mark Price ב-REST רק לסימבולים שלא קיבלו עדכון WS טרי לאחרונה.
    ניתן לכבות לחלוטין עם PRICE_MONITOR_DISABLE=1.
    """
    while True:
        try:
            now_iso = datetime.now(timezone.utc).isoformat()
            for sym, rec in list(LAST_PRICE_CACHE.items()):
                try:
                    ts = float(rec.get("ts") or 0.0)
                except Exception:
                    ts = 0.0
                # אם היה עדכון WS ב-TTL האחרון → דילוג על REST
                if (time.time() - ts) < PRICE_WS_FRESH_TTL:
                    continue
                try:
                    price_val = futures_mark_price(sym)  # float יציב
                    if price_val and price_val > 0:
                        update_price(sym, float(price_val))
                        logger.info({"event": "price_monitor", "symbol": sym, "price": float(price_val), "time": now_iso})
                except Exception as e:
                    logger.error({"event": "price_monitor_error", "symbol": sym, "error": str(e)})
        except Exception as e:
            logger.error({"event": "price_monitor_loop_error", "error": str(e)})
        await asyncio.sleep(interval)

# --- Anchor Snapshot


































































































































































































































































































































































































































