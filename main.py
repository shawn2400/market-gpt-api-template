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

# --- ENV: טוען .env רק כשלא בענן (כמו Render) ---
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
from utils import cache_fallback as redis_store  # מספק lpush/ltrim אסינכרוניים

APP_VERSION = os.getenv("ALGOGPT_VERSION", "2.15.0")

# --- Logging ---
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

# --- Config check ---
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

# --- FastAPI App ---
app = FastAPI(title="AlgoGPT API", version=APP_VERSION, description="AlgoGPT — מסחר אלגוריתמי בזמן אמת")

# Middlewares
app.add_middleware(ResponseSizeLimiter, max_bytes=int(os.getenv("RESPONSE_MAX_BYTES", 5_242_880)))
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.add_middleware(RateLimitMiddleware, limit=60, window=60, endpoint_limits={})

# Static
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
app.include_router(market_router, prefix="/market", tags=["Market"])
app.include_router(binance_status_router, tags=["Binance"])
app.include_router(price_router, tags=["Price"])  # כולל /price ו-/price/{symbol}

# ✅ AI Router – תמיד נרשם; לוג בהתאם לזמינות מפתח
app.include_router(ai_router, prefix="/ai", tags=["AI"])
if ENABLE_AI_ROUTES and OPENAI_KEY and not OPENAI_KEY.startswith("YOUR_REAL_"):
    logger.info({"event": "ai_routes_enabled", "model": os.getenv("OPENAI_MODEL", "gpt-4o")})
else:
    logger.warning("⚠️ AI routes registered but may fallback (missing or placeholder OPENAI_API_KEY)")

# ✅ Executor
app.include_router(executor_router.router, prefix="/executor", tags=["Executor"])

# --- Price Cache (in-process) ---
LAST_PRICE_CACHE: dict[str, dict[str, float | int]] = {}

def update_price_local(symbol: str, price: float) -> None:
    if price:
        LAST_PRICE_CACHE[symbol.upper()] = {"price": float(price), "ts": time.time()}

def get_price_local(symbol: str) -> float | None:
    info = LAST_PRICE_CACHE.get(symbol.upper(), {})
    return float(info["price"]) if "price" in info else None

def is_price_fresh(symbol: str, max_age_sec: int = 20) -> bool:
    info = LAST_PRICE_CACHE.get(symbol.upper())
    return bool(info and (time.time() - float(info.get("ts", 0))) <= max_age_sec)

# --- Background tasks ---
async def auto_anchor_updater_loop(interval: int = 20):
    """מעדכן עוגנים + קאש מחיר באופן רציף כדי להוריד לטנציה לקריאות /price."""
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
    while True:
        for sym in symbols:
            try:
                price = futures_mark_price(sym)
                if price and float(price) > 0:
                    update_price_local(sym, float(price))
                    logger.info({"event": "anchor_update", "symbol": sym, "price": float(price)})
            except Exception as e:
                logger.warning({"event": "anchor_update_error", "symbol": sym, "error": str(e)})
        await asyncio.sleep(interval)

async def price_monitor_loop(interval: int = PRICE_MONITOR_INTERVAL):
    """מרענן מחירים לכל מה שכבר בקאש, בקצב קבוע."""
    if PRICE_MONITOR_DISABLE:
        return
    while True:
        for sym in list(LAST_PRICE_CACHE.keys()):
            try:
                price_val = futures_mark_price(sym)
                if price_val:
                    update_price_local(sym, float(price_val))
            except Exception as e:
                logger.warning({"event": "price_monitor_error", "symbol": sym, "error": str(e)})
        await asyncio.sleep(interval)

async def anchor_snapshot_loop(interval: int = 30):
    """שומר היסטוריית Anchor ב-Redis (או נפילה לקאש בזיכרון)"""
    while True:
        for side in ["LONG", "SHORT"]:
            try:
                dec = evaluate_anchor(side)
                item = {
                    "ts": int(time.time()),
                    "side": side,
                    "bias": dec.bias,
                    "score": float(dec.score),
                    "allow": bool(dec.allow),
                }
                try:
                    await redis_store.lpush("anchor:history", json.dumps(item))
                    await redis_store.ltrim("anchor:history", 0, 200)
                except Exception as e:
                    logger.warning({"event": "anchor_snapshot_cache_error", "side": side, "error": str(e)})
            except Exception as e:
                logger.warning({"event": "anchor_snapshot_error", "side": side, "error": str(e)})
        await asyncio.sleep(interval)

# Startup
@app.on_event("startup")
async def startup_event():
    if LIGHT_MODE:
        logger.info({"event": "startup", "mode": "light"})
        return
    watchlist = load_watchlist()
    symbols = [it["symbol"].upper() for it in watchlist]
    if "BTCUSDT" not in symbols:
        symbols.insert(0, "BTCUSDT")
    # פרה-חימום קאש מקומי
    for s in symbols[:10]:
        try:
            p = futures_mark_price(s)
            if p:
                update_price_local(s, float(p))
        except Exception as e:
            logger.warning({"event": "warmup_price_error", "symbol": s, "error": str(e)})
    # יצירת משימות רקע
    asyncio.create_task(auto_anchor_updater_loop())
    asyncio.create_task(price_monitor_loop())
    asyncio.create_task(anchor_snapshot_loop())
    logger.info({"event": "startup", "mode": "normal", "watchlist_size": len(symbols)})

# Health
@app.get("/", tags=["Config"])
async def root_status():
    return {"status": "ok", "version": APP_VERSION, "mode": "light" if LIGHT_MODE else "normal"}

@app.get("/health", tags=["Health"])
async def health():
    return {"status": "ok", "version": APP_VERSION, "mode": "light" if LIGHT_MODE else "normal"}

@app.get("/health/live", tags=["Health"])
async def health_live():
    return {"status": "live"}

@app.get("/_routes", tags=["Debug"])
async def list_routes():
    routes_list = []
    for r in app.router.routes:
        methods = getattr(r, "methods", None)
        routes_list.append({
            "path": getattr(r, "path", None),
            "name": getattr(r, "name", None),
            "methods": list(methods) if methods else [],
            "type": r.__class__.__name__,
        })
    return routes_list

@app.exception_handler(Exception)
async def handle_exception(request: Request, exc: Exception):
    logger.error({"event": "exception", "error": str(exc)}, extra={"path": request.url.path})
    return JSONResponse({"detail": str(exc)}, status_code=500)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)), reload=False)




































































































































































































































































































































































































































































