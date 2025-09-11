# main.py
from __future__ import annotations
import os
import time
import asyncio
import logging
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from prometheus_client import make_asgi_app
import httpx

from utils.json_logger import setup_json_logging
from utils.response_limits import ResponseSizeLimiter
from utils.auth import extract_token, allow_all, token_matches
from utils.binance_client import fapi_ping, futures_balance, get_price, futures_exchange_info_safe
from utils.metrics_middleware import MetricsMiddleware

# InternalAuthMiddleware (safe import with fallback)
try:
    from app.middlewares import InternalAuthMiddleware  # type: ignore
except Exception:
    class InternalAuthMiddleware(BaseHTTPMiddleware):  # no-op fallback
        async def dispatch(self, request: Request, call_next):
            return await call_next(request)

from utils.trade_executor import ConfirmStore

# Optional runtime counters (WS/Executor status)
try:
    from utils.runtime_counters import ws_user_status, exec_get_counters
except Exception:
    def ws_user_status() -> Dict[str, Any]:
        return {"running": False, "reconnects": None, "ttl_sec": None, "inter_event_ewma_ms": None}
    def exec_get_counters() -> Dict[str, Any]:
        return {"tick_ewma_ms": None, "tick_p95_ms": None, "tick_p99_ms": None,
                "last_tick_age_sec": None, "timeouts_burst": 0, "no_trade_streak": 0,
                "current_interval": int(os.getenv("SCAN_INTERVAL","60"))}

# ────────────────────────────────────────────────────────────────────────────────
# Logging
# ────────────────────────────────────────────────────────────────────────────────
def _coerce_log_level(val):
    import logging as _l
    if isinstance(val, int) or (isinstance(val, str) and str(val).isdigit()):
        return int(val)
    m = {
        "debug": _l.DEBUG,
        "info": _l.INFO,
        "warning": _l.WARNING, "warn": _l.WARNING,
        "error": _l.ERROR, "critical": _l.CRITICAL
    }
    return m.get(str(val).strip().lower(), _l.INFO)

logger = setup_json_logging()
logging.getLogger().setLevel(_coerce_log_level(os.getenv("LOG_LEVEL", "INFO")))

# ────────────────────────────────────────────────────────────────────────────────
# FS bootstrap
# ────────────────────────────────────────────────────────────────────────────────
# מוסיף גם data כדי להבטיח שה-SQLite יעבוד עם DATABASE_URL=sqlite:////app/data/algogpt.db
for d in ("static", "logs", "data"):
    try:
        Path(d).mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.warning({"event": "mkdir_failed", "dir": d, "error": str(e)})

APP_VERSION = os.getenv("ALGOGPT_VERSION", "2.18.0")
app = FastAPI(title="AlgoGPT API", version=APP_VERSION, description="AlgoGPT - מסחר אלגוריתמי")

# ────────────────────────────────────────────────────────────────────────────────
# OpenAPI dynamic filter (hide x-internal, patterns, cap operations)
# ────────────────────────────────────────────────────────────────────────────────
from fastapi.openapi.utils import get_openapi
from fnmatch import fnmatch

def custom_openapi():
    if getattr(app, "openapi_schema", None):
        return app.openapi_schema

    schema = get_openapi(
        title=app.title, version=APP_VERSION,
        description=app.description, routes=app.routes
    )

    max_ops = int(os.getenv("OPENAPI_PUBLIC_MAX_OPS", "30"))  # 0 = unlimited
    hide_patterns = [p.strip() for p in os.getenv("OPENAPI_HIDE_PATTERNS", "").split(",") if p.strip()]
    include_tags = {t.strip() for t in os.getenv("OPENAPI_INCLUDE_TAGS", "").split(",") if t.strip()}

    new_paths: Dict[str, Any] = {}
    count = 0

    for path in sorted(schema.get("paths", {}).keys()):
        methods = schema["paths"][path]
        new_methods = {}

        path_hidden = any(fnmatch(path, pat) for pat in hide_patterns)

        for method in list(methods.keys()):
            if method.startswith("x-"):
                continue
            op = methods[method]

            # hide if explicitly internal
            if op.get("x-internal") is True:
                continue

            # include only specific tags if configured
            if include_tags and not include_tags.intersection(set(op.get("tags") or [])):
                continue

            # hide by path glob
            if path_hidden:
                continue

            # enforce public ops cap
            if max_ops > 0 and count >= max_ops:
                continue

            new_methods[method] = op
            count += 1

        if new_methods:
            new_paths[path] = new_methods

    schema["paths"] = new_paths
    app.openapi_schema = schema
    return app.openapi_schema

