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

# ──────────────────────────────────────────────────────────────────────────────
# Env / Local .env
# ──────────────────────────────────────────────────────────────────────────────
IS_CLOUD = bool(os.getenv("RENDER") or os.getenv("RENDER_SERVICE_ID") or os.getenv("DYNO") or os.getenv("K_SERVICE"))
if not IS_CLOUD:
    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv(override=False)
    except Exception:
        pass

def _to_bool(v: str | None, default: bool = False) -> bool:
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "on")

def _parse_csv(s: str | None) -> List[str]:
    s = s or ""
    return [x.strip() for x in s.split(",") if x.strip()]

def _clean_key(s: str | None) -> str:
    # מסיר מרכאות/שבירות שורה/טאבים ורווחי קצה
    return (s or "").strip().strip('"').replace("\r", "").replace("\n", "").replace("\t", "")

APP_VERSION = os.getenv("ALGOGPT_VERSION", "2.15.8")

# ──────────────────────────────────────────────────────────────────────────────
# Config & Logging
# ──────────────────────────────────────────────────────────────────────────────
from utils import config as cfg
from utils.config import dump_config_sanitized, LOG_LEVEL
from utils.response_limits import ResponseSizeLimiter
from utils.json_logger import setup_json_logging

# Binance helpers
from utils.binance_client import (
    fapi_ping, futures_balance,
    start_user_stream_keepalive, stop_user_stream,
)
from utils.ws_fallback import auto_price_updater, is_price_fresh, get_price

logger = setup_json_logging()
logging.getLogger().setLevel(LOG_LEVEL)

# ──────────────────────────────────────────────────────────────────────────────
# Filesystem prep (don’t crash on RO FS)
# ──────────────────────────────────────────────────────────────────────────────
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

# ──────────────────────────────────────────────────────────────────────────────
# FastAPI app
# ──────────────────────────────────────────────────────────────────────────────
app = FastAPI(title="AlgoGPT API", version=APP_VERSION, description="AlgoGPT — מסחר אלגוריתמי בזמן אמת")

# Response size cap (~5MB default)
app.add_middleware(ResponseSizeLimiter, max_bytes=int(os.getenv("RESPONSE_MAX_BYTES", "5242880")))
# GZip for large responses
app.add_middleware(GZipMiddleware, minimum_size=1000)

# CORS
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

# Static (skip if RO/no access)
try:
    if static_ok and os.access("static", os.R_OK):
        app.mount("/static", StaticFiles(directory="static"), name="static")
    else:
        logger.warning({"event": "static_mount_skipped", "reason": "no_access_or_not_ok"})
except Exception as e:
    logger.warning({"event": "static_mount_failed", "error": str(e)})

# ──────────────────────────────────────────────────────────────────────────────
# Authorization (Bearer / X-API-Key)
# ──────────────────────────────────────────────────────────────────────────────
def _split_tokens(val: str | None) -> list[str]:
    if not val:
        return []
    s = val.replace("\n", ",").replace(";", ",")
    return [t.strip() for t in s.split(",") if t.strip()]

def _load_tokens() -> set[str]:
    raw = [
        os.getenv("API_BEARER_TOKEN"),
        os.getenv("API_BEARER_TOKEN_ALT"),
        *_split_tokens(os.getenv("ALGOGPT_TOKENS")),
    ]
    toks: set[str] = set()
    for t in raw:
        ct = _clean_key(t)
        if ct:
            toks.add(ct)
    return toks

TOKENS = _load_tokens()
ALLOW_ALL = _to_bool(os.getenv("SECURITY_ALLOW_ALL", "0"), False)
logger.info({"event": "auth_tokens_loaded", "count": len(TOKENS), "allow_all": ALLOW_ALL})

@app.middleware("http")
async def validate_token(request: Request, call_next):
    # פותחים מפורשות את המסלולים הציבוריים
    PUBLIC_PATHS = {
        "/", "/openapi.json",
        "/health", "/health/live", "/health_full",
        "/docs", "/redoc",
    }
    path = request.url.path

    # לא לחסום preflight
    if request.method.upper() == "OPTIONS":
        return await call_next(request)

    # סטטיק תמיד פתוח
    if path in PUBLIC_PATHS or path.startswith("/static/"):
        return await call_next(request)

    # מצב פתוח או אין טוקנים → לא לאכוף
    if ALLOW_ALL or not TOKENS:
        return await call_next(request)

    # אימות Bearer / X-API-Key / ?api_key
    auth_header = request.headers.get("Authorization", "")
    token = None
    if auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", 1)[1].strip()
    if not token:
        token = (request.headers.get("X-API-Key") or "").strip() or None
    if not token:
        qp = request.query_params.get("api_key")
        token = qp.strip() if qp else None

    if token not in TOKENS:
        return JSONResponse(status_code=401, content={"detail": "Invalid API key"})
    return await call_next(request)

# ──────────────────────────────────────────────────────────────────────────────
# Routers
# ──────────────────────────────────────────────────────────────────────────────
def _include_router(module_path: str, attr: str = "router") -> None:
    try:
        mod = __import__(module_path, fromlist=[attr])
        router = getattr(mod, attr)
        app.include_router(router)
        logger.info({"event": "router_registered", "router": module_path})
    except Exception as e:
        logger.warning({"event": "router_register_failed", "router": module_path, "error": str(e)})

CORE_ROUTERS: List[Tuple[str, str]] = [
    ("routes.trade", "router"),
    ("routes.market", "router"),
    ("routes.binance_status", "router"),
    ("routes.executor", "router"),
    ("routes.orders", "router"),
    ("routes.price", "router"),        # /price
]
if _to_bool(os.getenv("ENABLE_AI_ROUTES", "1"), True):
    CORE_ROUTERS.append(("routes.ai", "router"))

