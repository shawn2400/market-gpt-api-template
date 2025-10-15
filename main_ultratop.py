# main_ultratop.py — FastAPI wiring for AlgoGPT (Ultra-Top, zero-polling)
from __future__ import annotations

import os, time, hmac, hashlib, json, logging, threading
from typing import Optional, Dict, Any

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import PlainTextResponse, JSONResponse
from pydantic import BaseModel, Field
try:
    import jsonschema  # optional validation
except Exception:
    jsonschema = None
try:
    import yaml  # required
except Exception as e:
    raise RuntimeError("PyYAML is required. pip install pyyaml") from e

APP_NAME = os.getenv("APP_NAME", "algogpt")
APP_TITLE = os.getenv("APP_TITLE", "AlgoGPT API")
APP_VERSION = os.getenv("ALGOGPT_VERSION", "2.18.0")
START_TS = time.time()

# ---------- Logging ----------
logger = logging.getLogger("algogpt")
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
logger.addHandler(handler)
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))

# ---------- Runtime Prefs ----------
class RuntimePrefs(BaseModel):
    # a small subset; extend freely
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
            if "." in v: return float(v)
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

# ---------- App ----------
app = FastAPI(title=APP_TITLE, version=APP_VERSION)
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
    try:
        while not _stop.is_set():
            # TODO: חבר כאן את ה-WS האמיתי (Binance market/user streams, multiplex, resubscribe)
            time.sleep(1.0)
    finally:
        state["ws_ok"] = False
        logger.info("WS loop stopped")

@app.on_event("startup")
def on_start():
    try:
        policy_mgr.load()
        state["policy_loaded"] = True
    except Exception as e:
        logger.error("Policy load error: %s", e)
        state["policy_loaded"] = False
    t = threading.Thread(target=ws_loop, name="ws", daemon=True)
    t.start()

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
    return {"ws_ok": state["ws_ok"], "policy_loaded": state["policy_loaded"]}

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

@app.get("/metrics", response_class=PlainTextResponse)
def metrics():
    uptime = time.time() - START_TS
    return (
        "# HELP process_uptime_seconds Uptime seconds\n"
        "# TYPE process_uptime_seconds gauge\n"
        f"process_uptime_seconds {uptime:.2f}\n"
        "# HELP attach_sltp_p95_ms Target SLO placeholder\n"
        "# TYPE attach_sltp_p95_ms gauge\n"
        "attach_sltp_p95_ms 300\n"
    )

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
    return {"ok": True, "policy_mtime": policy_mgr.mtime}

# Run with:
# uvicorn main_ultratop:app --host 0.0.0.0 --port ${PORT:-10000}