app.openapi = custom_openapi

# ────────────────────────────────────────────────────────────────────────────────
# Middlewares
# ────────────────────────────────────────────────────────────────────────────────
app.add_middleware(ResponseSizeLimiter, max_bytes=int(os.getenv("RESPONSE_MAX_BYTES", "5242880")))
app.add_middleware(GZipMiddleware, minimum_size=1000)

UI_DOMAIN = os.getenv("UI_DOMAIN", "").strip()
CORS_ALLOWED = [UI_DOMAIN] if UI_DOMAIN else [o for o in os.getenv("CORS_ALLOW_ORIGINS", "*").split(",") if o]
CORS_ALLOW_CREDENTIALS_CFG = os.getenv("CORS_ALLOW_CREDENTIALS", "0").lower() in ("1", "true", "on")
# דפדפנים לא מאפשרים credentials עם wildcard:
CORS_ALLOW_CREDENTIALS_EFFECTIVE = CORS_ALLOW_CREDENTIALS_CFG and CORS_ALLOWED != ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if not CORS_ALLOWED else CORS_ALLOWED,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=CORS_ALLOW_CREDENTIALS_EFFECTIVE,
)
app.add_middleware(InternalAuthMiddleware)
app.add_middleware(MetricsMiddleware)
app.mount("/metrics", make_asgi_app())

# ────────────────────────────────────────────────────────────────────────────────
# Auth gate (public paths vs. token)
# ────────────────────────────────────────────────────────────────────────────────
METRICS_PUBLIC = os.getenv("METRICS_PUBLIC", "1").lower() in ("1", "true", "yes", "on")

@app.middleware("http")
async def validate_token(request: Request, call_next):
    PUBLIC_PATHS = {
        "/", "/openapi.json", "/health", "/healthz", "/readyz",
        "/docs", "/redoc",
        "/telegram/webhook", "/telegram/ping",
        # public provider webhook (HMAC-validated in its router)
        "/provider/cryptopanic/webhook",
    }
    PUBLIC_PREFIXES = [
        "/price", "/static/", "/risk",
        "/status/ping", "/status/ws", "/status/executor", "/status/all",
    ]
    if METRICS_PUBLIC:
        PUBLIC_PREFIXES.append("/metrics")

    path = request.url.path
    if request.method.upper() == "OPTIONS" or path in PUBLIC_PATHS or any(path.startswith(p) for p in PUBLIC_PREFIXES):
        return await call_next(request)
    if allow_all():
        return await call_next(request)

    token = extract_token(request, request.headers.get("Authorization", ""), request.headers.get("X-API-Key"))
    if not token_matches(token):
        return JSONResponse(status_code=401, content={"detail": "Invalid API key"})
    return await call_next(request)

# ────────────────────────────────────────────────────────────────────────────────
# Include routers (dynamic safe import)
# ────────────────────────────────────────────────────────────────────────────────
def _try_include(module_path: str) -> bool:
    try:
        mod = __import__(module_path, fromlist=["router"])
        if hasattr(mod, "router"):
            app.include_router(mod.router)
            logger.info({"event": "router_registered", "router": module_path})
            return True
        logger.warning({"event": "router_missing_router_attr", "router": module_path})
    except Exception as e:
        logger.warning({"event": "router_register_failed", "router": module_path, "error": str(e)})
    return False

_registered_paths = set()

for module_path in (
    "routes.trade",
    "routes.analytics",
    "routes.decision",
    "routes.backtest",
    "routes.executor",
    "routes.binance_status",
    "routes.telegram_webhook",     # optional
    "routes.grid",
    "routes.executor_control",
    "routes.ws_user_stream",       # optional
    "routes.ai_analyze",           # /ai/analyze with rate limit
    "routes.ws_user_status",       # fallback /status/ws
    "routes.executor_status",      # fallback /status/executor
    "routes.provider_cryptopanic", # HMAC-signed webhook
):
    if _try_include(module_path):
        try:
            for r in app.router.routes:
                try:
                    _registered_paths.add(getattr(r, "path", None))
                except Exception:
                    pass
        except Exception:
            pass

