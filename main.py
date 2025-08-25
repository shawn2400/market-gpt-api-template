# main.py
from __future__ import annotations
import os, asyncio, logging, json, time
from datetime import datetime, timezone
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse

IS_CLOUD = bool(os.getenv("RENDER") or os.getenv("RENDER_SERVICE_ID") or os.getenv("DYNO") or os.getenv("K_SERVICE"))
if not IS_CLOUD:
    from dotenv import load_dotenv
    load_dotenv(override=False)

def _to_bool(v: str | None, default: bool = False) -> bool:
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "on")

LIGHT_MODE = _to_bool(os.getenv("LIGHT_MODE", "0"))
SUPPRESS_BINANCE_WARNINGS = _to_bool(os.getenv("SUPPRESS_BINANCE_WARNINGS", "1"))

from utils.config import (
    dump_config_sanitized, LOG_LEVEL,
    PRICE_MONITOR_INTERVAL, PRICE_MONITOR_DISABLE,
    ENABLE_AI_ROUTES, OPENAI_API_KEY,
)
from utils.response_limits import ResponseSizeLimiter
from utils.json_logger import setup_json_logging
from utils.watchlist_utils import load_watchlist
from utils.binance_client import futures_mark_price
from utils.anchor import evaluate_anchor
from utils.rate_limit import RateLimitMiddleware
from utils import cache_fallback as redis_store

APP_VERSION = os.getenv("ALGOGPT_VERSION", "2.15.0")

logger = setup_json_logging()
logging.getLogger().setLevel(LOG_LEVEL)

if not LIGHT_MODE:
    from collections import deque
    LOG_BUFFER = deque(maxlen=int(os.getenv("LOG_BUFFER_SIZE", 200)))

    class MemoryLogHandler(logging.Handler):
        def emit(self, record):
            LOG_BUFFER.append({
                "time": datetime.now(timezone.utc).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            })
    logger.addHandler(MemoryLogHandler())

BINANCE_KEY = (os.getenv("BINANCE_API_KEY") or "").strip()
OPENAI_KEY = (os.getenv("OPENAI_API_KEY") or "").strip()

logger.info({
    "event": "env_loaded",
    "BINANCE_API_KEY_len": len(BINANCE_KEY),
    "OPENAI_API_KEY_len": len(OPENAI_KEY),
})
logger.info({"event": "config_snapshot", **dump_config_sanitized()})

if not BINANCE_KEY:
    logger.warning("⚠️ Binance API key not set → trading disabled")
if not OPENAI_KEY or OPENAI_KEY.startswith("YOUR_REAL_"):
    logger.warning("⚠️ OpenAI API key not set → AI may return fallback only")

app = FastAPI(title="AlgoGPT API", version=APP_VERSION, description="AlgoGPT — מסחר אלגוריתמי בזמן אמת")

app.add_middleware(ResponseSizeLimiter, max_bytes=int(os.getenv("RESPONSE_MAX_BYTES", 5_242_880)))
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.add_middleware(RateLimitMiddleware, limit=60, window=60, endpoint_limits={})

Path("static").mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Routers
from routes.ai import router as ai_router
from routes.multi_scan import router as scan_router
from routes.trade import router as trade_router
from routes.grid import router as grid_router
from routes.orderflow import router as orderflow_router
from routes.indicators import router as indicators_router
from routes.anchor import router as anchor_router
from routes.market import router as market_router
from routes.binance_status import router as binance_status_router
from routes.price import router as price_router
import routes.executor as executor_router

app.include_router(scan_router, tags=["Scan"])
app.include_router(trade_router, prefix="/trade", tags=["Trade"])
app.include_router(grid_router, prefix="/grid", tags=["Grid"])
app.include_router(orderflow_router, prefix="/orderflow", tags=["Orderflow"])
app.include_router(indicators_router, prefix="/indicators", tags=["Indicators"])
app.include_router(anchor_router, prefix="/anchor", tags=["Anchor"])
app.include_router(market_router, prefix="/market", tags=["Market"])  # ← עכשיו הנתיב תקין
app.include_router(binance_status_router, tags=["Binance"])
app.include_router(price_router, prefix="/price", tags=["Price"])

app.include_router(ai_router, prefix="/ai", tags=["AI"])
if ENABLE_AI_ROUTES and OPENAI_API_KEY and not OPENAI_API_KEY.startswith("YOUR_REAL_"):
    logger.info({"event": "ai_routes_enabled", "model": os.getenv("OPENAI_MODEL", "gpt-4o")})
else:
    logger.warning("⚠️ AI routes registered but may fallback (missing or placeholder OPENAI_API_KEY)")

app.include_router(executor_router.router, prefix="/executor", tags=["Executor"])

# ... (שאר הקוד – לולאות רקע, Health, Exception handler) ...






































































































































































































































































































































































































































































