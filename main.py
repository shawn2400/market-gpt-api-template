# ==========================
# main.py
# ==========================
from __future__ import annotations
import os, asyncio, logging
from pathlib import Path
from typing import List, Any
from fastapi import FastAPI, Request, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.gzip import GZipMiddleware
from prometheus_client import make_asgi_app

IS_CLOUD = bool(os.getenv("RENDER") or os.getenv("RENDER_SERVICE_ID") or os.getenv("DYNO") or os.getenv("K_SERVICE"))
if not IS_CLOUD:
    try:
        from dotenv import load_dotenv
        load_dotenv(override=False)
    except Exception:
        pass

from utils import config as cfg
from utils.config import dump_config_sanitized, LOG_LEVEL
from utils.response_limits import ResponseSizeLimiter
from utils.json_logger import setup_json_logging
from utils.auth import extract_token, allow_all, token_matches
from utils.time_sync import sync_now, start_background_sync, ensure_fresh_sync
from utils.binance_client import futures_balance, fapi_ping
from utils.ws_fallback import auto_price_updater, is_price_fresh
from utils.trade_manager import manage_open_trades, manage_open_trades_loop
from utils.auto_executor import start_executor, stop_executor
from utils.log_auto import log_auto
from utils.metrics_middleware import MetricsMiddleware
from app.middlewares import InternalAuthMiddleware

try:
    from utils.user_stream import start_user_stream_consumer, stop_user_stream_consumer
except Exception:
    async def start_user_stream_consumer(): return None
    async def stop_user_stream_consumer(): return None

logger = setup_json_logging()
logging.getLogger().setLevel(LOG_LEVEL)
for d in ("static", "logs"):
    try: Path(d).mkdir(parents=True, exist_ok=True)
    except Exception as e: logger.warning({"event": "mkdir_failed", "dir": d, "error": str(e)})

app = FastAPI(title="AlgoGPT API", version=os.getenv("ALGOGPT_VERSION", "2.17.0"), description="AlgoGPT - מסחר אלגוריתמי")
app.add_middleware(ResponseSizeLimiter, max_bytes=int(os.getenv("RESPONSE_MAX_BYTES", "5242880")))
app.add_middleware(GZipMiddleware, minimum_size=1000)
UI_DOMAIN = os.getenv("UI_DOMAIN", "").strip()
CORS_ALLOWED = [UI_DOMAIN] if UI_DOMAIN else os.getenv("CORS_ALLOW_ORIGINS", "*").split(",")
CORS_ALLOW_CREDENTIALS = os.getenv("CORS_ALLOW_CREDENTIALS", "0") in ("1", "true")
app.add_middleware(CORSMiddleware, allow_origins=["*"] if not CORS_ALLOWED else CORS_ALLOWED, allow_methods=["*"], allow_headers=["*"], allow_credentials=CORS_ALLOW_CREDENTIALS)
app.add_middleware(InternalAuthMiddleware)
app.add_middleware(MetricsMiddleware)
app.mount("/metrics", make_asgi_app())

@app.middleware("http")
async def validate_token(request: Request, call_next):
    PUBLIC_PATHS = {"/", "/openapi.json", "/health", "/healthz", "/readyz", "/docs", "/redoc", "/telegram/webhook"}
    PUBLIC_PREFIXES = ["/price", "/static/", "/alerts", "/risk", "/metrics"]
    path = request.url.path
    if request.method.upper() == "OPTIONS" or path in PUBLIC_PATHS or any(path.startswith(p) for p in PUBLIC_PREFIXES):
        return await call_next(request)
    if allow_all(): return await call_next(request)
    token = extract_token(request, request.headers.get("Authorization", ""), request.headers.get("X-API-Key"))
    if not token_matches(token):
        return JSONResponse(status_code=401, content={"detail": "Invalid API key"})
    return await call_next(request)

ROUTERS = ["routes.trade"]
for r in ROUTERS:
    try:
        mod = __import__(r, fromlist=["router"])
        if hasattr(mod, "router"):
            app.include_router(mod.router)
    except Exception as e:
        logger.warning({"event": "router_register_failed", "router": r, "error": str(e)})

@app.get("/")
async def root(): return {"ok": True, "status": "ok"}
@app.get("/health")
async def health(): return {"ok": True, "status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "10000")))

















































































































































































































































































































































































































































































































































