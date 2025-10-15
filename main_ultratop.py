# main_ultratop.py — AlgoGPT UltraTop (WS-only), plug & play:
# - Standalone: set ULTRATOP_MODE=standalone  and  APP_MODULE=main_ultratop:app
# - Recommended: run main:app and call setup_ultratop(app, prefix="/ultra") from main.py
from __future__ import annotations

import os
import time
import hmac
import hashlib
import json
import logging
import threading
from typing import Optional, Dict, Any

from fastapi import FastAPI, Request, HTTPException, Depends, APIRouter, Header
from fastapi.responses import PlainTextResponse, JSONResponse, Response
from pydantic import BaseModel

# Optional deps
try:
    import jsonschema  # optional validation
except Exception:
    jsonschema = None

try:
    import yaml  # required for policy DSL
except Exception as e:
    raise RuntimeError("PyYAML is required. pip install pyyaml") from e

# Prometheus
from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    ProcessCollector,
    PlatformCollector,
)

APP_NAME = os.getenv("APP_NAME", "algogpt")
APP_TITLE = os.getenv("APP_TITLE", "AlgoGPT Service")
APP_VERSION = os.getenv("ALGOGPT_VERSION", "2.18.0")
START_TS = time.time()

# ---------- Logging ----------
logger = logging.getLogger("algogpt.ultratop")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))

# ---------- Prometheus registry & metrics ----------
registry = CollectorRegistry()
# attach process/platform collectors to our private registry (avoid double-registration)
try:
    ProcessCollector(registry=registry)
    PlatformCollector(registry=registry)
except Exception:
    pass

APP_UPTIME = Gauge("app_uptime_seconds", "Application uptime seconds", registry=registry)
READY_WS_OK = Gauge("ready_ws_ok", "WebSocket manager up", registry=registry)
READY_POLICY = Gauge("ready_policy_loaded", "Policy loaded", registry=registry)
ATTACH_SLTP_P95 = Gauge("attach_sltp_p95_ms", "Target SLO placeholder for attach SL/TP p95", registry=registry)
BUILD_INFO = Gauge("build_info", "Build information", ["app", "version"], registry=registry)
HTTP_REQS = Counter("http_requests_total", "HTTP requests total", ["method", "path", "status"], registry=registry)
HTTP_LATENCY = Histogram("http_request_latency_seconds", "HTTP request latency seconds", ["method", "path"], registry=registry)

BUILD_INFO.labels(app=APP_NAME, version=APP_VERSION).inc(0)
ATTACH_SLTP_P95.set(300)  # default SLO placeholder

# ---------- Runtime Prefs ----------
class RuntimePrefs(BaseModel):
    NET_WS_ONLY_PRICES: int = 1
    NET_DISABLE_POLLING: int = 1

    ENTRY_CONF_MIN: float = 0.65
    TP_DYNAMIC_ENABLE: int = 1
    TRAIL_HYBRID_ENABLE: int = 1
    TIME_STOP_ENABLE: int = 1
    BE_PLUS_ENABLE: int = 1
    FLIP_ENABLE: int = 1

    POLICY_DSL_ENABLE: int = 1
    SLO_GUARD_ENABLE: int = 1

    class Config:
        extra = "allow"


class RuntimePrefsStore:
    _instance: Optional["RuntimePrefsStore"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._rw = threading.RLock()
        self._prefs = self._from_env()

    @classmethod
    def instance(cls) -> "RuntimePrefsStore":
        with cls._lock:
            if cls._instance is None:
                cls._instance = RuntimePrefsStore()
            return cls._instance

    def _coerce(self, v: str):
        vl = v.lower()
        if vl in ("true", "false", "1", "0", "yes", "no", "on", "off"):
            return 1 if vl in ("true", "1", "yes", "on") else 0
        try:
            if "." in v:
                return float(v)
            return int(v)
        except Exception:
            return v

    def _from_env(self) -> RuntimePrefs:
        kv = {k: self._coerce(v) for k, v in os.environ.items() if k.isupper()}
        return RuntimePrefs(**kv)

    def get(self) -> RuntimePrefs:
        with self._rw:
            return self._prefs

    def update(self, patch: Dict[str, Any]) -> RuntimePrefs:
        with self._rw:
            merged = self._prefs.dict()
            merged.update(patch)
            self._prefs = RuntimePrefs(**merged)
            return self._prefs


# ---------- Policy Manager ----------
class PolicyManager:
    def __init__(self, path: str, schema_path: Optional[str] = None):
        self.path = path
        self.schema_path = schema_path
        self.policy: Dict[str, Any] = {}
        self.schema: Optional[Dict[str, Any]] = None
        self.mtime: float = 0.0

    def load(self) -> Dict[str, Any]:
        # Load schema if present
        if self.schema_path and jsonschema:
            try:
                with open(self.schema_path, "r", encoding="utf-8") as f:
                    self.schema = json.load(f)
            except Exception as e:
                logger.warning(f"Schema load failed: {e}")

        # Load YAML policy
        with open(self.path, "r", encoding="utf-8") as f:
            doc = yaml.safe_load(f) or {}

        # Validate against schema if both available
        if self.schema and jsonschema:
            try:
                jsonschema.validate(doc, self.schema)  # type: ignore
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"policy schema validation failed: {e}")

        self.policy = doc
        self.mtime = time.time()
        logger.info("Policy loaded from %s", self.path)
        return self.policy


