# main.py
from __future__ import annotations
import os, time, asyncio, logging, pkgutil, httpx
from pathlib import Path
from typing import Any, Dict, Optional, Iterable, List
from fnmatch import fnmatch

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.openapi.utils import get_openapi
from fastapi.exceptions import RequestValidationError
from prometheus_client import make_asgi_app
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.status import HTTP_422_UNPROCESSABLE_ENTITY

from utils.auth import extract_token, allow_all, token_matches
from utils.json_logger import setup_json_logging
from utils.metrics_middleware import MetricsMiddleware
from utils.response_limits import ResponseSizeLimiter

# ---- Binance client (fallbacks) ----
try:
    from utils.binance_client import fapi_ping, futures_balance, get_price, futures_exchange_info_safe
except Exception:
    def fapi_ping() -> bool: return False
    def futures_balance(): return None
    def get_price(symbol: str) -> Optional[float]: return None
    def futures_exchange_info_safe(force_refresh: bool = False): return None

# ---- Telegram notifier (fallbacks) ----
try:
    from utils.telegram_notifier_core import ensure_ops_schedulers_started, send_ops_digest_now, send_eod_report_now
except Exception:
    async def ensure_ops_schedulers_started() -> None: return None
    async def send_ops_digest_now(hours: Optional[int] = None) -> None: return None
    async def send_eod_report_now() -> None: return None

# ---- InternalAuthMiddleware (fallback) ----
try:
    from app.middlewares import InternalAuthMiddleware
except Exception:
    class InternalAuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next): return await call_next(request)

# ---- ConfirmStore (fallback) ----
try:
    from utils.trade_executor import ConfirmStore
except Exception:
    try:
        from utils.auto_executor import ConfirmStore  # type: ignore
    except Exception:
        class ConfirmStore:  # type: ignore
            _P: Dict[str, Dict[str, Any]] = {}
            @classmethod
            def pending(cls) -> List[Dict[str, Any]]: return list(cls._P.values())
            @classmethod
            def create(cls, payload: Dict[str, Any]) -> str:
                tid = payload.get("ticket_id") or f"TKT-{int(time.time()*1000)}"
                payload["ticket_id"] = tid; cls._P[tid] = payload; return tid
            @classmethod
            def decide(cls, ticket_id: str, approved: bool) -> Dict[str, Any]:
                it = cls._P.pop(ticket_id, None)
                if not it: return {"ok": False, "error": "not_found"}
                it["approved"] = approved; it["decided_ts"] = int(time.time())
                return {"ok": True, "approved": approved, "ticket_id": ticket_id}
            @classmethod
            def flush_all(cls) -> None: cls._P.clear()
            flush = reset = flush_all

# ---- runtime counters (fallbacks) ----
try:
    from utils.runtime_counters import ws_user_status, exec_get_counters
except Exception:
    def ws_user_status() -> Dict[str, Any]:
        return {"running": False, "reconnects": None, "ttl_sec": None, "inter_event_ewma_ms": None}
    def exec_get_counters() -> Dict[str, Any]:
        return {"tick_ewma_ms": None,"tick_p95_ms": None,"tick_p99_ms": None,"last_tick_age_sec": None,
                "timeouts_burst": 0,"no_trade_streak": 0,"current_interval": int(os.getenv("SCAN_INTERVAL","60"))}

# ---- Trade Manager (optional) ----
TRADE_MANAGER_ENABLE = os.getenv("TRADE_MANAGER_ENABLE","1").lower() in ("1","true","yes","on")
TRADE_MANAGER_INTERVAL_SEC = int(os.getenv("TRADE_MANAGER_INTERVAL_SEC","20"))
try:
    from utils.trade_manager import manage_open_trades_loop  # type: ignore
except Exception:
    manage_open_trades_loop = None  # type: ignore

def _coerce_log_level(val):
    import logging as _l
    if isinstance(val,int) or (isinstance(val,str) and str(val).isdigit()): return int(val)
    m = {"debug":_l.DEBUG,"info":_l.INFO,"warning":_l.WARNING,"warn":_l.WARNING,"error":_l.ERROR,"critical":_l.CRITICAL}
    return m.get(str(val).strip().lower(), _l.INFO)

