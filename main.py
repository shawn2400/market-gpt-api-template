# main.py
from __future__ import annotations

import os
import asyncio
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Tuple, Optional, Dict, Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse

# --- סביבות ענן ---
IS_CLOUD = bool(os.getenv("RENDER") or os.getenv("RENDER_SERVICE_ID") or os.getenv("DYNO") or os.getenv("K_SERVICE"))
if not IS_CLOUD:
    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv(override=False)
    except Exception:
        pass

# --- עזרי קונפיג ---
def _to_bool(v: str | None, default: bool = False) -> bool:
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "on")

def _parse_csv(s: str | None) -> List[str]:
    s = s or ""
    return [x.strip() for x in s.split(",") if x.strip()]

def _clean_key(s: str | None) -> str:
    return (s or "").strip().strip('"').replace("\r", "").replace("\n", "").replace("\t", "")

APP_VERSION = os.getenv("ALGOGPT_VERSION", "2.17.0")

# --- Utils ---
from utils import config as cfg  # noqa: F401
from utils.config import dump_config_sanitized, LOG_LEVEL
from utils.response_limits import ResponseSizeLimiter
from utils.json_logger import setup_json_logging

from utils.auth import extract_token, allow_all, token_matches
from utils.time_sync import sync_now, start_background_sync, ensure_fresh_sync, last_server_time_ms
from utils.binance_client import fapi_ping, futures_balance, start_user_stream_keepalive, stop_user_stream
from utils.ws_fallback import auto_price_updater, is_price_fresh, get_price
from utils.open_trade_manager import manage_open_trades
from utils.auto_executor import start_executor, stop_executor, is_executor_running

# Optional
try:
    from utils.user_stream import start_user_stream_consumer, stop_user_stream_consumer
except Exception:
    async def start_user_stream_consumer(): return None
    async def stop_user_stream_consumer(): return None

logger = setup_json_logging()
logging.getLogger().setLevel(LOG_LEVEL)

# --- תיקיות ---
def _ensure_dir(path: str) -> bool:
    p = Path(path)
    try:
        p.mkdir(parents=True, exist_ok=True)
        return True
    except PermissionError:
        logger.warning({"event": "mkdir_permission_denied", "dir": path})
        return False
    except Exception as e:
        logger.warning({"event": "mkdir_failed", "dir": path, "error": str(e)})
        return False

static_ok = _ensure_dir("static")
_ = _ensure_dir("logs")

app = FastAPI(title="AlgoGPT API", version=APP_VERSION, description="AlgoGPT — מסחר אלגוריתמי בזמן אמת")

app.add_middleware(ResponseSizeLimiter, max_bytes=int(os.getenv("RESPONSE_MAX_BYTES", "5242880")))
app.add_middleware(GZipMiddleware, minimum_size=1000)

CORS_ALLOWED = (os.getenv("CORS_ALLOW_ORIGINS", "*") or "*").strip()
CORS_ALLOW_CREDENTIALS = _to_bool(os.getenv("CORS_ALLOW_CREDENTIALS", "0"), False)
if CORS_ALLOWED == "*" and CORS_ALLOW_CREDENTIALS:
    CORS_ALLOW_CREDENTIALS = False
allow_origins = ["*"] if CORS_ALLOWED == "*" else _parse_csv(CORS_ALLOWED)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=CORS_ALLOW_CREDENTIALS,
)

try:
    if static_ok and os.access("static", os.R_OK):
        app.mount("/static", StaticFiles(directory="static"), name="static")
except Exception as e:
    logger.warning({"event": "static_mount_failed", "error": str(e)})

# --- Auth Middleware ---
@app.middleware("http")
async def validate_token(request: Request, call_next):
    PUBLIC_PATHS = {"/", "/openapi.json", "/health", "/readyz", "/docs", "/redoc", "/telegram/webhook"}
    PUBLIC_PREFIXES = ["/price", "/static/"]
    path = request.url.path
    if request.method.upper() == "OPTIONS": return await call_next(request)
    if path in PUBLIC_PATHS or any(path.startswith(p) for p in PUBLIC_PREFIXES): return await call_next(request)
    if allow_all(): return await call_next(request)
    token = extract_token(request, authorization=request.headers.get("Authorization", ""), x_api_key=request.headers.get("X-API-Key"))
    if not token_matches(token): return JSONResponse(status_code=401, content={"detail": "Invalid API key"})
    return await call_next(request)

# --- Routers ---
def _include_router(module_path: str, attr: str = "router") -> None:
    try:
        mod = __import__(module_path, fromlist=[attr])
        router = getattr(mod, attr)
        app.include_router(router)
        logger.info({"event": "router_registered", "router": module_path})
    except Exception as e:
        logger.warning({"event": "router_register_failed", "router": module_path, "error": str(e)})

ALL_ROUTERS: List[str] = [
    "routes.trade", "routes.market", "routes.binance_status", "routes.executor", "routes.orders",
    "routes.price", "routes.rpc", "routes.market_extra", "routes.executor_extra", "routes.anchor_extra",
    "routes.ws_stream", "routes.grid", "routes.debug", "routes.indicators", "routes.indicators_extra",
    "routes.telegram_bot", "routes.metrics_extra", "routes.precision", "routes.alerts", "routes.reconcile",
    "routes.scheduler_ai", "routes.admin", "routes.export", "routes.pnl", "routes.ui", "routes.backtest"
]

if _to_bool(os.getenv("ENABLE_AI_ROUTES", "1"), True):
    ALL_ROUTERS.append("routes.ai")

for mod in ALL_ROUTERS: _include_router(mod)

@app.get("/")
async def root_status(): return {"ok": True, "status": "ok", "version": APP_VERSION}

@app.get("/health")
async def health(): return {"ok": True, "status": "ok", "version": APP_VERSION}

@app.get("/readyz")
async def readyz():
    try:
        ensure_fresh_sync()
        ex_ok = bool(futures_balance())
        syms = _parse_csv(os.getenv("HEALTH_SYMBOLS", "BTCUSDT,ETHUSDT"))
        prices_ok = all(is_price_fresh(sym) for sym in syms)
        return {"ok": ex_ok and prices_ok}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.on_event("startup")
async def startup_event():
    logger.info({"event": "startup", "version": APP_VERSION})
    try: sync_now(); start_background_sync() except: pass
    try: start_user_stream_keepalive() except: pass
    try:
        syms = _parse_csv(os.getenv("SYMS", "BTCUSDT,ETHUSDT"))
        if syms: asyncio.create_task(auto_price_updater(syms))
    except: pass
    try: await start_user_stream_consumer() except: pass

@app.on_event("shutdown")
async def shutdown_event():
    try: await stop_user_stream_consumer() except: pass
    try: stop_user_stream() except: pass

@app.post("/start-executor")
async def api_start_executor(): start_executor(); return {"ok": True}

@app.post("/stop-executor")
async def api_stop_executor(): stop_executor(); return {"ok": True}

@app.post("/manage-once")
async def api_manage_once(): await manage_open_trades(); return {"ok": True}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=os.getenv("BIND_HOST", "0.0.0.0"), port=int(os.getenv("PORT", "8000")))





















































































































































































































































































































































































































































































































