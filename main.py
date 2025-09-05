# main.py
# =======
from __future__ import annotations
import os, asyncio, logging
from pathlib import Path
from typing import List

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from starlette.middleware.gzip import GZipMiddleware

IS_CLOUD = bool(os.getenv("RENDER") or os.getenv("RENDER_SERVICE_ID") or os.getenv("DYNO") or os.getenv("K_SERVICE"))
if not IS_CLOUD:
    try:
        from dotenv import load_dotenv
        load_dotenv(override=False)
    except Exception:
        pass

def _to_bool(v: str | None, default: bool = False) -> bool:
    return default if v is None else str(v).strip().lower() in ("1", "true", "yes", "on")

def _parse_csv(s: str | None) -> List[str]:
    return [x.strip() for x in (s or "").split(",") if x.strip()]

APP_VERSION = os.getenv("ALGOGPT_VERSION", "2.17.0")

from utils import config as cfg  # noqa: F401
from utils.config import dump_config_sanitized, LOG_LEVEL
from utils.response_limits import ResponseSizeLimiter
from utils.json_logger import setup_json_logging
from utils.auth import extract_token, allow_all, token_matches
from utils.time_sync import sync_now, start_background_sync, ensure_fresh_sync
from utils.binance_client import futures_balance, fapi_ping
from utils.ws_fallback import auto_price_updater, is_price_fresh
from utils.open_trade_manager import manage_open_trades
from utils.auto_executor import start_executor, stop_executor
from utils.metrics import metrics_tracker

try:
    from utils.user_stream import start_user_stream_consumer, stop_user_stream_consumer
except Exception:
    async def start_user_stream_consumer(): return None
    async def stop_user_stream_consumer(): return None

logger = setup_json_logging()
logging.getLogger().setLevel(LOG_LEVEL)

def _ensure_dir(path: str) -> bool:
    try:
        Path(path).mkdir(parents=True, exist_ok=True)
        return True
    except Exception as e:
        logger.warning({"event": "mkdir_failed", "dir": path, "error": str(e)})
        return False

static_ok = _ensure_dir("static")
_ = _ensure_dir("logs")

app = FastAPI(title="AlgoGPT API", version=APP_VERSION, description="AlgoGPT — מסחר אלגוריתמי בזמן אמת אפשרי")
app.add_middleware(ResponseSizeLimiter, max_bytes=int(os.getenv("RESPONSE_MAX_BYTES", "5242880")))
app.add_middleware(GZipMiddleware, minimum_size=1000)

CORS_ALLOWED = os.getenv("CORS_ALLOW_ORIGINS", "*").strip()
CORS_ALLOW_CREDENTIALS = _to_bool(os.getenv("CORS_ALLOW_CREDENTIALS", "0"), False)
if CORS_ALLOWED == "*" and CORS_ALLOW_CREDENTIALS:
    CORS_ALLOW_CREDENTIALS = False

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if CORS_ALLOWED == "*" else _parse_csv(CORS_ALLOWED),
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=CORS_ALLOW_CREDENTIALS,
)

try:
    if static_ok and os.access("static", os.R_OK):
        app.mount("/static", StaticFiles(directory="static"), name="static")
except Exception as e:
    logger.warning({"event": "static_mount_failed", "error": str(e)})

@app.middleware("http")
async def validate_token(request: Request, call_next):
    PUBLIC_PATHS = {
        "/", "/openapi.json", "/health", "/readyz", "/docs", "/redoc",
        "/telegram/webhook", "/telegram/callbacks", "/ui/dashboard"
    }
    PUBLIC_PREFIXES = ["/price", "/static/"]
    path = request.url.path
    if request.method.upper() == "OPTIONS" or path in PUBLIC_PATHS or any(path.startswith(p) for p in PUBLIC_PREFIXES):
        return await call_next(request)
    if allow_all():
        return await call_next(request)
    token = extract_token(request, request.headers.get("Authorization", ""), request.headers.get("X-API-Key"))
    if not token_matches(token):
        return JSONResponse(status_code=401, content={"detail": "Invalid API key"})
    return await call_next(request)

