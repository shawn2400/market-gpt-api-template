# main.py
from __future__ import annotations
import os, time, asyncio, logging, pkgutil, httpx
from pathlib import Path
from typing import Any, Dict, Optional, Iterable, List
from fnmatch import fnmatch

from fastapi import FastAPI, Request, HTTPException  # ← הוספתי HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse, PlainTextResponse
from fastapi.openapi.utils import get_openapi
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from starlette.status import HTTP_422_UNPROCESSABLE_ENTITY
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.gzip import GZipMiddleware

# ---------- Prometheus (אופציונלי) ----------
try:
    from prometheus_client import make_asgi_app
    _prom_app = make_asgi_app()
except Exception:
    def make_asgi_app():
        async def _dummy_app(scope, receive, send):
            # אפליקציה ריקה במקום /metrics אם prometheus_client לא מותקן
            if scope["type"] == "http":
                await send({
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"text/plain; charset=utf-8")],
                })
                await send({"type": "http.response.body", "body": b""})
        return _dummy_app
    _prom_app = make_asgi_app()

# ---------- utils.* (פולבאקים בטוחים) ----------
# auth
try:
    from utils.auth import extract_token, allow_all, token_matches, get_loaded_tokens, get_public_paths
except Exception:
    def extract_token(request: Request, a_hdr: Optional[str], x_hdr: Optional[str]) -> Optional[str]:
        # מנסה לקחת מה-Header Authorization או X-API-Key או מה-query ?api_key=
        tok = None
        if a_hdr and a_hdr.lower().startswith("bearer "):
            tok = a_hdr.split(" ", 1)[1].strip()
        if not tok and x_hdr:
            tok = x_hdr.strip()
        if not tok:
            tok = request.query_params.get("api_key")
        return tok

    def allow_all() -> bool:
        # ברירת מחדל: אם לא טעונים טוקנים, נאפשר הכול (אפשר לשנות ל-False כדי לחסום)
        return True

    def token_matches(tok: Optional[str]) -> bool:
        # אם תרצה לאכוף API KEY, שים משתנה סביבה API_KEY=...
        expected = os.getenv("API_KEY", "").strip()
        if not expected:
            return True  # אין מפתח נדרש
        return (tok or "") == expected

    def get_loaded_tokens(mask: bool = True):
        val = os.getenv("API_KEY","")
        if not val:
            return []
        return [val[:2] + "***" + val[-2:] if mask else val]

    def get_public_paths():
        return {"paths":[], "prefixes":[]}

# json logger
try:
    from utils.json_logger import setup_json_logging
except Exception:
    def setup_json_logging():
        # לוגר בסיסי אם אין מודול json_logger
        logger = logging.getLogger("algogpt")
        handler = logging.StreamHandler()
        fmt = logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s')
        handler.setFormatter(fmt)
        logger.handlers[:] = [handler]
        logger.propagate = False
        return logger

# metrics middleware
try:
    from utils.metrics_middleware import MetricsMiddleware
except Exception:
    class MetricsMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            return await call_next(request)

# response size limiter
try:
    from utils.response_limits import ResponseSizeLimiter
except Exception:
    class ResponseSizeLimiter(BaseHTTPMiddleware):
        def __init__(self, app, max_bytes: int = 5_242_880):
            super().__init__(app)
            self.max_bytes = max_bytes
        async def dispatch(self, request: Request, call_next):
            resp = await call_next(request)
            # אם התוכן גדול מדי – נחתוך/נחזיר שגיאה רכה
            try:
                body = b""
                async for chunk in resp.body_iterator:
                    body += chunk
                    if len(body) > self.max_bytes:
                        return PlainTextResponse(
                            "Response too large", status_code=413
                        )
                # נשמר את קוד הסטטוס המקורי ונחזיר את הגוף כפי שהוא
                status = getattr(resp, "status_code", 200)
                # נשתדל לא לשנות תשובות JSON/וכו' – כאן אין לנו סוג,
                # אז נחזיר PlainText עם אותו קוד סטטוס (כמו קודם).
                return PlainTextResponse(
                    body.decode("utf-8", errors="ignore"),
                    status_code=status,
                    headers=getattr(resp, "headers", None)
                )
            except Exception:
                return resp

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

