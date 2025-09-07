# main.py
from __future__ import annotations
import os, asyncio, logging
from pathlib import Path
from typing import List
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.gzip import GZipMiddleware

# ===== Env =====
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

# ===== Imports =====
from utils import config as cfg
from utils.config import dump_config_sanitized, LOG_LEVEL
from utils.response_limits import ResponseSizeLimiter
from utils.json_logger import setup_json_logging
from utils.auth import extract_token, allow_all, token_matches
from utils.time_sync import sync_now, start_background_sync, ensure_fresh_sync
from utils.binance_client import futures_balance, fapi_ping
from utils.ws_fallback import auto_price_updater, is_price_fresh
# >> תיקון: ניהול טריידים מיובא מ-utils.trade_manager
from utils.trade_manager import manage_open_trades, manage_open_trades_loop
from utils.auto_executor import start_executor, stop_executor
from utils.metrics import metrics_tracker
from utils.log_auto import log_auto  # בקר לוג אוטומטי

# >> הוספה: מידלוור פנימי לאימות Bearer+HMAC+Idempotency עבור /alerts ו-/risk
from app.middlewares import InternalAuthMiddleware

try:
    from utils.user_stream import start_user_stream_consumer, stop_user_stream_consumer
except Exception:
    async def start_user_stream_consumer(): return None
    async def stop_user_stream_consumer(): return None

logger = setup_json_logging()
logging.getLogger().setLevel(LOG_LEVEL)

# יצירת תיקיות בסיס
for d in ("static", "logs"):
    try:
        Path(d).mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.warning({"event": "mkdir_failed", "dir": d, "error": str(e)})

app = FastAPI(title="AlgoGPT API", version=APP_VERSION, description="AlgoGPT — מסחר אלגוריתמי בזמן אמת")
app.add_middleware(ResponseSizeLimiter, max_bytes=int(os.getenv("RESPONSE_MAX_BYTES", "5242880")))
app.add_middleware(GZipMiddleware, minimum_size=1000)

# ===== CORS =====
UI_DOMAIN = os.getenv("UI_DOMAIN", "").strip()
CORS_ALLOWED = [UI_DOMAIN] if UI_DOMAIN else _parse_csv(os.getenv("CORS_ALLOW_ORIGINS", "*"))
CORS_ALLOW_CREDENTIALS = _to_bool(os.getenv("CORS_ALLOW_CREDENTIALS", "0"), False)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if not CORS_ALLOWED else CORS_ALLOWED,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=CORS_ALLOW_CREDENTIALS,
)

# >> הוספה: מידלוור פנימי שמאבטח /alerts* ו-/risk* עם HMAC+Bearer+Idem
app.add_middleware(InternalAuthMiddleware)

# ===== Middleware =====
@app.middleware("http")
async def validate_token(request: Request, call_next):
    # >> הרחבתי את הרשימה כך שהאימות הכללי לא ייחול על /alerts ו-/risk
    PUBLIC_PATHS = {
        "/", "/openapi.json", "/health", "/readyz", "/docs", "/redoc",
        "/telegram/webhook", "/telegram/callbacks"
    }
    PUBLIC_PREFIXES = ["/price", "/static/", "/alerts", "/risk"]
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
        dur_ms = (asyncio.get_event_loop().time() - start) * 1000.0
        metrics_tracker.observe_request(500, dur_ms)
        log_auto.observe(500, dur_ms)
        raise
    else:
        dur_ms = (asyncio.get_event_loop().time() - start) * 1000.0
        metrics_tracker.observe_request(response.status_code, dur_ms)
        log_auto.observe(response.status_code, dur_ms)
        return response

# ===== Routers =====
ROUTERS: List[str] = [
    "routes.trade","routes.market","routes.binance_status","routes.executor","routes.orders","routes.price",
    "routes.rpc","routes.market_extra","routes.executor_extra","routes.anchor_extra",
    "routes.grid","routes.debug","routes.indicators","routes.indicators_extra",
    "routes.telegram_bot","routes.telegram_callbacks",
    "routes.metrics","routes.metrics_extra","routes.precision","routes.alerts",
    "routes.reconcile","routes.scheduler_ai","routes.admin","routes.export","routes.pnl",
    "routes.ui","routes.backtest","routes.ui_grid","routes.orderbook","routes.ws","routes.ws_health","routes.orderflow"
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
        logger.info({"event": "router_registered", "router": path})
    except Exception as e:
        logger.warning({"event": "router_register_failed", "router": path, "error": str(e)})

for r in ROUTERS:
    _include_router(r)

# ===== Endpoints =====
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
        syms = _parse_csv(os.getenv("HEALTH_SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT"))
        prices_ok = all(is_price_fresh(sym) for sym in syms)
        for sym in syms:
            details[f"price_{sym}"] = is_price_fresh(sym)
        return {"ok": bool(details["ping_ok"] and details["balance_ok"] and prices_ok), "details": details}
    except Exception as e:
        return {"ok": False, "error": str(e), "details": details}

@app.on_event("startup")
async def startup_event():
    logger.info({"event": "startup", "version": APP_VERSION, "config": dump_config_sanitized()})
    try:
        sync_now(); start_background_sync()
    except:
        pass
    try:
        asyncio.create_task(auto_price_updater(_parse_csv(os.getenv("WATCHLIST", "BTCUSDT,ETHUSDT,SOLUSDT"))))
    except:
        pass
    try:
        await start_user_stream_consumer()
    except:
        pass
    try:
        asyncio.create_task(manage_open_trades_loop(interval=20))
    except:
        pass
    try:
        from services.telegram_daily import start_daily_summaries
        asyncio.create_task(start_daily_summaries())
    except:
        pass

@app.on_event("shutdown")
async def shutdown_event():
    try:
        await stop_user_stream_consumer()
    except:
        pass

@app.post("/start-executor")
async def api_start_executor():
    start_executor()
    return {"ok": True}

@app.post("/stop-executor")
async def api_stop_executor():
    stop_executor()
    return {"ok": True}

@app.post("/manage-once")
async def api_manage_once():
    await manage_open_trades()
    return {"ok": True}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=os.getenv("BIND_HOST", "0.0.0.0"), port=int(os.getenv("PORT", "10000")))


































































































































































































































































































































































































































































































