def _route_exists(path: str) -> bool:
    try:
        for r in app.router.routes:
            if getattr(r, "path", None) == path:
                return True
    except Exception:
        pass
    return False

# ────────────────────────────────────────────────────────────────────────────────
# Meta & Health
# ────────────────────────────────────────────────────────────────────────────────
@app.get("/")
async def root():
    return {"ok": True, "status": "ok", "service": "app_full", "title": "AlgoGPT API", "version": APP_VERSION}

@app.get("/health")
async def health():
    return {"ok": True, "status": "ok", "version": APP_VERSION}

@app.get("/debug/health", include_in_schema=False)
async def debug_health():
    return {"ok": True, "status": "ok", "env": os.getenv("ENV", "prod"), "version": APP_VERSION}

@app.get("/status/ping")
async def status_ping():
    # שימוש ב-epoch ms לשמירה על עקביות עם שאר ה־API
    return {"ok": True, "ts_ms": int(time.time() * 1000)}

# ────────────────────────────────────────────────────────────────────────────────
# Built-in status endpoints (fallback)
# ────────────────────────────────────────────────────────────────────────────────
if not _route_exists("/status/ws"):
    @app.get("/status/ws")
    async def status_ws():
        st = ws_user_status()
        return {"ok": True, **st}

if not _route_exists("/status/executor"):
    @app.get("/status/executor")
    async def status_executor():
        st = exec_get_counters()
        return {"ok": True, **st}

if not _route_exists("/status/all"):
    @app.get("/status/all")
    async def status_all():
        try:
            ping_ok = bool(fapi_ping())
        except Exception:
            ping_ok = False
        ws = ws_user_status()
        ex = exec_get_counters()
        return {
            "ok": True, "version": APP_VERSION,
            "ws": ws, "executor": ex, "binance_ping_ok": ping_ok,
        }

# ────────────────────────────────────────────────────────────────────────────────
# Price (aligned with OpenAPI schema)
# ────────────────────────────────────────────────────────────────────────────────
@app.get("/price/{symbol}")
async def price(symbol: str):
    src = "binance_fapi"
    ts = int(time.time() * 1000)  # OpenAPI field name: ts
    err = ""
    try:
        p = get_price(symbol)
        ok = bool(p and p > 0)
        if not ok:
            err = "no price"
    except Exception as e:
        p = None
        ok = False
        err = str(e)
    return {
        "ok": ok,
        "symbol": symbol.upper(),
        "price": float(p) if p is not None else None,
        "source": src,
        "ts": ts,
        "error": err,
    }

@app.get("/readyz")
async def readyz():
    details: Dict[str, Any] = {}
    err: str | None = None
    try:
        details["binance_ping_ok"] = bool(fapi_ping())
        if not details["binance_ping_ok"]:
            err = "binance ping failed"
    except Exception as e:
        details["binance_ping_ok"] = False
        err = f"binance ping error: {e}"

    try:
        bal = futures_balance()
        details["balance_ok"] = bool(bal and isinstance(bal, list))
        if not details["balance_ok"]:
            err = (err or "") + "; balance not ok"
    except Exception as e:
        details["balance_ok"] = False
        err = (err or "") + f"; balance error: {e}"

    for s in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        try:
            details[f"price_{s}"] = get_price(s)
        except Exception:
            details[f"price_{s}"] = None

    return {"ok": (err is None), "error": err, "details": details}

# ────────────────────────────────────────────────────────────────────────────────
# Telegram webhook & ping (public)
# ────────────────────────────────────────────────────────────────────────────────
WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
BOT_TOKEN      = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
API_BASE       = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else ""
TELEGRAM_AUTO_WEBHOOK = os.getenv("TELEGRAM_AUTO_WEBHOOK", "1").lower() in ("1", "true", "yes", "on")

async def _tg_send(chat_id: int, text: str):
    if not BOT_TOKEN:
        return
    try:
        async with httpx.AsyncClient(timeout=10.0) as cli:
            await cli.post(f"{API_BASE}/sendMessage", data={
                "chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True
            })
    except Exception as e:
        logging.getLogger("algogpt.telegram").warning("telegram send failed: %s", e)

@app.get("/telegram/ping", include_in_schema=False)
async def tg_ping():
    return {"ok": True, "src": "telegram", "ts_ms": int(time.time() * 1000)}

