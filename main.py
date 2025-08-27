# main.py
from __future__ import annotations
import os, logging
from pathlib import Path
from datetime import datetime, timezone
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse

# --- Env ---
IS_CLOUD = bool(
    os.getenv("RENDER") or
    os.getenv("RENDER_SERVICE_ID") or
    os.getenv("DYNO") or
    os.getenv("K_SERVICE")
)
if not IS_CLOUD:
    from dotenv import load_dotenv
    load_dotenv(override=False)

def _to_bool(v: str | None, default: bool = False) -> bool:
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "on")

LIGHT_MODE = _to_bool(os.getenv("LIGHT_MODE", "0"))

# --- Config ---
from utils import config as cfg
from utils.config import dump_config_sanitized, LOG_LEVEL
from utils.response_limits import ResponseSizeLimiter
from utils.json_logger import setup_json_logging
from utils.rate_limit import RateLimitMiddleware

APP_VERSION = os.getenv("ALGOGPT_VERSION", "2.15.6")

# --- Logging ---
logger = setup_json_logging()
logging.getLogger().setLevel(LOG_LEVEL)

# --- FastAPI ---
app = FastAPI(
    title="AlgoGPT API",
    version=APP_VERSION,
    description="AlgoGPT — מסחר אלגוריתמי בזמן אמת"
)

app.add_middleware(ResponseSizeLimiter, max_bytes=int(os.getenv("RESPONSE_MAX_BYTES", 5_242_880)))
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.add_middleware(RateLimitMiddleware, limit=60, window=60, endpoint_limits={})

Path("static").mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

# --- Routers ---
from routes.ai import router as ai_router
from routes.trade import router as trade_router
from routes.market import router as market_router
from routes.binance_status import router as binance_status_router
import routes.executor as executor_router

from routes.market_extra import router as market_extra_router
from routes.executor_extra import router as executor_extra_router
from routes.anchor_extra import router as anchor_extra_router
from routes.ws_stream import router as ws_stream_router
from routes.grid import router as grid_router
from routes.debug import router as debug_router

# Register routers
app.include_router(trade_router)
app.include_router(market_router)
app.include_router(binance_status_router)
app.include_router(ai_router)
app.include_router(executor_router.router)

# Extra routers
app.include_router(market_extra_router)
app.include_router(executor_extra_router)
app.include_router(anchor_extra_router)
app.include_router(ws_stream_router)
app.include_router(grid_router)
app.include_router(debug_router)

# --- Health ---
@app.get("/", tags=["Config"])
async def root_status():
    return {"ok": True, "status": "ok", "version": APP_VERSION}

@app.get("/health", tags=["Health"])
async def health():
    return {"ok": True, "status": "ok", "version": APP_VERSION}

@app.get("/health/live", tags=["Health"])
async def health_live():
    return {"ok": True, "status": "live"}

# --- Exception handler ---
@app.exception_handler(Exception)
async def handle_exception(request: Request, exc: Exception):
    logger.error({
        "event": "exception",
        "error": str(exc),
        "path": request.url.path,
        "time": datetime.now(timezone.utc).isoformat()
    })
    return JSONResponse({"detail": str(exc)}, status_code=500)

# --- Startup log ---
@app.on_event("startup")
async def startup_event():
    logger.info({
        "event": "startup",
        "APP_VERSION": APP_VERSION,
        "BINANCE_KEY_LEN": len(cfg.BINANCE_API_KEY or ""),
        "OPENAI_KEY_LEN": len(cfg.OPENAI_API_KEY or ""),
        "config": dump_config_sanitized()
    })

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)), reload=False)























































































































































































































































































































































































































































