logger = setup_json_logging()
logging.getLogger().setLevel(_coerce_log_level(os.getenv("LOG_LEVEL","INFO")))

# base dirs
for d in ("static","logs","data"):
    try: Path(d).mkdir(parents=True, exist_ok=True)
    except Exception as e: logger.warning({"event":"mkdir_failed","dir":d,"error":str(e)})

APP_VERSION = os.getenv("ALGOGPT_VERSION","2.18.0")
app = FastAPI(title="AlgoGPT API", version=APP_VERSION, description="AlgoGPT - Algorithmic Trading")

# ---------- 422 handler ----------
from fastapi.exceptions import RequestValidationError
@app.exception_handler(RequestValidationError)
async def _validation_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=HTTP_422_UNPROCESSABLE_ENTITY, content={"detail": exc.errors()})

# ---------- OpenAPI filtering ----------
def custom_openapi():
    if getattr(app, "openapi_schema", None): return app.openapi_schema
    schema = get_openapi(title=app.title, version=APP_VERSION, description=app.description, routes=app.routes)
    max_ops = int(os.getenv("OPENAPI_PUBLIC_MAX_OPS","30"))
    hide_patterns = [p.strip() for p in os.getenv("OPENAPI_HIDE_PATTERNS","").split(",") if p.strip()]
    include_tags = {t.strip() for t in os.getenv("OPENAPI_INCLUDE_TAGS","").split(",") if t.strip()}
    new_paths: Dict[str, Any] = {}; count = 0
    for path in sorted(schema.get("paths", {}).keys()):
        methods = schema["paths"][path]; new_methods = {}; path_hidden = any(fnmatch(path, pat) for pat in hide_patterns)
        for method, op in list(methods.items()):
            if method.startswith("x-"): continue
            if op.get("x-internal") is True: continue
            if include_tags and not include_tags.intersection(set(op.get("tags") or [])): continue
            if path_hidden: continue
            if max_ops > 0 and count >= max_ops: continue
            new_methods[method] = op; count += 1
        if new_methods: new_paths[path] = new_methods
    schema["paths"] = new_paths; app.openapi_schema = schema; return app.openapi_schema
app.openapi = custom_openapi

# ---------- Middlewares ----------
app.add_middleware(ResponseSizeLimiter, max_bytes=int(os.getenv("RESPONSE_MAX_BYTES","5242880")))
app.add_middleware(GZipMiddleware, minimum_size=1000)

UI_DOMAIN = os.getenv("UI_DOMAIN","").strip()
_cao = os.getenv("CORS_ALLOW_ORIGINS", os.getenv("CORS_ALLOW_ORIGINS","*"))
CORS_ALLOWED = [UI_DOMAIN] if UI_DOMAIN else [o for o in _cao.split(",") if o]
CORS_ALLOW_CREDENTIALS_CFG = os.getenv("CORS_ALLOW_CREDENTIALS","0").lower() in ("1","true","on")
CORS_ALLOW_CREDENTIALS_EFFECTIVE = CORS_ALLOW_CREDENTIALS_CFG and CORS_ALLOWED != ["*"]

app.add_middleware(CORSMiddleware,
    allow_origins=["*"] if not CORS_ALLOWED else CORS_ALLOWED,
    allow_methods=["*"], allow_headers=["*"], allow_credentials=CORS_ALLOW_CREDENTIALS_EFFECTIVE)

app.add_middleware(InternalAuthMiddleware)
app.add_middleware(MetricsMiddleware)
app.mount("/metrics", make_asgi_app())

# ---------- Public paths ----------
METRICS_PUBLIC = os.getenv("METRICS_PUBLIC","1").lower() in ("1","true","yes","on")
PUBLIC_STATUS  = os.getenv("SECURITY_PUBLIC_STATUS","1").lower() in ("1","true","yes","on")
def _split_multi(s: str) -> Iterable[str]:
    import re; return [x for x in re.split(r"[,\n\r\t ]+", (s or "").strip()) if x]