@app.post("/telegram/webhook", include_in_schema=False)
async def telegram_webhook(request: Request, x_telegram_bot_api_secret_token: str | None = Header(default=None)):
    if WEBHOOK_SECRET and (not x_telegram_bot_api_secret_token or x_telegram_bot_api_secret_token.strip() != WEBHOOK_SECRET):
        raise HTTPException(401, "Invalid telegram secret")

    try:
        update = await request.json()
    except Exception:
        raise HTTPException(400, "invalid JSON")

    cb = update.get("callback_query")
    if cb:
        data = str(cb.get("data", ""))
        chat = (cb.get("message", {}).get("chat", {}) or cb.get("from", {}))
        chat_id = int(chat.get("id", 0))
        parts = data.split(":", 2)
        if len(parts) == 3 and parts[0] == "CONFIRM":
            action, cid = parts[1], parts[2]
            approver = str(cb.get("from", {}).get("username") or chat_id)
            if action == "APPROVE":
                ConfirmStore.approve(cid, approver=approver)
                await _tg_send(chat_id, "✅ אושר. מפעיל את הטרייד.")
            else:
                ConfirmStore.reject(cid, approver=approver)
                await _tg_send(chat_id, "❌ בוטל. הטרייד לא יצא לפועל.")
        try:
            cb_id = cb.get("id")
            if BOT_TOKEN and cb_id:
                async with httpx.AsyncClient(timeout=10.0) as cli:
                    await cli.post(f"{API_BASE}/answerCallbackQuery", data={"callback_query_id": cb_id})
        except Exception:
            pass
        return {"ok": True}

    msg = update.get("message")
    if msg and str(msg.get("text", "")).strip() == "/ping":
        chat_id = int(msg.get("chat", {}).get("id", 0))
        await _tg_send(chat_id, "pong ✅")
        return {"ok": True}

    return {"ok": True}

# ────────────────────────────────────────────────────────────────────────────────
# Kill-Switch /flush
# ────────────────────────────────────────────────────────────────────────────────
@app.post("/flush")
async def flush_kill_switch():
    done = False
    for name in ("flush_all", "flush", "reset"):
        try:
            fn = getattr(ConfirmStore, name, None)
            if callable(fn):
                fn()
                done = True
                break
        except Exception as e:
            logger.warning({"event": "flush_failed", "err": str(e)})
    return {"ok": True, "flushed": done}

# ────────────────────────────────────────────────────────────────────────────────
# Preflight Warmup on startup
# ────────────────────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def _startup_preflight_warmup():
    try:
        _ = futures_exchange_info_safe(force_refresh=True)
    except Exception as e:
        logger.warning({"event": "warmup.exinfo_failed", "error": str(e)})
    try:
        _ = get_price("BTCUSDT")
        try:
            from utils.get_klines import get_klines_sync
            _ = get_klines_sync("BTCUSDT", interval=os.getenv("DEFAULT_INTERVAL", "15m"), limit=50)
        except Exception:
            pass
    except Exception as e:
        logger.warning({"event": "warmup.price_failed", "error": str(e)})

# ────────────────────────────────────────────────────────────────────────────────
# Auto setWebhook (optional)
# ────────────────────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def _startup_webhook():
    if not BOT_TOKEN or not TELEGRAM_AUTO_WEBHOOK:
        return
    public_host = os.getenv("PUBLIC_HOST", "").strip()
    if not public_host:
        return
    try:
        async with httpx.AsyncClient(timeout=10.0) as cli:
            await cli.post(f"{API_BASE}/setWebhook", data={
                "url": f"{public_host}/telegram/webhook",
                "secret_token": WEBHOOK_SECRET,
                "drop_pending_updates": "true",
                "max_connections": "40",
            })
    except Exception as e:
        logging.getLogger("algogpt.telegram").warning("setWebhook failed: %s", e)

# ────────────────────────────────────────────────────────────────────────────────
# WS User-Data Stream autostart
# ────────────────────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def _startup_user_stream():
    try:
        if os.getenv("USER_STREAM_ENABLE", "1").lower() in ("1", "true", "yes", "on"):
            from utils import ws_user_stream
            ws_user_stream.start()
            logger.info({"event": "ws_user_stream_autostart"})
    except Exception as e:
        logger.warning({"event": "ws_user_stream_autostart_failed", "error": str(e)})

# ────────────────────────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=os.getenv("BIND_HOST", "0.0.0.0"), port=int(os.getenv("PORT", "10000")))


















































































































































































































































































































































































































































































































































