# ---- InternalAuthMiddleware (optional) ----
try:
    from app.middlewares import InternalAuthMiddleware
except Exception:
    class InternalAuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next): return await call_next(request)

# ---- RateLimitMiddleware (optional) ----
try:
    from app.rate_limit_mw import RateLimitMiddleware
except Exception:
    class RateLimitMiddleware(BaseHTTPMiddleware):
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
            def pending(cls) -> List[Dict[str, Any]]:
                return list(cls._P.values())
            @classmethod
            def create(cls, payload: Dict[str, Any]) -> str:
                import time as _t
                tid = payload.get("ticket_id") or f"TKT-{int(_t.time()*1000)}"
                payload["ticket_id"] = tid
                payload.setdefault("created_ts", int(_t.time()))
                payload.setdefault("ttl_sec", int(os.getenv("OPS_TICKET_TTL_SEC", "1800")))
                cls._P[tid] = payload
                return tid
            @classmethod
            def decide(cls, ticket_id: str, approved: bool) -> Dict[str, Any]:
                it = cls._P.pop(ticket_id, None)
                if not it:
                    return {"ok": False, "error": "not_found"}
                it["approved"] = approved
                it["decided_ts"] = int(time.time())
                return {"ok": True, "approved": approved, "ticket_id": ticket_id}
            @classmethod
            def flush_all(cls) -> None:
                cls._P.clear()
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

# ---------- Validation error => 422 ----------
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

# ---------- Class middlewares ----------
app.add_middleware(ResponseSizeLimiter, max_bytes=int(os.getenv("RESPONSE_MAX_BYTES","5242880")))
app.add_middleware(GZipMiddleware, minimum_size=1000)

UI_DOMAIN = os.getenv("UI_DOMAIN","").strip()
_cao = os.getenv("CORS_ALLOW_ORIGINS", "*")
CORS_ALLOWED = [UI_DOMAIN] if UI_DOMAIN else [o for o in _cao.split(",") if o]
CORS_ALLOW_CREDENTIALS_CFG = os.getenv("CORS_ALLOW_CREDENTIALS","0").lower() in ("1","true","on")
CORS_ALLOW_CREDENTIALS_EFFECTIVE = CORS_ALLOW_CREDENTIALS_CFG and CORS_ALLOWED != ["*"]

app.add_middleware(CORSMiddleware,
    allow_origins=["*"] if not CORS_ALLOWED else CORS_ALLOWED,
    allow_methods=["*"], allow_headers=["*"], allow_credentials=CORS_ALLOW_CREDENTIALS_EFFECTIVE)

# InternalAuthMiddleware כבוי כברירת מחדל — הדלקה רק אם צריך
if os.getenv("INTERNAL_AUTH_ENABLE","0").lower() in ("1","true","on"):
    app.add_middleware(InternalAuthMiddleware)

# Rate limit (אם קיים)
app.add_middleware(RateLimitMiddleware)

app.add_middleware(MetricsMiddleware)
app.mount("/metrics", _prom_app)

# static
app.mount("/static", StaticFiles(directory="static"), name="static")

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
    "/ops/approve", "/ops/approve-link", "/ops/approve/signed", "/ops/reject", "/ops/digest/expired",
    "/_debug/hmac", "/_debug/echo-hmac", "/_debug/routes",
    "/alerts/ping", "/alerts/ingest", "/alerts/_debug/alerts-hmac-check",
    "/ui/dashboard", "/ops/ui", "/ops/ui/ticket",
    "/trade/approve", "/trade/reject",
    "/metrics-json", "/metrics/labels", "/metrics/health",
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

# ---------- rndr-id ----------
INSTANCE_ID = (
    os.getenv("RENDER_INSTANCE_ID")
    or os.getenv("INSTANCE_ID")
    or os.getenv("HOSTNAME")
    or "unknown"
)

