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

# --- Config ---
from utils.config import (
    check_config, dump_config_sanitized, LOG_LEVEL,
    WS_UPDATE_INTERVAL, PRICE_MONITOR_INTERVAL,
    PRICE_WS_FRESH_TTL, PRICE_MONITOR_DISABLE,
    ENABLE_AI_ROUTES, OPENAI_API_KEY,
)
from utils.response_limits import ResponseSizeLimiter
from utils.json_logger import setup_json_logging
from utils.ws_fallback import auto_price_updater, LAST_PRICE_CACHE, update_price
from utils.watchlist_utils import load_watchlist
from utils.binance_client import futures_mark_price
from utils.anchor import evaluate_anchor
from utils.rate_limit import RateLimitMiddleware
from utils import cache_fallback as redis_store
from utils.auth import require_api_key

# --- App Version ---
APP_VERSION = os.getenv("ALGOGPT_VERSION", "2.14.6")

# --- Logging ---
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

# --- Config check ---
check_config()
logger.info({"event": "config_snapshot", **dump_config_sanitized()})

# --- FastAPI ---
app = FastAPI(
    title="AlgoGPT API",
    version=APP_VERSION,
    description="AlgoGPT — מערכת מסחר אלגוריתמי בזמן אמת"
)

# --- Middlewares ---
app.add_middleware(ResponseSizeLimiter, max_bytes=int(os.getenv("RESPONSE_MAX_BYTES", 1_048_576)))
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ✅ Rate-limit
app.add_middleware(
    RateLimitMiddleware,
    limit=60,
    window=60,
    endpoint_limits={},
)

# --- Static ---
app.mount("/static", StaticFiles(directory="static"), name="static")

# --- Routers ---
from routes.ai import router as ai_router
from routes.multi_scan import router as scan_router
from routes.trade import router as trade_router
from routes.grid import router as grid_router
from routes.orderflow import router as orderflow_router
from routes.indicators import router as indicators_router
from routes.anchor import router as anchor_router
from routes.debug import router as debug_router

protected_routers = [
    (scan_router, "", ["Scan"]),
    (trade_router, "/trade", ["Trade"]),
    (grid_router, "/grid", ["Grid"]),
    (orderflow_router, "/orderflow", ["Orderflow"]),
    (indicators_router, "/indicators", ["Indicators"]),
    (anchor_router, "", ["Anchor"]),
]

# ✅ AI רק אם יש מפתח
if ENABLE_AI_ROUTES and OPENAI_API_KEY:
    protected_routers.append((ai_router, "/ai", ["AI"]))

for r, p, t in protected_routers:
    app.include_router(r, prefix=p, tags=t, dependencies=[Depends(require_api_key)])

# Debug router פתוח
app.include_router(debug_router, prefix="/debug", tags=["Debug"])

# --- Background tasks ---
async def price_monitor_loop(interval: int = PRICE_MONITOR_INTERVAL):
    while True:
        try:
            now_iso = datetime.now(timezone.utc).isoformat()
            for sym, rec in list(LAST_PRICE_CACHE.items()):
                try:
                    ts = float(rec.get("ts") or 0.0)
                except Exception:
                    ts = 0.0
                if (time.time() - ts) < PRICE_WS_FRESH_TTL:
                    continue
                try:
                    price_val = futures_mark_price(sym)
                    if price_val and price_val > 0:
                        update_price(sym, float(price_val))
                        logger.info({"event": "price_monitor", "symbol": sym, "price": float(price_val), "time": now_iso})
                except Exception as e:
                    logger.warning({"event": "price_monitor_error", "symbol": sym, "error": str(e)})
        except Exception as e:
            logger.error({"event": "price_monitor_loop_error", "error": str(e)})
        await asyncio.sleep(interval)

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

CACHE_DIR = Path("static/cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

async def cache_cleaner(interval: int = 3600, max_files: int = 100, max_age: int = 86400):
    while True:
        try:
            files = sorted(CACHE_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
            now = time.time()
            for f in files:
                if now - f.stat().st_mtime > max_age:
                    f.unlink(missing_ok=True)
            for f in files[max_files:]:
                f.unlink(missing_ok=True)
        except Exception as e:
            logger.error({"event": "cache_cleaner_error", "error": str(e)})
        await asyncio.sleep(interval)

# --- Startup ---
@app.on_event("startup")
async def startup_event():
    try:
        watchlist = load_watchlist()
        symbols = [it["symbol"] for it in watchlist]
        if "BTCUSDT" not in [s.upper() for s in symbols]:
            symbols.insert(0, "BTCUSDT")
        asyncio.create_task(auto_price_updater(symbols, interval=WS_UPDATE_INTERVAL))
        if not PRICE_MONITOR_DISABLE:
            asyncio.create_task(price_monitor_loop(interval=PRICE_MONITOR_INTERVAL))
        asyncio.create_task(anchor_snapshot_loop())
        asyncio.create_task(cache_cleaner())
    except Exception as e:
        logger.error({"event": "startup_error", "error": str(e)})

# --- Health / Status ---
@app.get("/", tags=["Config"])
async def root_status():
    return {"status": "ok", "version": APP_VERSION}

@app.get("/health", tags=["Health"])
async def health():
    return {"status": "ok", "version": APP_VERSION}

@app.get("/health/live", tags=["Health"])
async def health_live():
    return {"status": "live"}

@app.get("/debug/health", tags=["Debug"])
async def debug_health(limit: int = Query(50), level: str | None = None, logger_name: str | None = None):
    logs = list(LOG_BUFFER)[-limit:]
    if level:
        logs = [l for l in logs if l["level"] == level.upper()]
    if logger_name:
        logs = [l for l in logs if l["logger"] == logger_name]
    return {"count": len(logs), "logs": logs}

# --- Exception handler ---
@app.exception_handler(Exception)
async def handle_exception(request: Request, exc: Exception):
    logger.error({"event": "exception", "error": str(exc), "path": request.url.path})
    return JSONResponse({"detail": str(exc)}, status_code=500)

# --- Entrypoint ---
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)), reload=False)































































































































































































































































































































































































































