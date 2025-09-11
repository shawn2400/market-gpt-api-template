# main.py
from __future__ import annotations
import os
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

# Optional runtime counters (לסטטוסי WS/Executor)
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
for d in ("static", "logs"):
    try:
        Path(d).mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.warning({"event": "mkdir_failed", "dir": d, "error": str(e)})

APP_VERSION = os.getenv("ALGOGPT_VERSION", "2.18.0")
app = FastAPI(title="AlgoGPT API", version=APP_VERSION, description="AlgoGPT - מסחר אלגוריתמי")

# ────────────────────────────────────────────────────────────────────────────────
# Middlewares
# ────────────────────────────────────────────────────────────────────────────────
app.add_middleware(ResponseSizeLimiter, max_bytes=int(os.getenv("RESPONSE_MAX_BYTES", "5242880")))
app.add_middleware(GZipMiddleware, minimum_size=1000)

UI_DOMAIN = os.getenv("UI_DOMAIN", "").strip()
CORS_ALLOWED = [UI_DOMAIN] if UI_DOMAIN else [o for o in os.getenv("CORS_ALLOW_ORIGINS", "*").split(",") if o]
CORS_ALLOW_CREDENTIALS = os.getenv("CORS_ALLOW_CREDENTIALS", "0").lower() in ("1", "true", "on")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if not CORS_ALLOWED else CORS_ALLOWED,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=CORS_ALLOW_CREDENTIALS,
)
app.add_middleware(InternalAuthMiddleware)
app.add_middleware(MetricsMiddleware)
app.mount("/metrics", make_asgi_app())

# ────────────────────────────────────────────────────────────────────────────────
# Auth gate (public paths vs. token)
# ────────────────────────────────────────────────────────────────────────────────
@app.middleware("http")
async def validate_token(request: Request, call_next):
    PUBLIC_PATHS = {
        "/", "/openapi.json", "/health", "/healthz", "/readyz",
        "/docs", "/redoc", "/telegram/webhook", "/telegram/ping"
    }
    # שים לב: /alerts מוסר – מוגן ע"י טוקן; Webhooks לגורמי חוץ מקבלים חריג מפורש
    PUBLIC_PREFIXES = [
        "/price", "/static/", "/risk", "/metrics",
        "/status/ping", "/status/ws", "/status/executor", "/status/all",
        "/provider/cryptopanic"  # ← Webhook חתום בלבד
    ]
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
    "routes.telegram_webhook",     # אם קיים
    "routes.grid",
    "routes.executor_control",
    "routes.ws_user_stream",       # אם קיים
    "routes.ai_analyze",           # ✅ /ai/analyze עם Rate-Limit
    "routes.ws_user_status",       # ✅ אופציונלי: /status/ws
    "routes.executor_status",      # ✅ אופציונלי: /status/executor
    "routes.provider_cryptopanic", # ✅ webhook חתום
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
    return {"ok": True, "status": "ok"}

@app.get("/debug/health", include_in_schema=False)
async def debug_health():
    return {"ok": True, "status": "ok", "env": os.getenv("ENV", "prod"), "version": APP_VERSION}

# Simple ping
@app.get("/status/ping")
async def status_ping():
    return {"ok": True, "ts_ms": int(asyncio.get_event_loop().time() * 1000)}

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
# Price (בדיקות)
# ────────────────────────────────────────────────────────────────────────────────
@app.get("/price/{symbol}")
async def price(symbol: str):
    try:
        p = get_price(symbol)
    except Exception:
        p = None
    return {"symbol": symbol.upper(), "price": p, "fresh": bool(p and p > 0)}

@app.get("/readyz")
async def readyz():
    try:
        ping_ok = bool(fapi_ping())
    except Exception:
        ping_ok = False
    try:
        bal = futures_balance()
        balance_ok = bool(bal and isinstance(bal, list))
    except Exception:
        balance_ok = False
    prices: Dict[str, Any] = {}
    for s in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        try:
            prices[f"price_{s}"] = get_price(s)
        except Exception:
            prices[f"price_{s}"] = None
    return {"ping_ok": ping_ok, "balance_ok": balance_ok, **prices}

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
    return {"ok": True, "src": "telegram", "ts_ms": int(asyncio.get_event_loop().time() * 1000)}

@app.post("/telegram/webhook", include_in_schema=False)
async def telegram_webhook(request: Request, x_telegram_bot_api_secret_token: str | None = Header(default=None)):
    if WEBHOOK_SECRET and (not x_telegram_bot_api_secret_token or x_telegram_bot_api_secret_token.strip() != WEBHOOK_SECRET):
        raise HTTPException(401, "Invalid telegram secret")

    # parse JSON safely
    try:
        update = await request.json()
    except Exception:
        raise HTTPException(400, "invalid JSON")

    # Handle inline callback buttons: "CONFIRM:APPROVE:<cid>" / "CONFIRM:REJECT:<cid>"
    cb = update.get("callback_query")
    if cb:
        data = str(cb.get("data", ""))  # e.g., "CONFIRM:APPROVE:<cid>"
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
        # answerCallbackQuery
        try:
            cb_id = cb.get("id")
            if BOT_TOKEN and cb_id:
                async with httpx.AsyncClient(timeout=10.0) as cli:
                    await cli.post(f"{API_BASE}/answerCallbackQuery", data={"callback_query_id": cb_id})
        except Exception:
            pass
        return {"ok": True}

    # Simple "/ping"
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









































































































































































































































































































































































































































































































































