# ---------- HMAC helpers ----------
def verify_hmac(headers: Dict[str, str], body: bytes, secret: str) -> None:
    sig = headers.get("X-Signature", "")
    ts = headers.get("X-Timestamp", "")
    if not sig or not ts:
        raise HTTPException(status_code=401, detail="missing signature headers")
    mac = hmac.new(secret.encode("utf-8"), ts.encode("utf-8") + b"." + body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(mac, sig):
        raise HTTPException(status_code=403, detail="invalid signature")


# ---------- Global singletons ----------
prefs_store = RuntimePrefsStore.instance()
state = {"ws_ok": False, "policy_loaded": False}
policy_path = os.getenv("POLICY_DSL_PATH", "policies/dynamic_policy.yaml")
policy_schema_path = os.getenv("POLICY_SCHEMA_PATH", "config/policy_schema.json")
policy_mgr = PolicyManager(policy_path, policy_schema_path)
_stop = threading.Event()

# bearer protection for /metrics (recommended)
METRICS_BEARER = os.getenv("METRICS_BEARER", "").strip()

# ---------- WS manager (placeholder; plug real WS here) ----------
def ws_loop():
    logger.info("WS loop started")
    state["ws_ok"] = True
    READY_WS_OK.set(1.0)
    try:
        while not _stop.is_set():
            # TODO: connect Binance market/user streams, multiplex, resubscribe, stale-protection
            time.sleep(1.0)
    finally:
        state["ws_ok"] = False
        READY_WS_OK.set(0.0)
        logger.info("WS loop stopped")


# ---------- Router (can be attached to any app) ----------
router = APIRouter()


@router.get("/health", response_class=PlainTextResponse)
def health():
    return "ok"


@router.get("/readyz", response_class=JSONResponse)
def readyz():
    ok = bool(state["ws_ok"] and state["policy_loaded"])
    return {"ok": ok, "ws_ok": state["ws_ok"], "policy_loaded": state["policy_loaded"]}


@router.get("/readyz/strict", response_class=JSONResponse)
def readyz_strict():
    ok = bool(state["ws_ok"] and state["policy_loaded"])
    status = 200 if ok else 503
    return JSONResponse({"ok": ok, "ws_ok": state["ws_ok"], "policy_loaded": state["policy_loaded"]}, status_code=status)


@router.get("/meta/version", response_class=JSONResponse)
def meta_version():
    return {"name": APP_NAME, "title": APP_TITLE, "version": APP_VERSION}


@router.get("/meta", response_class=JSONResponse)
def meta_all(prefs: RuntimePrefs = Depends(lambda: prefs_store.get())):
    return {
        "name": APP_NAME,
        "title": APP_TITLE,
        "version": APP_VERSION,
        "uptime_sec": round(time.time() - START_TS, 2),
        "flags": prefs.dict(),
    }


@router.get("/metrics")
def metrics(authorization: Optional[str] = Header(default=None)):
    # Bearer protection if configured
    if METRICS_BEARER:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="missing bearer")
        token = authorization.split(" ", 1)[1]
        if token != METRICS_BEARER:
            raise HTTPException(status_code=403, detail="invalid bearer")

    APP_UPTIME.set(time.time() - START_TS)
    blob = generate_latest(registry)
    return Response(content=blob, media_type=CONTENT_TYPE_LATEST)