DEFAULT_PUBLIC_PATHS = {
    "/", "/openapi.json", "/health", "/healthz", "/readyz", "/docs", "/redoc",
    "/telegram/webhook", "/telegram/callback", "/telegram/ping",
    "/provider/cryptopanic/webhook",
    "/status/ping", "/status/ws", "/status/executor", "/status/all", "/status/auth",
    "/debug/health", "/_debug/auth", "/debug/env", "/debug/refresh-auth", "/executor/status",
    "/ops/approve", "/ops/approve/signed", "/ops/reject",
    "/_debug/hmac", "/_debug/echo-hmac", "/_debug/routes",
    # Alerts public (HMAC יאומת בתוך ה-router)
    "/alerts/ping", "/alerts/ingest", "/alerts/_debug/alerts-hmac-check",
}
DEFAULT_PUBLIC_PREFIXES = ["/price", "/static/", "/risk"]
CFG_PUBLIC = set(_split_multi(os.getenv("SECURITY_PUBLIC_PATHS","")))
CFG_PUBLIC_PREFIXES = set(_split_multi(os.getenv("SECURITY_PUBLIC_PREFIXES","")))
if METRICS_PUBLIC: CFG_PUBLIC.add("/metrics")
EFFECTIVE_PUBLIC_PATHS = set(DEFAULT_PUBLIC_PATHS) if PUBLIC_STATUS else set()
EFFECTIVE_PUBLIC_PATHS |= CFG_PUBLIC
EFFECTIVE_PUBLIC_PREFIXES = list(DEFAULT_PUBLIC_PREFIXES) if PUBLIC_STATUS else []
EFFECTIVE_PUBLIC_PREFIXES += list(CFG_PUBLIC_PREFIXES)

logger.info({"event":"public_paths_config","public_status":PUBLIC_STATUS,
             "paths":sorted(EFFECTIVE_PUBLIC_PATHS),"prefixes":sorted(EFFECTIVE_PUBLIC_PREFIXES)})

# ---------- stable instance id ----------
INSTANCE_ID = (
    os.getenv("RENDER_INSTANCE_ID")
    or os.getenv("INSTANCE_ID")
    or os.getenv("HOSTNAME")
    or "unknown"
)

@app.middleware("http")
async def add_server_identity_header(request: Request, call_next):
    try:
        resp = await call_next(request)
    except Exception:
        logger.exception("middleware call_next failed for add_server_identity_header")
        return JSONResponse(status_code=500, content={"detail":"internal error"})
    resp.headers["x-app-instance-id"] = INSTANCE_ID
    resp.headers["rndr-id"] = INSTANCE_ID
    return resp

# ---------- Global auth middleware ----------
@app.middleware("http")
async def validate_token(request: Request, call_next):
    path = request.url.path

    # OPTIONS passthrough
    if request.method.upper() == "OPTIONS":
        try:
            return await call_next(request)
        except Exception:
            logger.exception("middleware call_next failed for %s", path)
            return JSONResponse(status_code=500, content={"detail":"internal error"})

    # public exact paths
    if path in EFFECTIVE_PUBLIC_PATHS:
        try:
            return await call_next(request)
        except Exception:
            logger.exception("middleware call_next failed for %s", path)
            return JSONResponse(status_code=500, content={"detail":"internal error"})

    # public prefixes
    for pfx in EFFECTIVE_PUBLIC_PREFIXES:
        if path.startswith(pfx):
            try:
                return await call_next(request)
            except Exception:
                logger.exception("middleware call_next failed for %s", path)
                return JSONResponse(status_code=500, content={"detail":"internal error"})

    # allow-all
    if allow_all():
        try:
            return await call_next(request)
        except Exception:
            logger.exception("middleware call_next failed for %s", path)
            return JSONResponse(status_code=500, content={"detail":"internal error"})

    # token gate
    a_hdr = request.headers.get("authorization") or request.headers.get("Authorization") or ""
    x_hdr = request.headers.get("x-api-key") or request.headers.get("X-API-Key")
    token = extract_token(request, a_hdr, x_hdr)
    if not token_matches(token):
        return JSONResponse(status_code=401, content={"detail":"Invalid API key"})

    try:
        return await call_next(request)
    except Exception:
        logger.exception("middleware call_next failed for %s", path)
        return JSONResponse(status_code=500, content={"detail":"internal error"})