# ---------- Secure global auth middleware ----------
class SecureAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, public_paths: set[str], public_prefixes: list[str]):
        super().__init__(app)
        self.public_paths = set(public_paths)
        self.public_prefixes = list(public_prefixes)

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if request.method.upper() == "OPTIONS":
            return await call_next(request)
        if path in self.public_paths or any(path.startswith(p) for p in self.public_prefixes):
            return await call_next(request)
        if allow_all():
            return await call_next(request)
        try:
            a_hdr = request.headers.get("authorization") or request.headers.get("Authorization") or ""
            x_hdr = request.headers.get("x-api-key") or request.headers.get("X-API-Key")
            tok = extract_token(request, a_hdr, x_hdr)
            if not token_matches(tok):
                return JSONResponse(status_code=401, content={"detail": "Invalid API key"})
        except Exception:
            logging.getLogger("algogpt").exception("SecureAuthMiddleware: auth logic failed")
            return JSONResponse(status_code=500, content={"ok": False, "error": "middleware_auth_failed"})
        return await call_next(request)

app.add_middleware(
    SecureAuthMiddleware,
    public_paths=EFFECTIVE_PUBLIC_PATHS,
    public_prefixes=EFFECTIVE_PUBLIC_PREFIXES,
)

# ---------- ONE safe middleware: always returns a Response + adds headers ----------
@app.middleware("http")
async def _final_safety_and_headers(request: Request, call_next):
    try:
        resp = await call_next(request)
        if resp is None:
            resp = PlainTextResponse("Internal server error (no response)", status_code=500)

    except HTTPException as exc:
        # ← שמירת קוד הסטטוס וה־detail המקורי; לא להחזיר 200 בטעות
        detail = exc.detail if isinstance(exc.detail, (str, dict, list)) else str(exc.detail)
        resp = JSONResponse({"detail": detail}, status_code=exc.status_code)

    except Exception as exc:
        logging.getLogger("algogpt").exception(
            "final_mw: call_next failed",
            extra={
                "path": str(getattr(request.url, "path", "")),
                "method": request.method,
                "client": getattr(getattr(request, "client", None), "host", None),
                "x_req_id": request.headers.get("x-request-id"),
            },
        )
        resp = JSONResponse({"detail": "internal_error", "where": "final_mw", "message": str(exc)}, status_code=500)

    try:
        resp.headers["x-app-instance-id"] = INSTANCE_ID
        resp.headers["rndr-id"] = INSTANCE_ID
    except Exception:
        pass
    return resp

# ---------- our safe digest/eod routes (registered BEFORE routers) ----------
@app.get("/ops/digest/now", include_in_schema=False)
async def ops_digest_now(hours: Optional[int] = None):
    """
    תואם-לאחור: אם send_ops_digest_now תומכת ב-hours נעביר, אחרת נקרא בלי פרמטרים.
    """
    ok, err = True, None
    try:
        import inspect
        params = {}
        try:
            sig = inspect.signature(send_ops_digest_now)  # type: ignore
            if "hours" in sig.parameters:
                params["hours"] = hours
        except Exception:
            params = {}
        if params:
            await send_ops_digest_now(**params)  # type: ignore
        else:
            await send_ops_digest_now()  # type: ignore
    except TypeError:
        try:
            await send_ops_digest_now()  # type: ignore
        except Exception as e:
            ok, err = False, str(e)
    except Exception as e:
        ok, err = False, str(e)
    effective_hours = hours or int(os.getenv("OPS_DIGEST_INTERVAL_HOURS","3"))
    return {"ok": ok, "sent": ok, "hours": effective_hours, "error": err}

@app.get("/ops/eod/now", include_in_schema=False)
async def ops_eod_now():
    await send_eod_report_now()
    return {"ok":True,"sent":True}

# ---------- include routers (WITHOUT routes.ops_digest to avoid conflicts) ----------
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
        if module_path == "routes.ops_digest":
            continue
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
        "routes.trade_approvals",
        "routes.auto_trade",
        "routes.ops_ui",
        "routes.ops_flags",
        "routes.position_ops",
        "routes.calibration",
        # "routes.ops_digest",  # ← בכוונה לא לכלול כדי למנוע התנגשות עם /ops/digest/now
    ):
        _try_include(_mod)
    # אם אין תיקיית routes – הקריאה הזו לא תכשיל את האפליקציה
    try:
        for m in pkgutil.iter_modules(["routes"]):
            module_path = f"routes.{m.name}"
            if module_path == "routes.ops_digest":
                continue
            _try_include(module_path)
        try:
            for r in app.router.routes:
                try: _registered_paths.add(getattr(r, "path", None))
                except Exception: pass
        except Exception: pass
    except Exception:
        pass