EXTRA_ROUTERS: List[Tuple[str, str]] = [
    ("routes.market_extra", "router"),
    ("routes.executor_extra", "router"),
    ("routes.anchor_extra", "router"),
    ("routes.ws_stream", "router"),
    ("routes.grid", "router"),
    ("routes.debug", "router"),
    ("routes.indicators", "router"),   # /indicators
]
for mod, attr in CORE_ROUTERS:
    _include_router(mod, attr)
for mod, attr in EXTRA_ROUTERS:
    _include_router(mod, attr)

# ──────────────────────────────────────────────────────────────────────────────
# Root & Health
# ──────────────────────────────────────────────────────────────────────────────
@app.get("/", tags=["Config"])
async def root_status():
    return {"ok": True, "status": "ok", "version": APP_VERSION}

@app.get("/health", tags=["Health"])
async def health():
    return {"ok": True, "status": "ok", "version": APP_VERSION}

@app.get("/health/live", tags=["Health"])
async def health_live():
    return {"ok": True, "status": "live"}

@app.get("/health_full", tags=["Health"])
async def health_full():
    k = _clean_key(os.getenv("BINANCE_API_KEY")); s = _clean_key(os.getenv("BINANCE_API_SECRET"))
    key_len = len(k); sec_len = len(s)

    try:
        ping_ok = bool(fapi_ping())
    except Exception as e:
        ping_ok = False
        logger.warning({"event": "health_ping_error", "error": str(e)})

    try:
        bal = futures_balance()
        account_ok = isinstance(bal, list)
    except Exception as e:
        account_ok = False
        logger.warning({"event": "health_account_error", "error": str(e)})

    try:
        lk = start_user_stream_keepalive(period_sec=int(os.getenv("LISTENKEY_KEEPALIVE_SEC", "1800")))
        listen_key_ok = bool(lk)
    except Exception as e:
        listen_key_ok = False
        logger.warning({"event": "health_listenkey_error", "error": str(e)})

    symbols = _parse_csv(os.getenv("HEALTH_SYMBOLS", "BTCUSDT,ETHUSDT"))
    prices: Dict[str, Any] = {}
    for sym in symbols:
        prices[sym] = {
            "fresh": is_price_fresh(sym, max_age_sec=int(os.getenv("HEALTH_PRICE_MAX_AGE", "30"))),
            "price": get_price(sym),
        }

    return {
        "ok": bool((key_len == 64) and (sec_len == 64) and account_ok),
        "version": APP_VERSION,
        "binance": {
            "key_len": key_len,
            "secret_len": sec_len,
            "fapi_time_ok": ping_ok,
            "account_ok": account_ok,
            "listenKey_ok": listen_key_ok,
        },
        "prices": prices,
        "time": datetime.now(timezone.utc).isoformat(),
    }

# ──────────────────────────────────────────────────────────────────────────────
# Exception handler
# ──────────────────────────────────────────────────────────────────────────────
@app.exception_handler(Exception)
async def handle_exception(request: Request, exc: Exception):
    logger.error({
        "event": "exception",
        "error": str(exc),
        "type": exc.__class__.__name__,
        "path": request.url.path,
        "time": datetime.now(timezone.utc).isoformat(),
    })
    return JSONResponse({"detail": str(exc)}, status_code=500)

# ──────────────────────────────────────────────────────────────────────────────
# Startup / Shutdown
# ──────────────────────────────────────────────────────────────────────────────
_price_task: Optional[asyncio.Task] = None

@app.on_event("startup")
async def startup_event():
    global _price_task
    logger.info({
        "event": "startup",
        "APP_VERSION": APP_VERSION,
        "BINANCE_KEY_LEN": len(_clean_key(os.getenv("BINANCE_API_KEY"))),
        "OPENAI_KEY_LEN": len((os.getenv("OPENAI_API_KEY") or "").strip()),
        "config": dump_config_sanitized(),
    })
    try:
        start_user_stream_keepalive(period_sec=int(os.getenv("LISTENKEY_KEEPALIVE_SEC", "1800")))
        logger.info({"event": "listen_key_keepalive_started"})
    except Exception as e:
        logger.warning({"event": "listen_key_keepalive_failed", "error": str(e)})

    syms = [s.strip().upper() for s in os.getenv("SYMS", os.getenv("HEALTH_SYMBOLS","BTCUSDT,ETHUSDT,SOLUSDT")).split(",") if s.strip()]
    ws_keepalive = int(os.getenv("WS_KEEPALIVE_SEC", "25"))
    rest_every = int(os.getenv("PRICE_SCAN_INTERVAL", "15"))
    if syms:
        try:
            _price_task = asyncio.create_task(
                auto_price_updater(syms, ws_interval_keepalive=ws_keepalive, rest_interval_sec=rest_every)
            )
            logger.info({"event": "price_updater_started", "symbols": syms, "ws_keepalive": ws_keepalive, "rest_every": rest_every})
        except Exception as e:
            logger.warning({"event": "price_updater_failed_start", "error": str(e)})

@app.on_event("shutdown")
async def shutdown_event():
    global _price_task
    try:
        stop_user_stream()
        logger.info({"event": "listen_key_keepalive_stopped"})
    except Exception as e:
        logger.warning({"event": "listen_key_keepalive_stop_error", "error": str(e)})
    if _price_task:
        try:
            _price_task.cancel()
        except Exception:
            pass
        _price_task = None

# ──────────────────────────────────────────────────────────────────────────────
# Uvicorn entry (local run)
# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        reload=_to_bool(os.getenv("UVICORN_RELOAD", "0")),
        log_level=os.getenv("UVICORN_LOG_LEVEL", "info"),
    )









































































































































































































































































































































































































































































