# ---------- include routers ----------
def _try_include(module_path: str) -> bool:
    try:
        mod = __import__(module_path, fromlist=["router"])
        if hasattr(mod, "router"):
            app.include_router(mod.router)
            logger.info({"event":"router_registered","router":module_path})
            return True
        logger.warning({"event":"router_missing_router_attr","router":module_path})
    except Exception as e:
        logger.warning({"event":"router_register_failed","router":module_path,"error":str(e)})
    return False

_registered_paths = set()
_routes_only = [m.strip() for m in os.getenv("ROUTES_ONLY","").split(",") if m.strip()]

if _routes_only:
    for module_path in _routes_only:
        _try_include(module_path)
else:
    for _mod in (
        "routes.scan_top_volume",
        "routes.scan_now_alias",
        "routes.ops_guard",
        "routes.telegram_ping",
        "routes.debug_hmac",
        "routes.ops_approve",
        "routes.trade",
        "routes.auto_trade",
    ):
        _try_include(_mod)
    for m in pkgutil.iter_modules(["routes"]):
        module_path = f"routes.{m.name}"
        _try_include(module_path)
        try:
            for r in app.router.routes:
                try: _registered_paths.add(getattr(r, "path", None))
                except Exception: pass
        except Exception: pass

def _route_exists(path: str) -> bool:
    try:
        for r in app.router.routes:
            if getattr(r, "path", None) == path: return True
    except Exception: pass
    return False

# ---------- base routes ----------
@app.get("/")
async def root(): return {"ok":True,"status":"ok","service":"app_full","title":"AlgoGPT API","version":APP_VERSION}

@app.get("/health")
async def health(): return {"ok":True,"status":"ok","version":APP_VERSION}

@app.get("/debug/health", include_in_schema=False)
async def debug_health(): return {"ok":True,"status":"ok","env":os.getenv("ENV","prod"),"version":APP_VERSION}

@app.get("/status/ping")
async def status_ping(): return {"ok":True,"ts_ms":int(time.time()*1000)}

if not _route_exists("/status/ws"):
    @app.get("/status/ws")
    async def status_ws(): st = ws_user_status(); return {"ok":True, **st}

if not _route_exists("/status/executor"):
    @app.get("/status/executor")
    async def status_executor(): st = exec_get_counters(); return {"ok":True, **st}

if not _route_exists("/status/all"):
    @app.get("/status/all")
    async def status_all():
        try: ping_ok = bool(fapi_ping())
        except Exception: ping_ok = False
        ws = ws_user_status(); ex = exec_get_counters()
        manager_enabled = os.getenv("MANAGER_ENABLE","1").lower() in ("1","true","yes","on")
        return {
            "ok": True,
            "version": APP_VERSION,
            "instance": INSTANCE_ID,
            "ws": ws,
            "executor": ex,
            "manager": {"enabled": manager_enabled},
            "binance_ping_ok": ping_ok
        }

# auth status/public paths (public)
try:
    from utils.auth import get_loaded_tokens, get_public_paths
except Exception:
    def get_loaded_tokens(mask: bool = True): return []
    def get_public_paths(): return {"paths":[], "prefixes":[]}

if not _route_exists("/status/auth"):
    @app.get("/status/auth")
    async def status_auth():
        toks = get_loaded_tokens(mask=True); public = get_public_paths()
        return {"ok":True,"tokens_count":len(toks),"tokens":toks,"public":public}

@app.get("/price/{symbol}")
async def price(symbol: str):
    src = "binance_fapi"; ts = int(time.time()*1000); err = ""
    try:
        p = get_price(symbol); ok = bool(p and p > 0)
        if not ok: err = "no price"
    except Exception as e:
        p = None; ok = False; err = str(e)
    return {"ok":ok,"symbol":symbol.upper(),"price":float(p) if p is not None else None,"source":src,"ts":ts,"error":err}