@app.middleware("http")
async def track_metrics(request: Request, call_next):
    start = asyncio.get_event_loop().time()
    try:
        response = await call_next(request)
    except Exception:
        metrics_tracker.observe_request(500, (asyncio.get_event_loop().time() - start) * 1000)
        raise
    else:
        metrics_tracker.observe_request(response.status_code, (asyncio.get_event_loop().time() - start) * 1000)
        return response

# ✅ עדכון רשימת ה-routers: כולל Telegram callbacks
ROUTERS: List[str] = [
    "routes.trade", "routes.market", "routes.binance_status", "routes.executor", "routes.orders", "routes.price",
    "routes.rpc", "routes.market_extra", "routes.executor_extra", "routes.anchor_extra",
    "routes.grid", "routes.debug", "routes.indicators", "routes.indicators_extra",
    "routes.telegram_bot", "routes.telegram_routes", "routes.telegram_callbacks",
    "routes.metrics", "routes.metrics_extra", "routes.precision", "routes.alerts",
    "routes.reconcile", "routes.scheduler_ai", "routes.admin", "routes.export", "routes.pnl",
    "routes.ui", "routes.backtest", "routes.ui_grid",
    # NEW:
    "routes.orderbook", "routes.ws", "routes.ws_health", "routes.orderflow"
]
if _to_bool(os.getenv("ENABLE_AI_ROUTES", "1"), True):
    ROUTERS.append("routes.ai")

def _include_router(path: str) -> None:
    try:
        mod = __import__(path, fromlist=["router", "router_public"])
        if hasattr(mod, "router"):
            app.include_router(getattr(mod, "router"))
        if hasattr(mod, "router_public"):
            app.include_router(getattr(mod, "router_public"))
    except Exception as e:
        logger.warning({"event": "router_register_failed", "router": path, "error": str(e)})

for r in ROUTERS:
    _include_router(r)

@app.get("/")
async def root_status():
    return {"ok": True, "status": "ok", "version": APP_VERSION}

@app.get("/health")
async def health():
    return {"ok": True, "status": "ok", "version": APP_VERSION}

@app.get("/readyz")
async def readyz():
    details: dict[str, any] = {}
    try:
        ensure_fresh_sync()
        details["ping_ok"] = bool(fapi_ping())
        details["balance_ok"] = isinstance(futures_balance(), list)
        syms = _parse_csv(os.getenv("HEALTH_SYMBOLS", "BTCUSDT,ETHUSDT"))
        prices_ok = all(is_price_fresh(sym) for sym in syms)
        for sym in syms:
            details[f"price_{sym}"] = is_price_fresh(sym)
        return {"ok": bool(details["ping_ok"] and details["balance_ok"] and prices_ok), "details": details}
    except Exception as e:
        return {"ok": False, "error": str(e), "details": details}

@app.on_event("startup")
async def startup_event():
    logger.info({"event": "startup", "version": APP_VERSION, "config": dump_config_sanitized()})
    try: sync_now(); start_background_sync()
    except: pass
    try: asyncio.create_task(auto_price_updater(_parse_csv(os.getenv("SYMS", "BTCUSDT,ETHUSDT"))))
    except: pass
    try: await start_user_stream_consumer()
    except: pass

@app.on_event("shutdown")
async def shutdown_event():
    try: await stop_user_stream_consumer()
    except: pass

@app.post("/start-executor")
async def api_start_executor(): start_executor(); return {"ok": True}

@app.post("/stop-executor")
async def api_stop_executor(): stop_executor(); return {"ok": True}

@app.post("/manage-once")
async def api_manage_once(): await manage_open_trades(); return {"ok": True}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=os.getenv("BIND_HOST", "0.0.0.0"), port=int(os.getenv("PORT", "8000")))





























































































































































































































































































































































































































































































