def _route_exists(path: str) -> bool:
    try:
        for r in app.router.routes:
            if getattr(r, "path", None) == path: return True
    except Exception: pass
    return False

# ---------- base routes ----------
@app.get("/")
async def root():
    return {"ok":True,"status":"ok","service":"app_full","title":"AlgoGPT API","version":APP_VERSION}

@app.get("/health")
async def health():
    return {"ok":True,"status":"ok","version":APP_VERSION}

@app.get("/debug/health", include_in_schema=False)
async def debug_health():
    return {"ok":True,"status":"ok","env":os.getenv("ENV","prod"),"version":APP_VERSION}

def _mask(v: str) -> str:
    if not v: return ""
    if len(v) <= 8: return "*" * len(v)
    return v[:4] + "*" * (len(v)-8) + v[-4:]

@app.get("/debug/env", include_in_schema=False)
async def debug_env():
    return {
        "ok": True,
        "INSTANCE_ID": os.getenv("INSTANCE_ID", ""),
        "ALERTS_INGEST_HMAC_SECRET": _mask(os.getenv("ALERTS_INGEST_HMAC_SECRET","")),
        "ALERTS_INGEST_HMAC_KEY_IS_HEX": os.getenv("ALERTS_INGEST_HMAC_KEY_IS_HEX",""),
        "WEBHOOK_HMAC_SECRET": _mask(os.getenv("WEBHOOK_HMAC_SECRET","")),
        "RATE_LIMIT_ENABLE": os.getenv("RATE_LIMIT_ENABLE",""),
        "RATE_LIMIT_BACKEND": os.getenv("RATE_LIMIT_BACKEND",""),
        "RL_FAIL_OPEN": os.getenv("RL_FAIL_OPEN",""),
        "SCAN_RL_LIMIT": os.getenv("SCAN_RL_LIMIT",""),
        "SCAN_RL_WINDOW": os.getenv("SCAN_RL_WINDOW",""),
    }

@app.get("/status/ping")
async def status_ping():
    return {"ok":True,"ts_ms":int(time.time()*1000)}

if not _route_exists("/status/ws"):
    @app.get("/status/ws")
    async def status_ws():
        st = ws_user_status(); return {"ok":True, **st}

if not _route_exists("/status/executor"):
    @app.get("/status/executor")
    async def status_executor():
        st = exec_get_counters(); return {"ok":True, **st}

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

@app.get("/_debug/auth", include_in_schema=False)
async def _debug_auth(request: Request):
    a = request.headers.get("authorization") or request.headers.get("Authorization")
    x = request.headers.get("x-api-key") or request.headers.get("X-API-Key")
    t = extract_token(request, a, x)
    return {"ok":True,"auth_header":a,"x_api_key":x,"query":dict(request.query_params),
            "extracted_token":t,"matches":bool(token_matches(t)),
            "tokens_loaded":get_loaded_tokens(mask=True)}

@app.get("/_debug/routes", include_in_schema=False)
async def _debug_routes():
    paths = sorted({getattr(r, "path", None) for r in app.router.routes if getattr(r, "path", None)})
    return {"paths": paths}

# ---------- startup/shutdown ----------
WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET","").strip()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN","").strip()
API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else ""
TELEGRAM_AUTO_WEBHOOK = os.getenv("TELEGRAM_AUTO_WEBHOOK","1").lower() in ("1","true","yes","on")

@app.on_event("startup")
async def _startup_preflight_warmup():
    try:
        from utils.auth import get_loaded_tokens as _glt
        logger.info({"event":"auth.tokens_loaded","tokens":_glt(mask=True)})
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
    public_host = os.getenv("PUBLIC_HOST","").strip()
    if not public_host: return
    try:
        async with httpx.AsyncClient(timeout=10.0) as cli:
            await cli.post(f"{API_BASE}/setWebhook",
                json={"url":f"{public_host.rstrip('/')}/telegram/webhook",
                      "secret_token":WEBHOOK_SECRET,"drop_pending_updates":True,"max_connections":40})
    except Exception as e:
        logging.getLogger("algogpt.telegram").warning("setWebhook failed: %s", e)

