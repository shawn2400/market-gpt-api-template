# main_ultratop.py — FastAPI wiring for AlgoGPT (Ultra-Top, zero-polling)
from __future__ import annotations

import os, time, hmac, hashlib, json, logging, threading
from typing import Optional, Dict, Any

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import PlainTextResponse, JSONResponse, Response
from pydantic import BaseModel
try:
    import jsonschema  # optional validation
except Exception:
    jsonschema = None
try:
    import yaml  # required
except Exception as e:
    raise RuntimeError("PyYAML is required. pip install pyyaml") from e

# Prometheus
from prometheus_client import (
    Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST, CollectorRegistry, PROCESS_COLLECTOR, PLATFORM_COLLECTOR
)

APP_NAME = os.getenv("APP_NAME", "algogpt")
APP_TITLE = os.getenv("APP_TITLE", "AlgoGPT Service")
APP_VERSION = os.getenv("ALGOGPT_VERSION", "2.18.0")
START_TS = time.time()

# ---------- Logging ----------
logger = logging.getLogger("algogpt")
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
logger.addHandler(handler)
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))

# ---------- Prometheus registry & metrics ----------
registry = CollectorRegistry()
# default python process/platform collectors
PROCESS_COLLECTOR.registries = set()  # detach globals to avoid double-reg
PLATFORM_COLLECTOR.registries = set()
PROCESS_COLLECTOR.register(registry)
PLATFORM_COLLECTOR.register(registry)

APP_UPTIME = Gauge("app_uptime_seconds", "Application uptime seconds", registry=registry)
READY_WS_OK = Gauge("ready_ws_ok", "WebSocket manager up", registry=registry)
READY_POLICY = Gauge("ready_policy_loaded", "Policy loaded", registry=registry)
ATTACH_SLTP_P95 = Gauge("attach_sltp_p95_ms", "Target SLO placeholder for attach SL/TP p95", registry=registry)
BUILD_INFO = Gauge("build_info", "Build information", ["app", "version"], registry=registry)
HTTP_REQS = Counter("http_requests_total", "HTTP requests total", ["method", "path", "status"], registry=registry)
HTTP_LATENCY = Histogram("http_request_latency_seconds", "HTTP request latency seconds", ["method", "path"], registry=registry)

BUILD_INFO.labels(app=APP_NAME, version=APP_VERSION).inc(0)
ATTACH_SLTP_P95.set(300)  # default SLO placeholder

# ---------- FastAPI ----------
app = FastAPI(title=APP_TITLE, version=APP_VERSION)

# ---------- Request metrics middleware ----------
@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    start = time.time()
    try:
        resp = await call_next(request)
        status = getattr(resp, "status_code", 500)
    except Exception:
        status = 500
        raise
    finally:
        dur = time.time() - start
        path = request.url.path
        method = request.method
        HTTP_REQS.labels(method=method, path=path, status=str(status)).inc()
        # cap cardinality on path: keep common control-plane endpoints granular; others collapsed
        bucket_path = path if path in ("/health", "/readyz", "/readyz/strict", "/meta", "/meta/version", "/metrics") else "/other"
        HTTP_LATENCY.labels(method=method, path=bucket_path).observe(dur)
    return resp

# ---------- Runtime Prefs ----------
class RuntimePrefs(BaseModel):
    # WS-only & core toggles (extend freely)
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
        if vl in ("true", "false"):
            return 1 if vl == "true" else 0
        try:
            if "." in v:
                return float(v)
            return int(v)
        except:
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
        if self.schema_path and jsonschema:
            try:
                with open(self.schema_path, "r", encoding="utf-8") as f:
                    self.schema = json.load(f)
            except Exception as e:
                logger.warning(f"Schema load failed: {e}")

        with open(self.path, "r", encoding="utf-8") as f:
            doc = yaml.safe_load(f) or {}

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
    ts  = headers.get("X-Timestamp", "")
    if not sig or not ts:
        raise HTTPException(status_code=401, detail="missing signature headers")
    mac = hmac.new(secret.encode("utf-8"), ts.encode("utf-8")+b"."+body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(mac, sig):
        raise HTTPException(status_code=403, detail="invalid signature")

# ---------- App state ----------
prefs_store = RuntimePrefsStore.instance()
state = {"ws_ok": False, "policy_loaded": False}
policy_path = os.getenv("POLICY_DSL_PATH", "policies/dynamic_policy.yaml")
policy_schema_path = os.getenv("POLICY_SCHEMA_PATH", "config/policy_schema.json")
policy_mgr = PolicyManager(policy_path, policy_schema_path)

# ---------- WS manager (placeholder, zero polling) ----------
_stop = threading.Event()
def ws_loop():
    logger.info("WS loop started")
    state["ws_ok"] = True
    READY_WS_OK.set(1.0)
    try:
        while not _stop.is_set():
            time.sleep(1.0)
    finally:
        state["ws_ok"] = False
        READY_WS_OK.set(0.0)
        logger.info("WS loop stopped")

@app.on_event("startup")
def on_start():
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
    logger.info("Startup complete")

@app.on_event("shutdown")
def on_stop():
    _stop.set()

# ---------- Deps ----------
def get_prefs() -> RuntimePrefs:
    return prefs_store.get()

# ---------- Endpoints ----------
@app.get("/health", response_class=PlainTextResponse)
def health():
    return "ok"

@app.get("/readyz", response_class=JSONResponse)
def readyz():
    ok = bool(state["ws_ok"] and state["policy_loaded"])
    # keep healthcheck friendly: always 200 for Render /readyz
    return {"ok": ok, "ws_ok": state["ws_ok"], "policy_loaded": state["policy_loaded"]}

@app.get("/readyz/strict", response_class=JSONResponse)
def readyz_strict():
    ok = bool(state["ws_ok"] and state["policy_loaded"])
    status = 200 if ok else 503
    return JSONResponse({"ok": ok, "ws_ok": state["ws_ok"], "policy_loaded": state["policy_loaded"]}, status_code=status)

@app.get("/meta/version", response_class=JSONResponse)
def meta_version():
    return {"name": APP_NAME, "title": APP_TITLE, "version": APP_VERSION}

@app.get("/meta", response_class=JSONResponse)
def meta_all(prefs: RuntimePrefs = Depends(get_prefs)):
    return {
        "name": APP_NAME, "title": APP_TITLE, "version": APP_VERSION,
        "uptime_sec": round(time.time() - START_TS, 2),
        "flags": prefs.dict()
    }

@app.get("/metrics")
def metrics():
    APP_UPTIME.set(time.time() - START_TS)
    blob = generate_latest(registry)
    return Response(content=blob, media_type=CONTENT_TYPE_LATEST)

# ---------- Ops (HMAC) ----------
class PrefsPatch(BaseModel):
    patch: Dict[str, Any]

@app.post("/ops/runtime/prefs")
async def patch_prefs(req: Request, payload: PrefsPatch):
    secret = os.getenv("OPS_SIGN_SECRET", "")
    if not secret:
        raise HTTPException(status_code=500, detail="OPS_SIGN_SECRET not set")
    body = await req.body()
    verify_hmac(req.headers, body, secret)
    updated = prefs_store.update(payload.patch)
    logger.info("runtime prefs updated")
    return {"ok": True, "prefs": updated.dict()}

@app.post("/ops/policy/reload")
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

# Run with:
# uvicorn main_ultratop:app --host 0.0.0.0 --port ${PORT:-10000}