class PrefsPatch(BaseModel):
    patch: Dict[str, Any]


@router.post("/ops/runtime/prefs")
async def patch_prefs(req: Request, payload: PrefsPatch):
    secret = os.getenv("OPS_SIGN_SECRET", "")
    if not secret:
        raise HTTPException(status_code=500, detail="OPS_SIGN_SECRET not set")
    body = await req.body()
    verify_hmac(req.headers, body, secret)
    updated = prefs_store.update(payload.patch)
    logger.info("runtime prefs updated")
    return {"ok": True, "prefs": updated.dict()}


@router.post("/ops/policy/reload")
async def policy_reload(req: Request):
    secret = os.getenv("OPS_SIGN_SECRET", "")
    if not secret:
        raise HTTPException(status_code=500, detail="OPS_SIGN_SECRET not set")
    body = await req.body()
    verify_hmac(req.headers, body, secret)
    policy_mgr.load()
    state["policy_loaded"] = True
    READY_POLICY.set(1.0)
    return {"ok": True, "policy_mtime": policy_mgr.mtime}


# ---------- Middleware (attachable) ----------
async def _metrics_middleware(request: Request, call_next):
    start = time.time()
    resp = await call_next(request)
    status = getattr(resp, "status_code", 500)
    dur = time.time() - start
    path = request.url.path
    method = request.method
    try:
        # bucket popular/diagnostic paths and collapse the rest to "/other"
        bucket_path = path if path in (
            "/health", "/readyz", "/readyz/strict", "/meta", "/meta/version", "/metrics"
        ) else "/other"
        HTTP_REQS.labels(method=method, path=bucket_path, status=str(status)).inc()
        HTTP_LATENCY.labels(method=method, path=bucket_path).observe(dur)
    except Exception:
        pass
    return resp


def _attach_middleware(app: FastAPI):
    if getattr(app.state, "_ultra_mw_attached", False):
        return
    app.middleware("http")(_metrics_middleware)
    app.state._ultra_mw_attached = True


def _attach_lifecycle(app: FastAPI):
    if getattr(app.state, "_ultra_lc_attached", False):
        return

    @app.on_event("startup")
    def _ultra_startup():
        try:
            policy_mgr.load()
            state["policy_loaded"] = True
            READY_POLICY.set(1.0)
        except Exception as e:
            logger.error("Policy load error: %s", e)
            state["policy_loaded"] = False
            READY_POLICY.set(0.0)
        t = threading.Thread(target=ws_loop, name="ws", daemon=True)
        t.start()
        logger.info("UltraTop startup complete")

    @app.on_event("shutdown")
    def _ultra_shutdown():
        _stop.set()

    app.state._ultra_lc_attached = True


# ---------- Public helpers ----------
def setup_ultratop(app: FastAPI, prefix: str = "") -> None:
    """
    Mount UltraTop on an existing FastAPI app.
    - prefix="" exposes the routes as-is (like standalone)
    - prefix="/ultra" nests everything under /ultra
    """
    if getattr(app.state, "_ultra_router_attached", False):
        return
    _attach_middleware(app)
    _attach_lifecycle(app)
    app.include_router(router, prefix=prefix)
    app.state._ultra_router_attached = True


def create_ultratop_app(prefix: str = "") -> FastAPI:
    app = FastAPI(title=APP_TITLE, version=APP_VERSION)
    setup_ultratop(app, prefix=prefix)
    return app


# ---------- App export ----------
# Default is "noop" to avoid auto-mount on import. main.py will call setup_ultratop(...).
_MODE = os.getenv("ULTRATOP_MODE", "noop").lower()
_PREFIX = os.getenv("ULTRATOP_PREFIX", "/ultra")

if _MODE in ("mount", "embed", "attach"):
    from main import app as _base_app  # use main.py app and attach here
    setup_ultratop(_base_app, prefix=_PREFIX)
    app = _base_app
elif _MODE == "standalone":
    app = create_ultratop_app(prefix=os.getenv("ULTRATOP_PREFIX", ""))
else:
    # noop (or unknown): provide a minimal app for safety
    app = FastAPI(title=APP_TITLE, version=APP_VERSION)

    @app.get("/health", response_class=PlainTextResponse)
    def _noop_health():
        return "ok"




