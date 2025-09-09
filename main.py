# ==========================
# main.py
# ==========================
from __future__ import annotations
import os, asyncio, logging
from pathlib import Path
from fastapi import FastAPI, Request
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

from utils.config import LOG_LEVEL
from utils.response_limits import ResponseSizeLimiter
from utils.json_logger import setup_json_logging
from utils.auth import extract_token, allow_all, token_matches
from utils.binance_client import fapi_ping, futures_balance, get_price
from app.middlewares import InternalAuthMiddleware
from utils.metrics_middleware import MetricsMiddleware

logger = setup_json_logging()
logging.getLogger().setLevel(LOG_LEVEL)
for d in ("static", "logs"):
    try: Path(d).mkdir(parents=True, exist_ok=True)
    except Exception as e: logger.warning({"event": "mkdir_failed", "dir": d, "error": str(e)})

APP_VERSION = os.getenv("ALGOGPT_VERSION", "2.17.1")
app = FastAPI(title="AlgoGPT API", version=APP_VERSION, description="AlgoGPT - מסחר אלגוריתמי")

# ── Middlewares
app.add_middleware(ResponseSizeLimiter, max_bytes=int(os.getenv("RESPONSE_MAX_BYTES", "5242880")))
app.add_middleware(GZipMiddleware, minimum_size=1000)
UI_DOMAIN = os.getenv("UI_DOMAIN", "").strip()
CORS_ALLOWED = [UI_DOMAIN] if UI_DOMAIN else os.getenv("CORS_ALLOW_ORIGINS", "*").split(",")
CORS_ALLOW_CREDENTIALS = os.getenv("CORS_ALLOW_CREDENTIALS", "0") in ("1", "true")
app.add_middleware(CORSMiddleware, allow_origins=["*"] if not CORS_ALLOWED else CORS_ALLOWED,
                   allow_methods=["*"], allow_headers=["*"], allow_credentials=CORS_ALLOW_CREDENTIALS)
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
for module_path in ("routes.trade", "routes.executor", "routes.health"):
    try:
        mod = __import__(module_path, fromlist=["router"])
        if hasattr(mod, "router"):
            app.include_router(mod.router)
    except Exception as e:
        logger.warning({"event": "router_register_failed", "router": module_path, "error": str(e)})

# ── Meta & Health
@app.get("/")
async def root():
    return {"ok": True, "status": "ok", "service": "app_full", "title": "AlgoGPT API", "version": APP_VERSION}

@app.get("/health")
async def health():
    return {"ok": True, "status": "ok"}

# ── Price endpoint (לבדיקות ה-E2E שלך)
@app.get("/price/{symbol}")
async def price(symbol: str):
    p = await _get_price_async(symbol)

    return {"symbol": symbol.upper(), "price": p, "fresh": bool(p and p > 0)}

async def _get_price_async(symbol: str):
    # עטיפה אסינכרונית אם תרצה להחליף ל-WS בעתיד
    return get_price(symbol)

# ── Readyz (מיישר קו עם הסקריפטים שלך)
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
    # מחירים ע״י אותו מנגנון של /price
    prices = {}
    for s in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        try:
            prices[f"price_{s}"] = get_price(s)
        except Exception:
            prices[f"price_{s}"] = None
    return {"ping_ok": ping_ok, "balance_ok": balance_ok, **prices}

# ── Warmup קטן למניעת readyz קר
@app.on_event("startup")
async def _warm_prices():
    for s in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        try:
            await asyncio.wait_for(_get_price_async(s), timeout=3.0)
        except Exception:
            pass

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "10000")))


















































































































































































































































































































































































































































































































































