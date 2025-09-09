# main.py
from __future__ import annotations
import os, asyncio, logging, json
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.gzip import GZipMiddleware
from prometheus_client import make_asgi_app
import httpx

from utils.json_logger import setup_json_logging
from utils.response_limits import ResponseSizeLimiter
from utils.auth import extract_token, allow_all, token_matches
from utils.binance_client import fapi_ping, futures_balance, get_price
from utils.metrics_middleware import MetricsMiddleware
from app.middlewares import InternalAuthMiddleware
from utils.trade_executor import ConfirmStore  # לא צריך קובץ חדש

def _coerce_log_level(val):
    import logging as _l
    if isinstance(val, int) or (isinstance(val, str) and str(val).isdigit()):
        return int(val)
    m = {
        "debug": _l.DEBUG, "info": _l.INFO, "warning": _l.WARNING,
        "warn": _l.WARNING, "error": _l.ERROR, "critical": _l.CRITICAL,
    }
    return m.get(str(val).strip().lower(), _l.INFO)

logger = setup_json_logging()
logging.getLogger().setLevel(_coerce_log_level(os.getenv("LOG_LEVEL", "INFO")))

for d in ("static", "logs"):
    try:
        Path(d).mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.warning({"event": "mkdir_failed", "dir": d, "error": str(e)})

APP_VERSION = os.getenv("ALGOGPT_VERSION", "2.18.0")
app = FastAPI(title="AlgoGPT API", version=APP_VERSION, description="AlgoGPT - מסחר אלגוריתמי")

# ── Middlewares
app.add_middleware(ResponseSizeLimiter, max_bytes=int(os.getenv("RESPONSE_MAX_BYTES", "5242880")))
app.add_middleware(GZipMiddleware, minimum_size=1000)
UI_DOMAIN = os.getenv("UI_DOMAIN", "").strip()
CORS_ALLOWED = [UI_DOMAIN] if UI_DOMAIN else os.getenv("CORS_ALLOW_ORIGINS", "*").split(",")
CORS_ALLOW_CREDENTIALS = os.getenv("CORS_ALLOW_CREDENTIALS", "0") in ("1","true","on")
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

# ── Public/Auth middleware
@app.middleware("http")
async def validate_token(request: Request, call_next):
    PUBLIC_PATHS = {"/", "/openapi.json", "/health", "/healthz", "/readyz", "/docs", "/redoc", "/telegram/webhook"}
    PUBLIC_PREFIXES = ["/price", "/static/", "/alerts", "/risk", "/metrics"]
    path = request.url.path
    if request.method.upper() == "OPTIONS" or path in PUBLIC_PATHS or any(path.startswith(p) for p in PUBLIC_PREFIXES):
        return await call_next(request)
    if allow_all():
        return await call_next(request)
    token = extract_token(request, request.headers.get("Authorization", ""), request.headers.get("X-API-Key"))
    if not token_matches(token):
        return JSONResponse(status_code=401, content={"detail": "Invalid API key"})
    return await call_next(request)

# ── Routers
for module_path in ("routes.trade", "routes.analysis", "routes.decision"):
    try:
        mod = __import__(module_path, fromlist=["router"])
        if hasattr(mod, "router"):
            app.include_router(mod.router)
            logger.info({"event": "router_registered", "router": module_path})
    except Exception as e:
        logger.warning({"event": "router_register_failed", "router": module_path, "error": str(e)})

# ── Meta & Health
@app.get("/")
async def root():
    return {"ok": True, "status": "ok", "service": "app_full", "title": "AlgoGPT API", "version": APP_VERSION}

@app.get("/health")
async def health():
    return {"ok": True, "status": "ok"}

# ── Price (לבדיקות)
@app.get("/price/{symbol}")
async def price(symbol: str):
    p = get_price(symbol)
    return {"symbol": symbol.upper(), "price": p, "fresh": bool(p and p > 0)}

# ── Readyz (לכיסוי הסקריפטים שלך)
@app.get("/readyz")
async def readyz():
    try:
        ping_ok = fapi_ping()
    except Exception:
        ping_ok = False
    try:
        bal = futures_balance()
        balance_ok = bool(bal and isinstance(bal, list))
    except Exception:
        balance_ok = False
    prices = {}
    for s in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        try:
            prices[f"price_{s}"] = get_price(s)
        except Exception:
            prices[f"price_{s}"] = None
    return {"ping_ok": ping_ok, "balance_ok": balance_ok, **prices}

# ── Telegram webhook (Approve/Reject) — ללא קבצים חדשים
WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
BOT_TOKEN      = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
API_BASE       = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else ""

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

@app.post("/telegram/webhook")
async def telegram_webhook(request: Request, x_telegram_bot_api_secret_token: str | None = Header(default=None)):
    if WEBHOOK_SECRET and (not x_telegram_bot_api_secret_token or x_telegram_bot_api_secret_token.strip() != WEBHOOK_SECRET):
        raise HTTPException(401, "Invalid telegram secret")
    update = await request.json()

    # Callback (inline keyboard)
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
        return {"ok": True}

    # פקודת ping
    msg = update.get("message")
    if msg and str(msg.get("text", "")).strip() == "/ping":
        chat_id = int(msg.get("chat", {}).get("id", 0))
        await _tg_send(chat_id, "pong ✅")
        return {"ok": True}

    return {"ok": True}

# ── Auto setWebhook (אופציונלי)
@app.on_event("startup")
async def _startup():
    if not BOT_TOKEN:
        return
    if os.getenv("TELEGRAM_AUTO_WEBHOOK", "1") not in ("1", "true", "yes", "on"):
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "10000")))




















































































































































































































































































































































































































































































































