@app.get("/readyz")
async def readyz():
    details: Dict[str, Any] = {}; err: Optional[str] = None
    try:
        details["binance_ping_ok"] = bool(fapi_ping())
        if not details["binance_ping_ok"]: err = "binance ping failed"
    except Exception as e:
        details["binance_ping_ok"] = False; err = f"binance ping error: {e}"
    try:
        bal = futures_balance(); details["balance_ok"] = bool(bal and isinstance(bal, list))
        if not details["balance_ok"]: err = (err or "") + "; balance not ok"
    except Exception as e:
        details["balance_ok"] = False; err = (err or "") + f"; balance error: {e}"
    for s in ("BTCUSDT","ETHUSDT","SOLUSDT"):
        try: details[f"price_{s}"] = get_price(s)
        except Exception: details[f"price_{s}"] = None
    return {"ok":(err is None), "error":err, "details":details}

@app.post("/flush")
async def flush_kill_switch():
    done = False
    for name in ("flush_all","flush","reset"):
        try:
            fn = getattr(ConfirmStore, name, None)
            if callable(fn): fn(); done = True; break
        except Exception as e:
            logger.warning({"event":"flush_failed","err":str(e)})
    return {"ok":True,"flushed":done}

# --- public debug auth endpoint ---
try:
    from utils.auth import extract_token as _extract_token, token_matches as _token_matches, get_loaded_tokens as _get_loaded_tokens
except Exception:
    def _get_loaded_tokens(mask: bool = True): return []
    def _extract_token(req, a, b): return None
    def _token_matches(tok): return False

@app.get("/_debug/auth", include_in_schema=False)
async def _debug_auth(request: Request):
    a = request.headers.get("authorization") or request.headers.get("Authorization")
    x = request.headers.get("x-api-key") or request.headers.get("X-API-Key")
    t = _extract_token(request, a, x)
    return {"ok":True,"auth_header":a,"x_api_key":x,"query":dict(request.query_params),
            "extracted_token":t,"matches":bool(_token_matches(t)),
            "tokens_loaded":_get_loaded_tokens(mask=True)}

@app.get("/_debug/routes", include_in_schema=False)
async def _debug_routes():
    paths = sorted({getattr(r, "path", None) for r in app.router.routes if getattr(r, "path", None)})
    return {"paths": paths}

@app.get("/ops/digest/now", include_in_schema=False)
async def ops_digest_now(hours: Optional[int] = None):
    await send_ops_digest_now(hours)
    return {"ok":True,"sent":True,"hours": hours or int(os.getenv("OPS_DIGEST_INTERVAL_HOURS","3"))}

@app.get("/ops/eod/now", include_in_schema=False)
async def ops_eod_now():
    await send_eod_report_now()
    return {"ok":True,"sent":True}

# ---------- startup hooks ----------
WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET","").strip()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN","").strip()
API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else ""
TELEGRAM_AUTO_WEBHOOK = os.getenv("TELEGRAM_AUTO_WEBHOOK","1").lower() in ("1","true","yes","on")

@app.on_event("startup")
async def _startup_preflight_warmup():
    try:
        from utils.auth import get_loaded_tokens
        logger.info({"event":"auth.tokens_loaded","tokens":get_loaded_tokens(mask=True)})
    except Exception: pass
    try: _ = futures_exchange_info_safe(force_refresh=True)
    except Exception as e: logger.warning({"event":"warmup.exinfo_failed","error":str(e)})
    try:
        _ = get_price("BTCUSDT")
        try:
            from utils.get_klines import get_klines_sync  # type: ignore
            _ = get_klines_sync("BTCUSDT", interval=os.getenv("DEFAULT_INTERVAL","15m"), limit=50)
        except Exception: pass
    except Exception as e: logger.warning({"event":"warmup.price_failed","error":str(e)})

@app.on_event("startup")
async def _startup_webhook():
    if not BOT_TOKEN or not TELEGRAM_AUTO_WEBHOOK: return
    public_host = os.getenv("PUBLIC_HOST","



















































































































































































































































































































































































































































































































































































































