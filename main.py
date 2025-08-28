# main.py
from __future__ import annotations

import os
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Tuple

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse

# ──────────────────────────────────────────────────────────────────────────────
# Env / Local .env
# ──────────────────────────────────────────────────────────────────────────────
IS_CLOUD = bool(
    os.getenv("RENDER")
    or os.getenv("RENDER_SERVICE_ID")
    or os.getenv("DYNO")
    or os.getenv("K_SERVICE")
)
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

def _parse_csv(s: str) -> List[str]:
    return [x.strip() for x in (s or "").split(",") if x.strip()]

APP_VERSION = os.getenv("ALGOGPT_VERSION", "2.15.8")

# ──────────────────────────────────────────────────────────────────────────────
# Config & Logging
# ──────────────────────────────────────────────────────────────────────────────
from utils import config as cfg
from utils.config import dump_config_sanitized, LOG_LEVEL
from utils.response_limits import ResponseSizeLimiter
from utils.json_logger import setup_json_logging
from utils.rate_limit import RateLimitMiddleware

logger = setup_json_logging()
logging.getLogger().setLevel(LOG_LEVEL)

# ──────────────────────────────────────────────────────────────────────────────
# FastAPI app
# ──────────────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="AlgoGPT API",
    version=APP_VERSION,
    description="AlgoGPT — מסחר אלגוריתמי בזמן אמת",
)

# Response size cap (ברירת מחדל ~5MB)
app.add_middleware(ResponseSizeLimiter, max_bytes=int(os.getenv("RESPONSE_MAX_BYTES", "5242880")))

# GZip for large responses
app.add_middleware(GZipMiddleware, minimum_size=1000)

# CORS (נשלט ENV)
CORS_ALLOWED = os.getenv("CORS_ALLOW_ORIGINS", "*").strip()
CORS_ALLOW_CREDENTIALS = _to_bool(os.getenv("CORS_ALLOW_CREDENTIALS", "0"))
if CORS_ALLOWED == "*" and CORS_ALLOW_CREDENTIALS:
    # לפי התקן, אי אפשר "*" עם credentials; ננטרל credentials כדי למנוע בעיות בדפדפנים
    CORS_ALLOW_CREDENTIALS = False
allow_origins = ["*"] if CORS_ALLOWED == "*" else _parse_csv(CORS_ALLOWED)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=CORS_ALLOW_CREDENTIALS,
)

# Global rate limit (קליל, נשלט ENV)
RATE_LIMIT_GLOBAL = int(os.getenv("RATE_LIMIT_GLOBAL", "60"))   # בקשות לדקה
RATE_LIMIT_WINDOW = int(os.getenv("RATE_LIMIT_WINDOW", "60"))   # חלון בשניות
app.add_middleware(
    RateLimitMiddleware,
    limit=RATE_LIMIT_GLOBAL,
    window=RATE_LIMIT_WINDOW,
    endpoint_limits={},  # ניתן להזריק מפה פר-Route אם תרצה
)

# Static
Path("static").mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

# ──────────────────────────────────────────────────────────────────────────────
# Routers – טעינה בטוחה (מודול שבור לא מפיל את האפליקציה)
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
    ("routes.executor", "router"),           # מייצא router ברמת מודול
]

# נטען AI רק אם מאופשר ב-ENV (כדי למנוע 404 או תלות במודולים חיצוניים כשלא צריך)
if _to_bool(os.getenv("ENABLE_AI_ROUTES", "1"), True):
    CORE_ROUTERS.append(("routes.ai", "router"))

EXTRA_ROUTERS: List[Tuple[str, str]] = [
    ("routes.market_extra", "router"),
    ("routes.executor_extra", "router"),
    ("routes.anchor_extra", "router"),
    ("routes.ws_stream", "router"),
    ("routes.grid", "router"),
    ("routes.debug", "router"),
]

for mod, attr in CORE_ROUTERS:
    _include_router(mod, attr)
for mod, attr in EXTRA_ROUTERS:
    _include_router(mod, attr)

# ──────────────────────────────────────────────────────────────────────────────
# Health & Root
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

# ──────────────────────────────────────────────────────────────────────────────
# Exception handler (JSON + לוג)
# ──────────────────────────────────────────────────────────────────────────────
@app.exception_handler(Exception)
async def handle_exception(request: Request, exc: Exception):
    logger.error({
        "event": "exception",
        "error": str(exc),
        "type": exc.__class__.__name__,
        "args": getattr(exc, "args", []),
        "path": request.url.path,
        "time": datetime.now(timezone.utc).isoformat(),
    })
    return JSONResponse({"detail": str(exc)}, status_code=500)

# ──────────────────────────────────────────────────────────────────────────────
# Startup log
# ──────────────────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup_event():
    logger.info({
        "event": "startup",
        "APP_VERSION": APP_VERSION,
        "BINANCE_KEY_LEN": len(cfg.BINANCE_API_KEY or ""),
        "OPENAI_KEY_LEN": len(cfg.OPENAI_API_KEY or ""),
        "config": dump_config_sanitized(),
    })

# ──────────────────────────────────────────────────────────────────────────────
# Uvicorn entry (local dev)
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




























































































































































































































































































































































































































































