@app.on_event("startup")
async def _startup_user_stream():
    try:
        if os.getenv("USER_STREAM_ENABLE","1").lower() in ("1","true","yes","on"):
            from utils import ws_user_stream  # type: ignore
            ws_user_stream.start(); logger.info({"event":"ws_user_stream_autostart"})
    except Exception as e:
        logger.warning({"event":"ws_user_stream_autostart_failed","error":str(e)})

@app.on_event("startup")
async def _ops_schedulers():
    await ensure_ops_schedulers_started()

# --- Approvals GC (auto-reject expired) ---
try:
    from utils.approvals_gc import start_approvals_gc as _start_gc  # type: ignore
    _gc_needs_interval = True
except Exception:
    try:
        from utils.approvals_gc import start_gc_task as _start_gc  # type: ignore
        _gc_needs_interval = False
    except Exception:
        _start_gc = None  # type: ignore
        _gc_needs_interval = False

APPROVAL_GC_ENABLE = os.getenv("APPROVAL_GC_ENABLE","1").lower() in ("1","true","yes","on")
APPROVAL_GC_INTERVAL_SEC = int(os.getenv("APPROVAL_GC_INTERVAL_SEC","15"))

@app.on_event("startup")
async def _startup_approvals_gc():
    try:
        if APPROVAL_GC_ENABLE and _start_gc:
            if _gc_needs_interval:
                _start_gc(interval=APPROVAL_GC_INTERVAL_SEC)
            else:
                _start_gc()
            logging.getLogger("algogpt.approvals.gc").info({"event":"gc.start_ok","interval":APPROVAL_GC_INTERVAL_SEC})
    except Exception as e:
        logging.getLogger("algogpt.approvals.gc").warning({"event":"gc.start_failed","err":str(e)})

# --- Expired-digest Job (auto) ---
try:
    from utils.approvals_digest_job import start_expired_digest_job  # type: ignore
except Exception:
    start_expired_digest_job = None  # type: ignore

_bg_tasks: Dict[str, asyncio.Task] = {}

@app.on_event("startup")
async def _startup_expired_digest_job():
    try:
        if start_expired_digest_job:
            maybe = start_expired_digest_job()  # may return Task/None/Coroutine
            task = None
            if asyncio.iscoroutine(maybe):
                task = asyncio.create_task(maybe, name="expired_digest_job")
            elif isinstance(maybe, asyncio.Task):
                task = maybe
            if task:
                _bg_tasks["expired_digest_job"] = task
            logging.getLogger("algogpt.approvals.digest_job").info({"event":"digest_job.start_ok"})
    except Exception as e:
        logging.getLogger("algogpt.approvals.digest_job").warning({"event":"digest_job.start_failed","err":str(e)})

@app.on_event("startup")
async def _start_trade_manager_loop():
    if TRADE_MANAGER_ENABLE and manage_open_trades_loop:
        t = asyncio.create_task(manage_open_trades_loop(interval=TRADE_MANAGER_INTERVAL_SEC), name="trade_manager")
        _bg_tasks["trade_manager"] = t
        logger.info({"event":"trade_manager_loop_started","interval_sec":TRADE_MANAGER_INTERVAL_SEC})

@app.on_event("shutdown")
async def _graceful_shutdown():
    for name, t in list(_bg_tasks.items()):
        if t and not t.done():
            try: t.cancel()
            except Exception: pass
    for name, t in list(_bg_tasks.items()):
        if not t: continue
        try:
            await t
        except asyncio.CancelledError:
            pass
        except Exception:
            logging.getLogger("algogpt").exception("background task %s crashed on shutdown", name)

# ---------- run ----------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=os.getenv("BIND_HOST","0.0.0.0"), port=int(os.getenv("PORT","10000")))

























































































































































































































































































































































































































































































































































































































