# -*- coding: utf-8 -*-
from __future__ import annotations

from functools import lru_cache
from base64 import b64encode  # for HTTP Signatures digest/signature

import os
import json
import time
import hmac
import re
import hashlib
import secrets
import logging
import traceback
import inspect
import asyncio
import threading
import math
from contextlib import suppress
from typing import Any, Dict, List, Optional, Callable, Tuple, Union

# --- soft shim so routes.position_ops can import even if utils.anti_replay is missing ---
import sys, types  # noqa: E402
if "utils.anti_replay" not in sys.modules:
    _m = types.ModuleType("utils.anti_replay")
    def verify_request(ts_header: Optional[str], nonce_header: Optional[str], signature_header: Optional[str],
                       route: str, body: Any, require_signature: bool = False) -> Tuple[bool, str]:
        # permissive default; real verification lives in utils.anti_replay if present
        return True, "ok"
    _m.verify_request = verify_request  # type: ignore[attr-defined]
    sys.modules["utils.anti_replay"] = _m
# ----------------------------------------------------------------------------------------

# --- soft shim for utils.idempotency.idem_for_request (if missing keep permissive) ---
try:
    from utils.idempotency import idem_for_request  # type: ignore
except Exception:
    async def idem_for_request(body: bytes, headers: Dict[str, str], extra: Optional[Dict[str, Any]] = None) -> bool:  # type: ignore
        return True
# ----------------------------------------------------------------------------------------

import httpx
from fastapi import FastAPI, Request, HTTPException, Body, Query, APIRouter, Depends
from fastapi.responses import JSONResponse, PlainTextResponse, HTMLResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import Response as StarletteResponse

# ==================== Logging ====================
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("algogpt.main")

# ====== Metrics counters integration ======
try:
    from utils.metrics_tracker import (  # type: ignore
        inc_approve_ok, inc_approve_fail, inc_reject,
        inc_scan_eval, inc_scan_passed, inc_scan_blocked,
        inc_approvals_created,
        set_last_entry_score, set_last_slip_estimate_bps,
    )
    # Stage 6 metrics:
    from utils.metrics_tracker import inc_time_stop_keep, inc_time_stop_move_be, inc_struct_sl_applied  # type: ignore
except Exception:
    def inc_approve_ok():  # type: ignore
        pass
    def inc_approve_fail():  # type: ignore
        pass
    def inc_reject():  # type: ignore
        pass
    def inc_scan_eval():  # type: ignore
        pass
    def inc_scan_passed():  # type: ignore
        pass
    def inc_scan_blocked():  # type: ignore
        pass
    def inc_approvals_created():  # type: ignore
        pass
    def set_last_entry_score(_v: float):  # type: ignore
        pass
    def set_last_slip_estimate_bps(_v: float):  # type: ignore
        pass
    # Stage 6 metrics fallbacks:
    def inc_time_stop_keep():  # type: ignore
        pass
    def inc_time_stop_move_be():  # type: ignore
        pass
    def inc_struct_sl_applied():  # type: ignore
        pass

# (NEW) optional histogram for time-to-TP1
try:
    from utils.metrics_tracker import observe_time_to_tp1  # type: ignore
except Exception:
    def observe_time_to_tp1(_v: float):  # type: ignore
        pass

# === Checklist (עם נפילה רכה) ===
try:
    from utils.pretrade_checklist import compute_pretrade_score, estimate_impact_slip_bps  # type: ignore
except Exception:
    compute_pretrade_score = None  # type: ignore
    def estimate_impact_slip_bps(spread_pct: float, atr_pct: float, notional_usdt: float, *, max_bps: float = 25.0) -> float:  # type: ignore
        return 0.0

# Exec-decider (שלב 3) – אופציונלי
try:
    from utils.exec_decider import decide_execution_mode  # type: ignore
except Exception:
    decide_execution_mode = None  # type: ignore

# ==================== Inline safe defaults ====================
_inline_env_defaults: Dict[str, str] = {
    "GUARD_SL_GRACE_SEC": "2",
    "ORD_VERIFY_TIMEOUT_MS": "800",
    "ORD_CANCEL_STRATEGY": "MINIMAL",
    "SL_MONOTONIC": "1",
    "BE_BUFFER_USDT": "0.03",
    "ATR_UPDATE_COOLDOWN_SEC": "20",
    "ATR_MIN_DELTA": "0.02",
    "COALESCE_WINDOW_MS": "1500",
    "RETRY_MAX": "3",
    "RETRY_BASE_MS": "500",
    "RETRY_JITTER": "1",
    "REST_COOLDOWN_SEC": "6",
    "TP_MAX_LADDERS": "4",
    "ENABLE_INDICATOR_EXIT": "1",
    "ADX_MIN": "18",
    "NO_PROGRESS_TIMEOUT_MIN": "30",
    "DAILY_LOSS_CAP_USDT": "150",
    "KILL_ON_CAP": "1",
    "PRICE_PROTECT": "1",
    "USE_WS": "1",
    "WS_KEEPALIVE_SEC": "25",
    # --- NEW: Signed-POST timestamp enforcement knobs (default permissive) ---
    "SIG_TS_ENFORCE": "0",
    "SIG_TS_SKEW_SEC": "900",
}
for _k, _v in _inline_env_defaults.items():
    os.environ.setdefault(_k, _v)

# ========= Notification policy =========
ONLY_TRADE_NOTIFICATIONS = os.getenv("ONLY_TRADE_NOTIFICATIONS", "1").lower() in ("1", "true", "yes", "on")
STARTUP_NOTIFY_ENABLE = os.getenv("STARTUP_NOTIFY_ENABLE", "0").lower() in ("1", "true", "yes", "on")
HEALTH_TP1_ENABLE = os.getenv("HEALTH_TP1_ENABLE", "0").lower() in ("1", "true", "yes", "on")

# ========= Auto ranges defaults (lev/budget) =========
AUTO_LEV_MIN = int(os.getenv("AUTO_LEV_MIN", "20") or 20)
AUTO_LEV_MAX = int(os.getenv("AUTO_LEV_MAX", "35") or 35)
AUTO_BUDGET_MIN = float(os.getenv("AUTO_BUDGET_MIN", "100") or 100.0)
AUTO_BUDGET_MAX = float(os.getenv("AUTO_BUDGET_MAX", "200") or 200.0)

# ========= Real-time trailing manager (new) =========
TRAIL_RT_ENABLE = os.getenv("TRAIL_RT_ENABLE", "1").lower() in ("1", "true", "yes", "on")
TRAIL_RT_INTERVAL_SEC = int(os.getenv("TRAIL_RT_INTERVAL_SEC", "20") or 20)
TRAIL_RT_ATR_MULT = float(os.getenv("TRAIL_RT_ATR_MULT", "1.6") or 1.6)
TRAIL_RT_MIN_CALLBACK = float(os.getenv("TRAIL_RT_MIN_CALLBACK", "0.1") or 0.1)   # %
TRAIL_RT_MAX_CALLBACK = float(os.getenv("TRAIL_RT_MAX_CALLBACK", "5.0") or 5.0)   # %
TRAIL_RT_PRICE_SRC = os.getenv("TRAIL_RT_PRICE_SRC", "MARK_PRICE").upper()       # MARK_PRICE / CONTRACT_PRICE / LAST_PRICE
TRAIL_RT_MAX_SYMBOLS = int(os.getenv("TRAIL_RT_MAX_SYMBOLS", "30") or 30)
TRAIL_RT_ADJUST_THRESHOLD = float(os.getenv("TRAIL_RT_ADJUST_THRESHOLD", "0.2") or 0.2)  # % diff required to re-place
TRAIL_RT_WATCH = [s.strip().upper() for s in (os.getenv("TRAIL_RT_WATCHLIST", "") or "").split(",") if s.strip()]

# ===== NEW knobs from request =====
IDEM_TTL_SEC = int(os.getenv("IDEM_TTL_SEC", os.getenv("TG_COOLDOWN_SEC", "60")) or 60)
USE_REDIS_IDEM = os.getenv("USE_REDIS_IDEM", "0").lower() in ("1", "true", "yes", "on")
TRAIL_PAUSE_WINDOWS = (os.getenv("TRAIL_PAUSE_WINDOWS", "") or "").strip()   # e.g. "22:00-02:00Z,11:30-12:00Z"
AUTO_TRAIL_ADX_MIN = float(os.getenv("AUTO_TRAIL_ADX_MIN", "0") or 0.0)
AUTO_TRAIL_ATRPCT_MAX = float(os.getenv("AUTO_TRAIL_ATRPCT_MAX", "0") or 0.0)

# === תחזוקת TP (imports + ENV) ===
try:
    from utils.tp_helper import (  # type: ignore
        maybe_merge_close_tps, maybe_rearm_on_bounce, anti_stale_nudge, manage_once_place_all
    )
except Exception:
    maybe_merge_close_tps = maybe_rearm_on_bounce = anti_stale_nudge = None  # type: ignore
    manage_once_place_all = None  # type: ignore

TP_MERGE_TICK_BAND = int(os.getenv("TP_MERGE_TICK_BAND", "1") or 1)
TP_REARM_TICK = int(os.getenv("TP_REARM_TICK", "1") or 1)
ANTI_STALE_MIN = int(os.getenv("ANTI_STALE_MIN", "15") or 15)  # minutes
ANTI_STALE_NUDGE_BPS = float(os.getenv("ANTI_STALE_NUDGE_BPS", "2") or 2.0)

# ====== (NEW) Time-Stop knobs ======
TIME_STOP_MIN = int(os.getenv("TIME_STOP_MIN", "0") or 0)
TIME_STOP_KEEP_PROFIT_MIN_PCT = float(os.getenv("TIME_STOP_KEEP_PROFIT_MIN_PCT", "0") or 0.0)
try:
    from utils.time_stop import should_time_stop, time_stop_decision  # type: ignore
except Exception:
    should_time_stop = None  # type: ignore
    time_stop_decision = None  # type: ignore

# ==================== App & CORS ====================
APP_TITLE = os.getenv("APP_TITLE", "AlgoGPT API")
APP_VERSION = os.getenv("ALGOGPT_VERSION", "dev")
DOCS_URL = os.getenv("DOCS_URL", "/docs")
REDOC_URL = os.getenv("REDOC_URL", "/redoc")
OPENAPI_URL = os.getenv("OPENAPI_URL", "/openapi.json")

app = FastAPI(
    title=APP_TITLE,
    version=APP_VERSION,
    docs_url=DOCS_URL,
    redoc_url=REDOC_URL,
    openapi_url=OPENAPI_URL,
)

# ---- Optional include of external routers if available (prevents 404 on known modules) ----
with suppress(Exception):
    from routes import manager as _routes_manager  # type: ignore
    if getattr(_routes_manager, "router", None):
        app.include_router(_routes_manager.router)
with suppress(Exception):
    from routes import position_ops as _routes_position_ops  # type: ignore
    if getattr(_routes_position_ops, "router", None):
        app.include_router(_routes_position_ops.router)
with suppress(Exception):
    from routes import ops_ui as _routes_ops_ui  # type: ignore
    if getattr(_routes_ops_ui, "router", None):
        app.include_router(_routes_ops_ui.router)

# ---- Auto-discovery of all other routes.* modules (smart & dynamic) ----
ROUTES_AUTOLOAD = os.getenv("ROUTES_AUTOLOAD", "1").lower() in ("1","true","yes","on")
ROUTES_AUTOLOAD_MODE = (os.getenv("ROUTES_AUTOLOAD_MODE") or "eager").strip().lower()  # eager | background

def _routes_autoload_now():
    try:
        from utils.routes_autoload import autoload_routes  # type: ignore
    except Exception as e:
        logger.warning("routes_autoload: loader missing (%s) — skipping", e)
        return
    try:
        # You can narrow with envs: ROUTES_ALLOW, ROUTES_DENY, ROUTES_VERBOSE
        autoload_routes(app, package="routes")
        logger.info("routes_autoload: completed")
    except Exception as e:
        logger.warning("routes_autoload: failed: %s", e)

# ============= Public feed fallbacks (no-404) =============
def _route_exists(path: str, method: str = "GET") -> bool:
    try:
        for r in app.routes:
            p = getattr(r, "path", "")
            m = getattr(r, "methods", set()) or set()
            if p == path and method.upper() in m:
                return True
    except Exception:
        pass
    return False

def _fake_topk(limit: int = 10) -> List[Dict[str, Any]]:
    syms = WATCHLIST or ["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","NEARUSDT"]
    now = int(time.time())
    out: List[Dict[str, Any]] = []
    for i, s in enumerate(syms[:max(1, limit)]):
        out.append({"symbol": s, "score": round(9.5 - i*0.3, 2), "side": ("BUY" if i % 2 == 0 else "SELL"), "ts": now})
    return out

async def _scan_public_topk_fallback(limit: int = 10):
    data = _fake_topk(limit)
    return {"ok": True, "count": len(data), "data": data}

async def _scan_public_now_fallback(symbols: Optional[str] = None):
    want = [s.strip().upper() for s in (symbols or "").split(",") if s.strip()]
    data = _fake_topk(limit=5)
    if want:
        data = [d for d in data if d["symbol"] in want]
    return {"ok": True, "data": data}

def _ensure_public_fallbacks() -> None:
    try:
        if not _route_exists("/scan/public-topk", "GET"):
            app.add_api_route("/scan/public-topk", _scan_public_topk_fallback, methods=["GET"], tags=["public"])
        if not _route_exists("/scan/public-now", "GET"):
            app.add_api_route("/scan/public-now", _scan_public_now_fallback, methods=["GET"], tags=["public"])
        if not _route_exists("/topk", "GET"):
            app.add_api_route("/topk", _scan_public_topk_fallback, methods=["GET"], tags=["public"])
    except Exception as e:
        logger.warning("public_fallbacks_add_failed: %s", e)

# (NEW) In-memory timing trackers
app.state.pos_open_ts = getattr(app.state, "pos_open_ts", {})
app.state.tp1_hit_ts = getattr(app.state, "tp1_hit_ts", {})

# ===== UltraTop integration (optional) =====
ULTRATOP_MODE = os.getenv("ULTRATOP_MODE", "noop").lower()
ULTRATOP_PREFIX = os.getenv("ULTRATOP_PREFIX", "/ultra")
try:
    from main_ultratop import setup_ultratop  # type: ignore
    if ULTRATOP_MODE in ("mount", "embed", "attach"):
        setup_ultratop(app, prefix=ULTRATOP_PREFIX)
        logger.info("UltraTop mounted at %s (mode=%s)", ULTRATOP_PREFIX, ULTRATOP_MODE)
    else:
        logger.info("UltraTop not mounted (mode=%s)", ULTRATOP_MODE)
except Exception as e:
    logger.warning("UltraTop not mounted: %s", e)

# ---------- Safe HEAD & /readyz ----------
@app.middleware("http")
async def _head_compat_and_soft_readyz(request: Request, call_next):
    if request.url.path == "/readyz":
        return PlainTextResponse("ok", status_code=200)
    if request.method == "HEAD":
        scope_copy = dict(request.scope)
        scope_copy["method"] = "GET"
        new_req = Request(scope_copy, receive=request.receive)
        resp = await call_next(new_req)
        return StarletteResponse(status_code=resp.status_code, headers=dict(resp.headers), media_type=resp.media_type)
    return await call_next(request)

# ---------- CORS ----------
CORS_ALLOW_ORIGINS = os.getenv("CORS_ALLOW_ORIGINS", "*")
CORS_ALLOW_HEADERS = os.getenv("CORS_ALLOW_HEADERS", "*")
CORS_ALLOW_METHODS = os.getenv("CORS_ALLOW_METHODS", "*")
CORS_ALLOW_CREDENTIALS = os.getenv("CORS_ALLOW_CREDENTIALS", "0").lower() in ("1", "true", "yes", "on")

_origins_list = [o.strip() for o in CORS_ALLOW_ORIGINS.split(",")] if CORS_ALLOW_ORIGINS else ["*"]
if CORS_ALLOW_CREDENTIALS and _origins_list == ["*"]:
    strict_env = [o.strip() for o in (os.getenv("CORS_ALLOW_ORIGINS_STRICT", "")).split(",") if o.strip()]
    if strict_env:
        _origins_list = strict_env
    else:
        logger.warning("CORS: allow_credentials=True but allow_origins='*'. Consider using CORS_ALLOW_ORIGINS_STRICT.")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins_list,
    allow_credentials=CORS_ALLOW_CREDENTIALS,
    allow_methods=[m.strip() for m in CORS_ALLOW_METHODS.split(",")] if CORS_ALLOW_METHODS else ["*"],
    allow_headers=[h.strip() for h in CORS_ALLOW_HEADERS.split(",")] if CORS_ALLOW_HEADERS else ["*"],
)

# ==================== Env & helpers ====================
def _port() -> int:
    try:
        return int(os.getenv("PORT", "10000") or "10000")
    except Exception:
        return 10000

def get_internal_base() -> str:
    internal = (os.getenv("INTERNAL_BASE") or "").strip()
    if internal:
        return internal.rstrip("/")
    return f"http://127.0.0.1:{_port()}"

PUBLIC_HOST = (os.getenv("PUBLIC_HOST") or os.getenv("WEBHOOK_HOST") or "").strip().rstrip("/")
WATCHLIST = [s.strip().upper() for s in (os.getenv("WATCHLIST", "") or "").split(",") if s.strip()] or ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "NEARUSDT"]

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ADMIN_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") or os.getenv("ADMIN_CHAT_ID")
TELEGRAM_AUTO_WEBHOOK = os.getenv("TELEGRAM_AUTO_WEBHOOK", "1").lower() in ("1", "true", "yes", "on")
TELEGRAM_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()

API_BEARER_TOKEN = (os.getenv("API_BEARER_TOKEN") or os.getenv("API_TOKEN") or "").strip()
NS = os.getenv("REDIS_NAMESPACE", "ops-supervisor-web").strip() or "ops-supervisor-web"
REDIS_URL = os.getenv("REDIS_URL", "").strip()
_REQUIRE_REDIS_ENV = os.getenv("REQUIRE_REDIS", "1").lower() in ("1", "true", "yes", "on")
REQUIRE_REDIS = _REQUIRE_REDIS_ENV and bool(REDIS_URL)
CONFIRMSTORE_ENABLE = os.getenv("CONFIRMSTORE_ENABLE", "0").lower() in ("1", "true", "yes", "on") or (not REDIS_URL)

# ====== Public Cache & Rate limit config ======
PUBLIC_CACHE_MAX_AGE = int(os.getenv("PUBLIC_CACHE_MAX_AGE", "20") or "20")
PUBLIC_CACHE_PATHS = [p.strip() for p in (os.getenv("PUBLIC_CACHE_PATHS", "/scan/public-topk,/scan/public-now,/topk").split(",")) if p.strip()]
RATE_LIMIT_ENABLE = os.getenv("RATE_LIMIT_ENABLE", "1").lower() in ("1", "true", "yes", "on")
PUBLIC_TOPK_RPS = int(os.getenv("PUBLIC_TOPK_RPS", "2") or "2")
PUBLIC_TOPK_WINDOW = int(os.getenv("PUBLIC_TOPK_WINDOW", "3") or "3")
PUBLIC_NOW_RPS = int(os.getenv("PUBLIC_NOW_RPS", "2") or "2")
PUBLIC_NOW_WINDOW = int(os.getenv("PUBLIC_NOW_WINDOW", "3") or "3")

# UI knobs for root() payload
UI_POLL_MS = int(os.getenv("UI_POLL_MS", "2500") or 2500)
UI_IDLE_STOP_SEC = int(os.getenv("UI_IDLE_STOP_SEC", "3600") or 3600)

# Digest config
PUBLIC_TOPK_DIGEST_ENABLE = os.getenv("PUBLIC_TOPK_DIGEST_ENABLE", "0").lower() in ("1", "true", "yes", "on")
PUBLIC_TOPK_DIGEST_EVERY_SEC = int(os.getenv("PUBLIC_TOPK_DIGEST_EVERY_SEC", "300") or "300")
PUBLIC_TOPK_DIGEST_K = int(os.getenv("PUBLIC_TOPK_DIGEST_K", "5") or "5")
PUBLIC_TOPK_DIGEST_MIN_SCORE = float(os.getenv("PUBLIC_TOPK_DIGEST_MIN_SCORE", "7.0") or 7.0)
PUBLIC_TOPK_DIGEST_REQUIRE_SIDE = os.getenv("PUBLIC_TOPK_DIGEST_REQUIRE_SIDE", "1").lower() in ("1", "true", "yes", "on")
PUBLIC_TOPK_DIGEST_INCLUDE_DETAILS = os.getenv("PUBLIC_TOPK_DIGEST_INCLUDE_DETAILS", "0").lower() in ("1", "true", "yes", "on")

OPS_TICKET_TTL_SEC = int(os.getenv("OPS_TICKET_TTL_SEC", "1800"))
ETA_SMART_ENABLE = os.getenv("ETA_SMART_ENABLE", "1").lower() in ("1", "true", "yes", "on")
ETA_VELOCITY_WINDOW = int(os.getenv("ETA_VELOCITY_WINDOW", "30"))
TP1_TAGS = [t.strip() for t in (os.getenv("TP1_TAGS", "TP1,tp1,tp_1,TAKE_PROFIT_1")).split(",") if t.strip()]

# HMAC secret (links)
HMAC_SECRET = (os.getenv("WEBHOOK_HMAC_SECRET") or os.getenv("OPS_SIGN_SECRET") or "").strip()

# HTTP/2 toggle
HTTP2_ENABLE = os.getenv("HTTP2_ENABLE", "1").lower() in ("1", "true", "yes", "on")

# ==================== Binance endpoints auto-fallback ====================
def _csv_list(env_key: str, defaults: List[str]) -> List[str]:
    raw = (os.getenv(env_key) or "").strip()
    items = [x.strip() for x in raw.split(",") if x.strip()]
    return items or defaults[:]

def _binance_default_sets(testnet: bool) -> Tuple[List[str], List[str], List[str]]:
    if testnet:
        fut_http = [
            (os.getenv("BINANCE_FUTURES_HTTP_BASE") or "").strip() or "https://testnet.binancefuture.com",
            "https://testnet.binancefuture.com",
        ]
        fut_ws = [
            (os.getenv("BINANCE_FUTURES_WS_BASE") or "").strip() or "wss://stream.testnet.binancefuture.com/ws",
            "wss://stream.testnet.binancefuture.com/ws",
        ]
        spot_http = [
            (os.getenv("BINANCE_SPOT_HTTP_BASE") or "").strip() or "https://testnet.binance.vision",
            "https://testnet.binance.vision",
        ]
    else:
        fut_http = [
            (os.getenv("BINANCE_FUTURES_HTTP_BASE") or "").strip() or "https://fapi.binance.com",
            "https://fapi.binance.com",
            "https://fstream.binance.com",
        ]
        fut_ws = [
            (os.getenv("BINANCE_FUTURES_WS_BASE") or "").strip() or "wss://fstream.binance.com/ws",
            "wss://stream.binancefuture.com/ws",
            "wss://fstream.binance.com/ws",
        ]
        spot_http = [
            (os.getenv("BINANCE_SPOT_HTTP_BASE") or "").strip() or "https://api.binance.com",
            "https://api.binance.com",
        ]
    return fut_http, fut_ws, spot_http

def _binance_candidate_sets() -> Dict[str, List[str]]:
    testnet = (os.getenv("BINANCE_TESTNET", "false").lower() in ("1", "true", "yes", "on"))
    def_fut_http, def_fut_ws, def_spot_http = _binance_default_sets(testnet)
    fut_http = _csv_list("BINANCE_HTTP_BASES_FUTURES", def_fut_http)
    fut_ws   = _csv_list("BINANCE_WS_BASES_FUTURES", def_fut_ws)
    spot_http= _csv_list("BINANCE_HTTP_BASES_SPOT", def_spot_http)
    return {"fut_http": fut_http, "fut_ws": fut_ws, "spot_http": spot_http}

_shared_client_lock = threading.Lock()

def _http2_enabled_runtime() -> bool:
    return os.getenv("HTTP2_ENABLE", "1").lower() in ("1", "true", "yes", "on")

def _get_shared_async_client() -> httpx.AsyncClient:
    cli: Optional[httpx.AsyncClient] = getattr(app.state, "shared_async_client", None)
    if cli and not cli.is_closed:
        return cli
    with _shared_client_lock:
        cli = getattr(app.state, "shared_async_client", None)
        if cli and not cli.is_closed:
            return cli
        timeout = httpx.Timeout(15.0)
        limits = httpx.Limits(
            max_connections=int(os.getenv("HTTP_MAX_CONNECTIONS", "200")),
            max_keepalive_connections=int(os.getenv("HTTP_MAX_KEEPALIVE", "50")),
        )
        cli = httpx.AsyncClient(
            timeout=timeout,
            limits=limits,
            headers={"User-Agent": f"algogpt/{APP_VERSION}"},
            http2=_http2_enabled_runtime(),
        )
        app.state.shared_async_client = cli
        return cli

async def _http_ready(base: str, *, path: str = "/fapi/v1/ping", timeout: float = 6.0) -> bool:
    try:
        cli = _get_shared_async_client()
        r = await cli.get(base.rstrip("/") + path, timeout=httpx.Timeout(timeout))
        return r.status_code == 200
    except Exception:
        return False

async def _resolve_binance_endpoints() -> None:
    cands = _binance_candidate_sets()
    chosen_fut_http = None
    for b in cands["fut_http"]:
        if await _http_ready(b, path="/fapi/v1/ping"):
            chosen_fut_http = b
            break
    chosen_spot_http = None
    for b in cands["spot_http"]:
        if await _http_ready(b, path="/api/v3/ping"):
            chosen_spot_http = b
            break
    chosen_fut_ws = cands["fut_ws"][0] if cands["fut_ws"] else None

    app.state.BINANCE_FUTURES_HTTP_BASE = (chosen_fut_http or cands["fut_http"][0]).rstrip("/")
    app.state.BINANCE_SPOT_HTTP_BASE    = (chosen_spot_http or cands["spot_http"][0]).rstrip("/")
    app.state.BINANCE_FUTURES_WS_BASE   = (chosen_fut_ws   or cands["fut_ws"][0]).rstrip("/")
    os.environ["BINANCE_FUTURES_HTTP_BASE"] = app.state.BINANCE_FUTURES_HTTP_BASE
    os.environ["BINANCE_SPOT_HTTP_BASE"]    = app.state.BINANCE_SPOT_HTTP_BASE
    os.environ["BINANCE_FUTURES_WS_BASE"]   = app.state.BINANCE_FUTURES_WS_BASE

def _fut_http() -> str:
    return getattr(app.state, "BINANCE_FUTURES_HTTP_BASE", os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")).rstrip("/")

def _spot_http() -> str:
    return getattr(app.state, "BINANCE_SPOT_HTTP_BASE", os.getenv("BINANCE_SPOT_HTTP_BASE", "https://api.binance.com")).rstrip("/")

def _fut_ws() -> str:
    return getattr(app.state, "BINANCE_FUTURES_WS_BASE", os.getenv("BINANCE_FUTURES_WS_BASE", "wss://fstream.binance.com/ws")).rstrip("/")

# ==================== Security helpers ====================
def _get_hmac_key_bytes() -> Optional[bytes]:
    cand = (
        os.getenv("API_SIGNING_SECRET")
        or os.getenv("OPS_SIGN_SECRET")
        or os.getenv("SIGNING_SECRET_HEX")
        or os.getenv("SECRET_HEX")
        or os.getenv("WEBHOOK_HMAC_SECRET")
        or ""
    ).strip()
    if not cand:
        return None
    try:
        if len(cand) == 64 and all(c in "0123456789abcdefABCDEF" for c in cand):
            return bytes.fromhex(cand)
    except Exception:
        pass
    return cand.encode("utf-8")

def _sha256_b64(data: bytes) -> str:
    return b64encode(hashlib.sha256(data).digest()).decode()

def _parse_signature_auth(h: str) -> Optional[Dict[str, Any]]:
    if not h or not h.lower().startswith("signature "):
        return None
    s = h[len("Signature "):].strip()
    parts: Dict[str, str] = {}
    for kv in re.split(r'\s*,\s*', s):
        if "=" not in kv:
            continue
        k, v = kv.split("=", 1)
        v = v.strip()
        if v.startswith('"') and v.endswith('"'):
            v = v[1:-1]
        parts[k.strip()] = v
    if not {"keyId", "algorithm", "headers", "signature"}.issubset(parts.keys()):
        return None
    return {
        "keyId": parts["keyId"],
        "algorithm": parts["algorithm"].lower(),
        "headers": [x.strip().lower() for x in parts["headers"].split() if x.strip()],
        "signature": parts["signature"],
    }

def _build_sig_string(method: str, path: str, headers_lower: Dict[str, str], headers_order: List[str]) -> str:
    lines: List[str] = []
    for hname in headers_order:
        if hname == "(request-target)":
            lines.append(f"(request-target): {method.lower()} {path}")
        else:
            val = headers_lower.get(hname, "")
            lines.append(f"{hname}: {val}")
    return "\n".join(lines)

def _verify_http_signature(request: Request, body: bytes, *, route_path: str) -> Tuple[bool, str]:
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    info = _parse_signature_auth(auth or "")
    if not info:
        return False, "missing_or_bad_authorization_signature"
    if info["algorithm"] not in ("hmac-sha256",):
        return False, "unsupported_algorithm"

    hdrs_lower = {k.lower(): v for k, v in request.headers.items()}

    # Digest / x-content-sha256
    if "digest" in hdrs_lower:
        try:
            scheme, b64v = (hdrs_lower["digest"] or "").split("=", 1)
            if scheme.strip().lower() != "sha-256":
                return False, "unsupported_digest_scheme"
            want = b64v.strip()
            got = _sha256_b64(body)
            if want != got:
                return False, "bad_digest"
        except Exception:
            return False, "bad_digest_format"
    elif "x-content-sha256" in hdrs_lower:
        want = hdrs_lower["x-content-sha256"].strip()
        got = _sha256_b64(body)
        if want != got:
            return False, "bad_x_content_sha256"

    method = request.method
    path = route_path
    try:
        sigstr = _build_sig_string(method, path, hdrs_lower, info["headers"])
    except Exception as e:
        return False, f"sig_string_build_failed:{e}"

    key = _get_hmac_key_bytes()
    if not key:
        return False, "server_signing_secret_missing"
    mac = hmac.new(key, sigstr.encode(), hashlib.sha256).digest()
    calc = b64encode(mac).decode()
    if not hmac.compare_digest(calc, info["signature"]):
        return False, "bad_signature"

    enforce_ts = os.getenv("SIG_TS_ENFORCE", "0").lower() in ("1", "true", "yes", "on")
    if enforce_ts:
        try:
            skew = int(os.getenv("SIG_TS_SKEW_SEC", "900") or 900)
            ts_raw = hdrs_lower.get("x-request-timestamp", "0")
            try:
                ts = int(float(ts_raw))
            except Exception:
                logger.debug("sig_ts:reject reason=bad_format ts_raw=%s", ts_raw)
                return False, "timestamp_bad_format"
            now = int(time.time())
            if abs(now - ts) > max(0, skew):
                logger.debug("sig_ts:reject reason=out_of_window ts=%s now=%s skew=%s delta=%s",
                             ts, now, skew, now - ts)
                return False, "timestamp_out_of_window"
        except Exception:
            return False, "timestamp_bad_format"
    return True, "ok"

def _require_not_expired(exp_val: Optional[Union[int, str]]) -> None:
    if exp_val in (None, "", 0, "0", "0.0"):
        return
    try:
        if isinstance(exp_val, (int, float)):
            exp_i = int(exp_val)
        else:
            exp_i = int(float(str(exp_val)))
    except Exception:
        raise HTTPException(status_code=401, detail="bad_exp_format")
    if exp_i < int(time.time()):
        raise HTTPException(status_code=401, detail="expired")

async def _enforce_nonce_once(request: Request) -> None:
    if os.getenv("ANTI_REPLAY_ENABLE", "0").lower() not in ("1", "true", "yes", "on"):
        return
    nonce = request.headers.get("X-Request-Nonce") or request.headers.get("x-request-nonce") or ""
    nonce = nonce.strip()
    if not nonce:
        return
    ttl = int(os.getenv("ANTI_REPLAY_NONCE_TTL_SEC", "180") or 180)
    key = f"{NS}:nonce:{hashlib.sha256(nonce.encode('utf-8')).hexdigest()}"
    r = None
    with suppress(Exception):
        r = await _get_redis_cached()
    if r:
        try:
            ok = await r.setnx(key, "1")
            if not ok:
                raise HTTPException(status_code=401, detail="nonce_replay")
            with suppress(Exception):
                await r.expire(key, ttl)
            return
        except HTTPException:
            raise
        except Exception:
            pass
    # in-memory fallback
    bucket = getattr(app.state, "_nonce_mem", None)
    if bucket is None:
        bucket = {}
        app.state._nonce_mem = bucket
    now = time.time()
    for k, ts in list(bucket.items()):
        if now - float(ts) > ttl:
            bucket.pop(k, None)
    if key in bucket:
        raise HTTPException(status_code=401, detail="nonce_replay")
    bucket[key] = now

def _sign_hex(secret_hex_or_text: str, payload: bytes) -> str:
    try:
        if len(secret_hex_or_text) == 64:
            key = bytes.fromhex(secret_hex_or_text)
        else:
            key = secret_hex_or_text.encode("utf-8")
    except ValueError:
        key = secret_hex_or_text.encode("utf-8")
    return hmac.new(key, payload, hashlib.sha256).hexdigest()

def _build_signed_link(base: str, path: str, ticket_id: str, ttl_sec: int = 600, action: Optional[str] = None) -> str:
    if not HMAC_SECRET:
        route = "/ops/ui/ticket"
        if action == "approve":
            route = "/ops/approve"
        elif action == "reject":
            route = "/ops/reject"
        sep = "&" if "?" in route else "?"
        return f"{base}{route}{sep}ticket_id={ticket_id}"
    exp = int(time.time()) + int(ttl_sec)
    to_sign = f"{path}|{ticket_id}|{exp}|{NS}".encode("utf-8")
    sig = _sign_hex(HMAC_SECRET, to_sign)
    sep = "&" if "?" in path else "?"
    return f"{base}{path}{sep}ticket_id={ticket_id}&exp={exp}&sig={sig}"

def _verify_signed_params(ticket_id: str, exp: str, sig: str, path: str) -> bool:
    if not (HMAC_SECRET and ticket_id and exp and sig):
        return False
    try:
        exp_i = int(exp)
        if exp_i < int(time.time()):
            return False
    except Exception:
        return False
    expected = _sign_hex(HMAC_SECRET, f"{path}|{ticket_id}|{exp}|{NS}".encode("utf-8"))
    return hmac.compare_digest(expected, sig)

# ==================== Simple ConfirmStore (in-memory fallback) ====================
class ConfirmStore:
    _items: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def create(cls, req: Dict[str, Any]) -> None:
        tid = str(req.get("ticket_id") or f"T_{int(time.time())}_{secrets.token_hex(3)}")
        cls._items[tid] = {"ticket_id": tid, "req": dict(req), "ts": time.time(), "approved": None}

    @classmethod
    def decide(cls, ticket_id: str, approved: bool) -> None:
        it = cls._items.get(str(ticket_id))
        if it:
            it["approved"] = bool(approved)

    @classmethod
    def pending(cls) -> List[Dict[str, Any]]:
        return [v for v in cls._items.values() if v.get("approved") is None]

    @classmethod
    def remove(cls, ticket_id: str) -> None:
        cls._items.pop(str(ticket_id), None)

# ==================== Shared HTTP and Redis ====================
try:
    import redis.asyncio as aioredis  # type: ignore
except Exception:
    aioredis = None  # type: ignore

async def _get_redis_cached():
    if not (aioredis and REDIS_URL):
        return None
    r = getattr(app.state, "redis", None)
    if r:
        return r
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    app.state.redis = r
    return r

# ==================== Security headers middleware ====================
@app.middleware("http")
async def _security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    resp.headers.setdefault("Cross-Origin-Resource-Policy", "same-site")
    resp.headers.setdefault("Permissions-Policy", "browsing-topics=()")
    try:
        _enable_coep = os.getenv("ENABLE_COEP", "0").lower() in ("1", "true", "yes", "on")
    except Exception:
        _enable_coep = False
    if _enable_coep:
        resp.headers.setdefault("Cross-Origin-Embedder-Policy", "require-corp")
    resp.headers.setdefault("X-XSS-Protection", "0")
    # CSP (נשלט ENV)
    try:
        if os.getenv("ENABLE_CSP", "0").lower() in ("1", "true", "yes", "on"):
            pol = os.getenv("CSP_POLICY", "default-src 'none'")
            resp.headers.setdefault("Content-Security-Policy", pol)
    except Exception:
        pass
    if os.getenv("ENABLE_HSTS", "0").lower() in ("1", "true", "yes", "on"):
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains; preload")
    return resp

# ==================== Helpers for guards & RL logs ====================
def _client_ip(request: Request) -> str:
    return request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or (request.client.host if request.client else "0.0.0.0")

def _env_list(s: Optional[str]) -> List[str]:
    return [x.strip() for x in (s or "").split(",") if x and x.strip()]

def _path_matches(path: str, exact: List[str], prefixes: List[str]) -> bool:
    if any(path == e for e in exact):
        return True
    if any(path.startswith(pr) for pr in prefixes if pr):
        return True
    return False

# ==================== Path Protection (ENV-driven) ====================
@app.middleware("http")
async def _path_protection_guard(request: Request, call_next):
    """
    כיבוד ENV ל-public/protected:
      - SECURITY_PUBLIC_PATHS: רשימת נתיבים מדויקים (/, /readyz, ...)
      - SECURITY_PUBLIC_PREFIXES: רשימת פריפיקסים ציבוריים (/public, /static ...)
      - SECURITY_PROTECTED_PATHS: רשימת נתיבים מוגנים במדויק
      - ROUTES_PROTECTED_PREFIXES: רשימת פריפיקסים מוגנים (/ops, /admin ...)
    כללים:
      1. אם path ב-public (מדויק/פריפיקס) => מעבר חופשי.
      2. אחרת אם path ב-protected (מדויק/פריפיקס) => דרוש Bearer.
      3. אחרת => ברירת מחדל: אין שינוי (הראוטים עצמם יגנו אם צריך).
    """
    try:
        path = request.url.path
        pub_exact = _env_list(os.getenv("SECURITY_PUBLIC_PATHS"))
        pub_prefx = _env_list(os.getenv("SECURITY_PUBLIC_PREFIXES"))
        prot_exact = _env_list(os.getenv("SECURITY_PROTECTED_PATHS"))
        prot_prefx = _env_list(os.getenv("ROUTES_PROTECTED_PREFIXES"))

        # כלל public קודם (override)
        if _path_matches(path, pub_exact, pub_prefx):
            return await call_next(request)

        # אם מוגן – דרוש Bearer
        if _path_matches(path, prot_exact, prot_prefx):
            try:
                _require_bearer(request)
            except HTTPException:
                logger.debug("path_protection:401 path=%s ip=%s", path, _client_ip(request))
                raise
            return await call_next(request)
    except Exception as e:
        # לא לחסום תנועה על תקלה בשכבת ההגנה – נמשיך כרגיל ונרשום אזהרה
        logger.warning("path_protection_guard_failed: %s", e)
    return await call_next(request)

# ==================== Public Rate Limit middleware ====================
async def _rl_hit(path_key: str, window_sec: int, limit: int, ip: str) -> bool:
    key = f"{NS}:rl:{path_key}:{ip}"
    try:
        r = await _get_redis_cached()
        if r:
            pipe = r.pipeline()
            pipe.incr(key, 1)
            pipe.ttl(key)
            cur, ttl = await pipe.execute()
            if int(ttl) == -1:
                await r.expire(key, window_sec)
            return int(cur) > int(limit)
    except Exception as e:
        logger.debug("rate_limit_redis_fallback: %s", e)

    # in-memory fallback
    bucket = getattr(app.state, "rl_mem", None)
    if bucket is None:
        bucket = {}
        app.state.rlm_epoch = time.time()
        app.state.rl_mem = bucket
    now = time.time()
    rec = bucket.get(key)
    if not rec or (now - rec["start"]) >= window_sec:
        bucket[key] = {"start": now, "count": 1}
        return False
    rec["count"] += 1  # type: ignore[index]
    return rec["count"] > int(limit)  # type: ignore[index]

@app.middleware("http")
async def _public_rate_limit(request: Request, call_next):
    if not RATE_LIMIT_ENABLE:
        return await call_next(request)
    p = request.url.path
    if request.method.upper() != "GET":
        return await call_next(request)
    ip = _client_ip(request)
    rules = {
        "/scan/public-topk": (PUBLIC_TOPK_RPS, PUBLIC_TOPK_WINDOW),
        "/scan/public-now": (PUBLIC_NOW_RPS, PUBLIC_NOW_WINDOW),
        "/topk": (PUBLIC_TOPK_RPS, PUBLIC_TOPK_WINDOW),
    }
    for k, (rps, win) in rules.items():
        if p.startswith(k):
            over = await _rl_hit(k, int(win), int(rps) * int(win), ip)
            if over:
                logger.debug("rate_limit:429 path=%s ip=%s win=%ss limit=%s", k, ip, win, int(rps) * int(win))
                return JSONResponse(
                    {"ok": False, "error": "rate_limited"},
                    status_code=429,
                    headers={"Retry-After": str(win)},
                )
            break
    return await call_next(request)

# ==================== Public Cache/Etag middleware ====================
def _should_public_cache(path: str) -> bool:
    paths_cfg = (os.getenv("PUBLIC_CACHE_PATHS") or "").split(",") if os.getenv("PUBLIC_CACHE_PATHS") else []
    for prefix in paths_cfg:
        if prefix and path.startswith(prefix.strip()):
            return True
    for prefix in ["/scan/public-topk", "/scan/public-now", "/topk"]:
        if path.startswith(prefix):
            return True
    return False

@app.middleware("http")
async def _public_cache_etag(request: Request, call_next):
    if request.method.upper() != "GET" or not _should_public_cache(request.url.path):
        try:
            return await call_next(request)
        except RuntimeError as e:
            if "No response returned" in str(e):
                return PlainTextResponse("", status_code=204)
            raise
    try:
        resp: Response = await call_next(request)
    except RuntimeError as e:
        if "No response returned" in str(e):
            return PlainTextResponse("", status_code=204)
        raise
    try:
        if int(getattr(resp, "status_code", 200)) >= 400:
            return resp
        hdrs_lower = {k.lower() for k in resp.headers.keys()}
        if "cache-control" not in hdrs_lower:
            resp.headers["Cache-Control"] = f"public, max-age={PUBLIC_CACHE_MAX_AGE}"
        body = b""
        with suppress(Exception):
            body = resp.body if getattr(resp, "body", None) else b""
        if not body:
            if "vary" not in hdrs_lower:
                resp.headers["Vary"] = "If-None-Match"
            elif "if-none-match" not in resp.headers.get("Vary", "").lower():
                resp.headers["Vary"] = resp.headers["Vary"] + ", If-None-Match"
            return resp
        try:
            hasher = hashlib.md5()
            hasher.update(bytes(body))
            etag_val = hasher.hexdigest()
        except Exception:
            etag_val = hashlib.md5(body if isinstance(body, (bytes, bytearray)) else bytes(body)).hexdigest()
        etag = '"' + etag_val + '"'
        if "etag" not in hdrs_lower:
            resp.headers["ETag"] = etag
        if "vary" not in hdrs_lower:
            resp.headers["Vary"] = "If-None-Match"
        elif "if-none-match" not in resp.headers.get("Vary", "").lower():
            resp.headers["Vary"] = resp.headers["Vary"] + ", If-None-Match"
        inm = request.headers.get("If-None-Match")
        if inm and inm == etag and resp.status_code == 200:
            fresh = Response(status_code=304)
            fresh.headers["Cache-Control"] = resp.headers.get("Cache-Control", f"public, max-age={PUBLIC_CACHE_MAX_AGE}")
            fresh.headers["ETag"] = etag
            fresh.headers["Vary"] = resp.headers.get("Vary", "If-None-Match")
            logger.debug("etag:304 path=%s etag=%s", request.url.path, etag)
            return fresh
    except Exception:
        return resp
    return resp

# ==================== Telegram helpers ====================
def _md_html(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

async def _send_telegram_html(text: str, approve_url: Optional[str] = None,
                              reject_url: Optional[str] = None, preview_url: Optional[str] = None,
                              manage_url: Optional[str] = None) -> Dict[str, Any]:
    if os.getenv("TG_SILENT", "0").lower() in ("1", "true", "yes", "on"):
        return {"ok": True, "skipped": True, "reason": "silent_mode"}

    if USE_REDIS_IDEM and IDEM_TTL_SEC > 0 and (aioredis and REDIS_URL):
        try:
            r = await _get_redis_cached()
            if r:
                key_payload = json.dumps({"t": text, "a": approve_url, "r": reject_url, "p": preview_url, "m": manage_url}, ensure_ascii=False, separators=(",", ":"))
                idem_key = f"{NS}:idem:tg:{hashlib.md5(key_payload.encode('utf-8')).hexdigest()}"
                ok = await r.setnx(idem_key, "1")
                if not ok:
                    return {"ok": True, "skipped": True, "reason": "idem_duplicate"}
                with suppress(Exception):
                    await r.expire(idem_key, int(IDEM_TTL_SEC))
        except Exception as e:
            logger.debug("telegram_idem_warning: %s", e)

    if not TELEGRAM_BOT_TOKEN or not ADMIN_CHAT_ID:
        return {"ok": False, "skipped": True}
    try:
        chat_id: Any = int(ADMIN_CHAT_ID) if str(ADMIN_CHAT_ID).isdigit() else ADMIN_CHAT_ID
    except Exception:
        chat_id = ADMIN_CHAT_ID
    payload: Dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if approve_url or reject_url or preview_url or manage_url:
        row: List[Dict[str, Any]] = []
        if preview_url:
            row.append({"text": "👁 Preview", "url": preview_url})
        if manage_url:
            row.append({"text": "⚡ Manage Now", "url": manage_url})
        if approve_url:
            row.append({"text": "✅ Approve", "url": approve_url})
        if reject_url:
            row.append({"text": "❌ Reject", "url": reject_url})
        payload["reply_markup"] = {"inline_keyboard": [row]}

    cli = _get_shared_async_client()
    for attempt in range(3):
        try:
            r = await cli.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json=payload,
                timeout=httpx.Timeout(10.0),
            )
            data = {}
            with suppress(Exception):
                data = r.json()
            if r.status_code < 400 and data.get("ok"):
                return {"ok": True, "status": r.status_code, "result": data.get("result")}
            if r.status_code in (429, 500, 502, 503, 504):
                ra = 0.0
                with suppress(Exception):
                    ra = float(r.headers.get("Retry-After", "0") or 0)
                await asyncio.sleep(max(ra, 0.6 * (attempt + 1)))
                continue
            return {"ok": False, "status": r.status_code, "text_raw": r.text}
        except Exception as e:
            if attempt == 2:
                return {"ok": False, "error": str(e)}
            await asyncio.sleep(0.6 * (attempt + 1))
    return {"ok": False, "error": "telegram_send_exhausted"}

async def _ensure_telegram_webhook() -> None:
    if not TELEGRAM_AUTO_WEBHOOK:
        return
    bot = TELEGRAM_BOT_TOKEN
    secret = TELEGRAM_WEBHOOK_SECRET
    host = PUBLIC_HOST
    if not (bot and secret and host):
        return
    set_url = f"https://api.telegram.org/bot{bot}/setWebhook"
    payload = {
        "url": f"{host}/telegram/webhook",
        "secret_token": secret,
        "drop_pending_updates": True,
        "max_connections": 40,
    }
    try:
        cli = _get_shared_async_client()
        r = await cli.post(set_url, json=payload, timeout=httpx.Timeout(15.0))
        ok = False
        with suppress(Exception):
            ok = (r.status_code == 200) and (r.json().get("ok", False))
        logger.info("telegram.setWebhook: %s", "ok" if ok else f"bad_status={r.status_code}")
    except Exception as e:
        logger.info("telegram.setWebhook.failed: %s", e)

# ==================== Price helpers ====================
async def get_last_price_async(symbol: str) -> Optional[float]:
    sym = symbol.upper()
    with suppress(Exception):
        from utils.binance_client import get_price  # type: ignore
        val = await asyncio.to_thread(get_price, sym)
        if val:
            v = float(val)
            if v > 0:
                return v
    for base, path in ((_fut_http(), "/fapi/v1/ticker/price"), (_spot_http(), "/api/v3/ticker/price")):
        try:
            cli = _get_shared_async_client()
            r = await cli.get(base + path, params={"symbol": sym}, timeout=httpx.Timeout(10.0))
            if r.status_code == 200:
                data = r.json()
                p = float(data.get("price"))
                if p > 0:
                    return p
        except Exception:
            continue
    with suppress(Exception):
        from binance.client import Client  # type: ignore
        api_key = os.getenv("BINANCE_API_KEY", "").strip()
        api_sec = os.getenv("BINANCE_API_SECRET", "").strip()
        if api_key and api_sec:
            def _sdk_call() -> Optional[float]:
                try:
                    cli_ = Client(api_key, api_sec)
                    info = cli_.futures_symbol_ticker(symbol=sym)
                    if info and "price" in info:
                        return float(info["price"])
                except Exception:
                    return None
                return None
            v = await asyncio.to_thread(_sdk_call)
            if v and v > 0:
                return v
    return None

# >>> KL HTTP HELPER
async def _fetch_klines_http(symbol: str, interval: str = "15m", limit: int = 120) -> List[List[Any]]:
    sym = symbol.upper()
    if not sym.endswith("USDT"):
        sym += "USDT"
    url = _fut_http() + "/fapi/v1/klines"
    try:
        cli = _get_shared_async_client()
        r = await cli.get(url, params={"symbol": sym, "interval": interval, "limit": int(limit)}, timeout=httpx.Timeout(10.0))
        if r.status_code == 200:
            data = r.json()
            return data if isinstance(data, list) else []
    except Exception:
        pass
    return []

# ==================== Misc helpers ====================
_MODE_RX = re.compile(r"\[mode:\s*(MARKET|HYBRID|AUTO)\s*\]", flags=re.I)
def _parse_mode(note: Optional[str]) -> Optional[str]:
    if not note:
        return None
    m = _MODE_RX.search(str(note))
    return m.group(1).upper() if m else None

def _filter_kwargs_for_callable(fn: Callable[..., Any], kwargs: Dict[str, Any]) -> Dict[str, Any]:
    try:
        sig = inspect.signature(fn)
        allowed = set(sig.parameters.keys())
        return {k: v for k, v in kwargs.items() if k in allowed}
    except Exception:
        bad = {"tp_kind", "sl_kind", "entry_kind", "entry_offset", "tp_offset", "sl_offset"}
        return {k: v for k, v in kwargs.items() if k not in bad}

def _is_code_4061(err: Union[Exception, str]) -> bool:
    s = str(err)
    return "code=-4061" in s or "position side does not match" in s.lower()

def _align_position_mode(client) -> None:
    mode_override = (os.getenv("POSITION_MODE_OVERRIDE", "") or "").strip().lower()
    with suppress(Exception):
        if mode_override in ("hedge", "dual", "dual_side", "dual_side_position", "dualposition"):
            client.futures_change_position_mode(dualSidePosition="true")
        elif mode_override in ("oneway", "one_way", "single", "single_side", "oneside"):
            client.futures_change_position_mode(dualSidePosition="false")

# ==================== Order ID helper ====================
try:
    from utils.order_ids import build_client_order_id  # type: ignore
except Exception:
    def _coid_fit_local(s: str, limit: int = 36) -> str:
        if len(s) <= limit:
            return s
        h = hashlib.md5(s.encode("utf-8")).hexdigest()[:6]
        return f"{s[:limit - (len(h) + 1)]}_{h}"
    def build_client_order_id(symbol: str, side: str, role: str = "ENTRY", extra: Optional[str] = None) -> str:
        prefix = (os.getenv("ORDER_ID_PREFIX") or "ALG").strip() or "ALG"
        sym = str(symbol).upper()
        sd = str(side).upper()
        rl = str(role).upper().replace("@", "_")
        ts = str(int(time.time() * 1000))
        base = "-".join([prefix, sym, sd, rl, ts] + ([str(extra)] if extra else []))
        return _coid_fit_local(base, 36)

# ==================== Execute trade helpers ====================
def _bn_round(value: float, step: float) -> float:
    if step <= 0:
        return value
    return math.floor(value / step) * step

def _round_tick_dir(value: float, step: float, direction: str) -> float:
    if step <= 0:
        return value
    q = value / step
    if direction.lower().startswith("up"):
        return math.ceil(q) * step
    return math.floor(q) * step

def _get_exchange_info_cached(client, *, ttl_sec: int = 300) -> Dict[str, Any]:
    now = time.time()
    cache_key = "futures_exchange_info"
    ts_key = "futures_exchange_info_ts"
    ex_cached = getattr(app.state, cache_key, None)
    ex_ts = getattr(app.state, ts_key, 0.0)
    if ex_cached and (now - float(ex_ts)) < ttl_sec:
        return ex_cached
    try:
        ex = client.futures_exchange_info()
        setattr(app.state, cache_key, ex or {})
        setattr(app.state, ts_key, now)
        return ex or {}
    except Exception:
        return ex_cached or {}

def _get_filters(client, symbol: str) -> Tuple[float, float]:
    tick = 0.1
    step = 0.001
    try:
        ex = _get_exchange_info_cached(client)
        for s in ex.get("symbols", []):
            if s.get("symbol") == symbol:
                for f in s.get("filters", []):
                    if f.get("filterType") == "PRICE_FILTER":
                        with suppress(Exception):
                            tick = float(f.get("tickSize"))
                    if f.get("filterType") == "LOT_SIZE":
                        with suppress(Exception):
                            step = float(f.get("stepSize"))
                break
    except Exception:
        pass
    return tick, step

def _round_to_lot_size(client, symbol: str, qty: float) -> float:
    try:
        _tick, step = _get_filters(client, symbol)
        if step and step > 0:
            q = math.floor(float(qty) / float(step)) * float(step)
            dec = max(0, min(8, str(step)[::-1].find('.')))
            return float(f"{q:.{dec}f}")
        return float(qty)
    except Exception:
        return float(qty)

async def _execute_trade(ticket: Dict[str, Any]) -> Dict[str, Any]:
    with suppress(Exception):
        from utils.trade_executor import place_futures_market  # type: ignore
        return await place_futures_market(ticket)
    try:
        from binance.client import Client  # type: ignore
    except Exception as e:
        return {"ok": False, "entered": False, "error": "binance_client_import_failed", "detail": str(e)}
    try:
        api_key = os.getenv("BINANCE_API_KEY", "").strip()
        api_sec = os.getenv("BINANCE_API_SECRET", "").strip()
        if not api_key or not api_sec:
            return {"ok": False, "entered": False, "error": "binance_keys_missing"}
        client = Client(api_key, api_sec)
        _align_position_mode(client)
        symbol = str(ticket.get("symbol", "")).upper()
        side = str(ticket.get("side", "")).upper()
        qty = float(ticket.get("qty") or ticket.get("quantity") or 0)
        leverage = int(ticket.get("leverage") or ticket.get("lev") or 1)
        if not (symbol and side in ("BUY", "SELL") and qty > 0 and leverage > 0):
            return {"ok": False, "entered": False, "error": "bad_ticket_params"}
        with suppress(Exception):
            client.futures_change_leverage(symbol=symbol, leverage=leverage)
        try:
            if qty > 0:
                qty = _round_to_lot_size(client, symbol, qty)
        except Exception:
            pass
        base_kwargs: Dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": qty,
            "newClientOrderId": build_client_order_id(symbol, side, role="ENTRY"),
        }
        pos_side_supplied = str(ticket.get("position_side") or ticket.get("positionSide") or "").upper()
        attempt_order = dict(base_kwargs)
        if pos_side_supplied in ("LONG", "SHORT"):
            attempt_order["positionSide"] = pos_side_supplied
        try:
            order = client.futures_create_order(**attempt_order)
            return {"ok": True, "entered": True, "exchange": "binance_futures", "order": order}
        except Exception as e1:
            if not _is_code_4061(e1):
                raise
            try:
                order = client.futures_create_order(**base_kwargs)
                return {"ok": True, "entered": True, "exchange": "binance_futures", "order": order, "retry": "no_positionSide"}
            except Exception as e2:
                try:
                    retry2_kwargs = dict(base_kwargs)
                    retry2_kwargs["positionSide"] = "LONG" if side == "BUY" else "SHORT"
                    order = client.futures_create_order(**retry2_kwargs)
                    return {"ok": True, "entered": True, "exchange": "binance_futures", "order": order, "retry": "derived_positionSide"}
                except Exception as e3:
                    return {"ok": False, "entered": False, "error": "order_failed", "detail": str(e3), "first_error": str(e1), "second_error": str(e2)}
    except Exception as e:
        return {"ok": False, "entered": False, "error": "order_failed", "detail": str(e)}

async def _execute_trade_armed(ticket: Dict[str, Any]) -> Dict[str, Any]:
    execute_trade_live = None
    with suppress(Exception):
        from utils.trade_executor import execute_trade_live as _x  # type: ignore
        execute_trade_live = _x
    if execute_trade_live is None:
        with suppress(Exception):
            from app.trade_executor import execute_trade_live as _x  # type: ignore
            execute_trade_live = _x
    if execute_trade_live is None:
        return {"ok": False, "entered": False, "error": "execute_trade_live_missing"}
    symbol = (ticket.get("symbol") or "").upper()
    side = (ticket.get("side") or "").upper()
    qty = float(ticket.get("qty") or ticket.get("quantity") or 0)
    leverage = int(ticket.get("leverage") or ticket.get("lev") or 0)
    raw_ps = str(ticket.get("position_side") or ticket.get("positionSide") or "").upper()
    pos_side = raw_ps if raw_ps in ("LONG", "SHORT") else ("LONG" if side == "BUY" else "SHORT")
    tps_raw = [ticket.get("tp1"), ticket.get("tp2"), ticket.get("tp3")]
    tp_targets = [float(x) for x in tps_raw if x is not None and str(x) not in ("0", "0.0") and float(x) > 0]
    sl_targets = [float(ticket.get("sl"))] if (ticket.get("sl") not in (None, 0, "0", "0.0")) else None
    if not (symbol and side in ("BUY", "SELL") and qty > 0 and leverage > 0):
        return {"ok": False, "entered": False, "error": "bad_ticket_params"}
    try:
        from binance.client import Client  # type: ignore
        api_key = os.getenv("BINANCE_API_KEY", "").strip()
        api_sec = os.getenv("BINANCE_API_SECRET", "").strip()
        if api_key and api_sec and leverage > 0 and symbol:
            cli_ = Client(api_key, api_sec)
            _align_position_mode(cli_)
            with suppress(Exception):
                cli_.futures_change_leverage(symbol=symbol, leverage=leverage)
            with suppress(Exception):
                if qty > 0:
                    qty = _round_to_lot_size(cli_, symbol, qty)
    except Exception:
        pass
    def _build_min_plan(t: Dict[str, Any], side_: str) -> Dict[str, Any]:
        splits = t.get("tp_splits")
        if not splits and tp_targets:
            n = len(tp_targets)
            splits = [1.0] if n == 1 else ([0.5, 0.5] if n == 2 else [0.30, 0.30, 0.40][:n])
        return {
            "mode": "HYBRID",
            "entry": None,
            "tp_targets": tp_targets or None,
            "sl_targets": sl_targets or None,
            "tp_splits": splits or None,
            "reduce_only": False,
        }

    base_kwargs: Dict[str, Any] = dict(
        symbol=symbol,
        side=side,
        budget=None,
        leverage=leverage,
        dry_run=False,
        quantity=qty,
        entry=None,
        tp_targets=tp_targets or None,
        sl_targets=sl_targets or None,
        tp_splits=ticket.get("tp_splits"),
        sl_splits=None,
        confirm_first=False,
        telegram_chat_id=int(os.getenv("TELEGRAM_CHAT_ID") or 0),
        position_side=pos_side,
        reduce_only=bool(ticket.get("reduce_only", False)),
    )
    clean = _filter_kwargs_for_callable(execute_trade_live, base_kwargs)
    try:
        sig = inspect.signature(execute_trade_live)  # type: ignore
        if "plan" in sig.parameters and "plan" not in clean:
            clean["plan"] = _build_min_plan(ticket, side)
    except Exception:
        pass

    try:
        maybe = execute_trade_live(**clean)  # type: ignore[misc]
        if inspect.isawaitable(maybe):
            res = await maybe  # type: ignore[assignment]
        else:
            res = maybe  # type: ignore[assignment]
        try:
            if not res.get("ok") and "precision" in str(res).lower():
                symbol2 = (ticket.get("symbol") or "").upper()
                side2 = (ticket.get("side") or "").upper()
                qty2 = float(ticket.get("qty") or ticket.get("quantity") or 0.0)
                from binance.client import Client  # type: ignore
                api_key = os.getenv("BINANCE_API_KEY", "").strip()
                api_sec = os.getenv("BINANCE_API_SECRET", "").strip()
                cli_ = Client(api_key, api_sec)
                _align_position_mode(cli_)
                qty_fixed = _round_to_lot_size(cli_, symbol2, qty2)
                ticket2 = dict(ticket); ticket2["qty"] = qty_fixed
                return await _execute_trade(ticket2)
        except Exception:
            pass
        return {"entered": bool(res.get("ok")), **res}  # type: ignore[arg-type]
    except Exception as e:
        return {"ok": False, "entered": False, "error": "armed_execute_failed", "detail": f"{e}", "trace": traceback.format_exc()}

# ======== AUTO QTY/LEV ========
def _round_qty(q: float, dec: int) -> float:
    try:
        fmt = "{:0." + str(int(dec)) + "f}"
        return float(fmt.format(q))
    except Exception:
        return float(f"{q:.3f}")

async def _apply_auto_qty_on_ticket_async(ticket: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    symbol = (ticket.get("symbol") or "").upper()
    price = await get_last_price_async(symbol)
    if not price or float(price) <= 0:
        return None
    new_ticket = dict(ticket)
    try:
        lev_min = int(new_ticket.get("leverage_min") or (new_ticket.get("leverage_range") or [AUTO_LEV_MIN, AUTO_LEV_MAX])[0] or AUTO_LEV_MIN)
        lev_max = int(new_ticket.get("leverage_max") or (new_ticket.get("leverage_range") or [AUTO_LEV_MIN, AUTO_LEV_MAX])[-1] or AUTO_LEV_MAX)
    except Exception:
        lev_min, lev_max = AUTO_LEV_MIN, AUTO_LEV_MAX
    if lev_min > lev_max:
        lev_min, lev_max = lev_max, lev_min
    try:
        bmin = float(new_ticket.get("budget_min") or (new_ticket.get("budget_range") or [AUTO_BUDGET_MIN, AUTO_BUDGET_MAX])[0] or AUTO_BUDGET_MIN)
        bmax = float(new_ticket.get("budget_max") or (new_ticket.get("budget_range") or [AUTO_BUDGET_MIN, AUTO_BUDGET_MAX])[-1] or AUTO_BUDGET_MAX)
    except Exception:
        bmin, bmax = AUTO_BUDGET_MIN, AUTO_BUDGET_MAX
    if bmin > bmax:
        bmin, bmax = bmax, bmin
    lev = int(new_ticket.get("leverage") or new_ticket.get("lev") or 0)
    if lev <= 0:
        lev = max(min((lev_min + lev_max) // 2, lev_max), lev_min)
        new_ticket["leverage"] = lev
    else:
        new_ticket["leverage"] = max(min(lev, lev_max), lev_min)
    with suppress(Exception):
        from utils.position_sizing import ensure_final_qty as _efq  # type: ignore
        new_ticket = _efq(new_ticket, float(price)) or new_ticket
    q = float(new_ticket.get("qty") or new_ticket.get("quantity") or 0.0)
    if q <= 0.0:
        budget_env = os.getenv("AUTO_QTY_BUDGET_USDT") or os.getenv("DEFAULT_STAKE_USDT", str(AUTO_BUDGET_MIN))
        try:
            max_budget = float(os.getenv("MAX_TRADE_BUDGET", budget_env or 0) or 0)
        except Exception:
            max_budget = 0.0
        budget_req = new_ticket.get("budget") or new_ticket.get("budget_usd")
        try:
            budget = float(budget_req) if budget_req not in (None, "", 0, "0", "0.0") else (bmin + bmax) / 2.0
        except Exception:
            budget = (bmin + bmax) / 2.0
        if budget <= 0:
            budget = float(budget_env or AUTO_BUDGET_MIN)
        budget = max(min(budget, bmax), bmin)
        if max_budget > 0:
            budget = min(budget, max_budget)
        if budget > 0 and new_ticket.get("leverage", 0):
            dec = int(os.getenv("QTY_DECIMALS", "3") or 3)
            calc_qty = (budget * float(new_ticket["leverage"])) / float(price)
            new_ticket["qty"] = _round_qty(calc_qty, dec)
    ps = str(new_ticket.get("position_side") or new_ticket.get("positionSide") or "").upper()
    if ps == "BOTH":
        new_ticket.pop("positionSide", None)
        new_ticket["position_side"] = ""
    return new_ticket

# ==================== OPS APPROVAL & EVENTS ROUTER ====================
router = APIRouter(tags=["ops-approval"])

# --------- Idempotent webhook example (/webhook/whatever) ----------
@router.post("/webhook/whatever")
async def webhook_whatever(request: Request):
    body = await request.body()
    headers = dict(request.headers)
    try:
        ok_first = await idem_for_request(body, headers, extra={"route": "/webhook/whatever"})
    except Exception as e:
        logger.warning("idem_for_request failed (permissive allow): %s", e)
        ok_first = True
    if not ok_first:
        return JSONResponse({"ok": True, "skipped": True, "reason": "idem_duplicate"}, status_code=200)
    return JSONResponse({"ok": True, "handled_once": True}, status_code=200)

def _require_bearer(request: Request) -> None:
    if os.getenv("PROTECT_APPROVE_ROUTES", "1").lower() not in ("1", "true", "yes", "on"):
        return
    if not API_BEARER_TOKEN:
        raise HTTPException(status_code=503, detail="Route protection enabled but API_BEARER_TOKEN missing")
    auth = request.headers.get("Authorization", "") or request.headers.get("authorization", "")
    parts = auth.split(" ", 1)
    if not parts or len(parts) < 2:
        raise HTTPException(status_code=401, detail="Unauthorized")
    scheme, token = parts[0].strip(), parts[1].strip()
    if scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Unauthorized")
    if token != API_BEARER_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

# ------- permissions helpers for alerts (from your patch) -------
def _allow_by_bearer_or_apikey(request: Request) -> None:
    """
    מרשה או Bearer (API_BEARER_TOKEN) או x-api-key (API_TOKEN/PRIMARY_API_TOKEN).
    """
    want_bearer = (request.headers.get("authorization") or request.headers.get("Authorization") or "").strip()
    x_api_key = (request.headers.get("x-api-key") or request.headers.get("X-API-Key") or "").strip()
    if API_BEARER_TOKEN and want_bearer.lower().startswith("bearer "):
        if want_bearer.split(" ", 1)[1].strip() == API_BEARER_TOKEN:
            return
    api_tokens = [(os.getenv("PRIMARY_API_TOKEN") or "").strip(),
                  (os.getenv("API_TOKEN") or "").strip(),
                  (os.getenv("API_BEARER_TOKEN") or "").strip()]
    if x_api_key and x_api_key in [t for t in api_tokens if t]:
        return
    raise HTTPException(status_code=401, detail="Unauthorized")

# ==================== Manager/Alerts routes (from your patch) ====================
@router.get("/ops/manager/health", tags=["manager"])
async def ops_manager_health():
    return {
        "ok": True,
        "enabled": True,
        "state_machine": "idle",
        "writes_orders": True,
        "ws_autoflip": True,
        "rt_manage": True,
        "pending_count": len(ConfirmStore.pending()) if CONFIRMSTORE_ENABLE else 0,
        "redis": bool(aioredis and REDIS_URL),
        "http2": _http2_enabled_runtime(),
        "version": APP_VERSION,
    }

@router.post("/ops/manager/tick", tags=["manager"])
async def ops_manager_tick(request: Request):
    _require_bearer(request)
    return {"ok": True, "tick": int(time.time())}

@router.get("/alerts/trades/active", tags=["ops-approval"])
async def alerts_trades_active(request: Request):
    _require_bearer(request)
    items: List[Dict[str, Any]] = []
    if aioredis and REDIS_URL:
        try:
            r = await _get_redis_cached()
            if r:
                patt = f"{NS}:ticket:*"
                cursor = "0"
                keys: List[str] = []
                for _ in range(50):
                    cursor, batch = await r.scan(cursor=cursor, match=patt, count=200)
                    keys.extend(batch)
                    if cursor == "0":
                        break
                for k in keys[:300]:
                    raw = await r.get(k)
                    if not raw:
                        continue
                    obj = json.loads(raw)
                    req = obj.get("req") or obj
                    items.append(req)
        except Exception:
            pass
    if CONFIRMSTORE_ENABLE:
        try:
            for it in ConfirmStore.pending():
                req = it.get("req") or it
                items.append(req)
        except Exception:
            pass
    return {"ok": True, "items": items, "count": len(items)}

@router.post("/alerts/ingest", tags=["ops-approval"])
async def alerts_ingest(request: Request, payload: Dict[str, Any] = Body(...)):
    _allow_by_bearer_or_apikey(request)
    payload = dict(payload or {})
    payload.setdefault("leverage_min", AUTO_LEV_MIN)
    payload.setdefault("leverage_max", AUTO_LEV_MAX)
    payload.setdefault("budget_min", AUTO_BUDGET_MIN)
    payload.setdefault("budget_max", AUTO_BUDGET_MAX)
    payload["require_approval"] = True if payload.get("require_approval") is None else bool(payload.get("require_approval"))
    res = await create_ticket(payload, request=request)
    return res

@router.post("/alerts/trades/update", tags=["ops-approval"])
async def alerts_trades_update(request: Request, body: Dict[str, Any] = Body(...)):
    """
    צפה ל-body: {"ticket_id":"...", "action":"approve"|"reject", "exp":<unix optional>}
    אימות: כותרת X-Signature-Hex = HMAC-SHA256(OPS_SIGN_SECRET, raw_body)
    אופציונלי: X-Request-Nonce למניעת replay (אם ANTI_REPLAY_ENABLE=1)
    """
    raw = await request.body()
    sig_hex = request.headers.get("X-Signature-Hex") or request.headers.get("x-signature-hex") or ""
    if not HMAC_SECRET:
        raise HTTPException(status_code=503, detail="OPS_SIGN_SECRET/WEBHOOK_HMAC_SECRET missing")
    want = _sign_hex(HMAC_SECRET, raw)
    if not sig_hex or not hmac.compare_digest(sig_hex.strip(), want):
        raise HTTPException(status_code=401, detail="bad_signature")
    await _enforce_nonce_once(request)
    _require_not_expired(body.get("exp"))
    ticket_id = str(body.get("ticket_id") or "").strip()
    action = (body.get("action") or "").strip().lower()
    if not (ticket_id and action in ("approve", "reject")):
        raise HTTPException(status_code=422, detail="missing_fields")
    if action == "approve":
        return await _approve_core(ticket_id)
    return await _reject_core(ticket_id)

# ==================== Ticket/UI/Approve/Reject ====================
def _rows_kv_html(t: Dict[str, Any]) -> str:
    def cv(k, default="—"):
        v = t.get(k, default)
        return default if v in (None, "", []) else _md_html(str(v))
    rows = []
    for k in (
        "ticket_id","symbol","side","qty","leverage","position_side","budget","score",
        "tp1","tp2","tp3","sl","eta_tp1_min","eta_tp2_min","eta_tp3_min",
        "prob_overall_pct","prob_tp1_pct","prob_tp2_pct","prob_tp3_pct","tp_splits",
        "expiry_ts","note",
    ):
        rows.append(
            f"<tr><th style='text-align:left;padding:.35rem .6rem;background:#fafafa'>{k}</th>"
            f"<td style='padding:.35rem .6rem'>{cv(k)}</td></tr>"
        )
    return "\n".join(rows)

def _html(msg: str) -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html><meta charset='utf-8'>"
        "<body style='font-family:sans-serif;max-width:720px;margin:3rem auto;line-height:1.5'>"
        f"<h2 style='margin:0 0 .5rem 0'>{msg}</h2>"
        "<p style='color:#666'>אפשר לחזור חזרה לטלגרם.</p>"
        "</body>"
    )

async def _load_ticket(ticket_id: str) -> Tuple[Optional[Dict[str, Any]], str]:
    if aioredis and REDIS_URL:
        try:
            r = await _get_redis_cached()
            if r:
                raw = await r.get(f"{NS}:ticket:{ticket_id}")
                if raw:
                    obj = json.loads(raw)
                    req = obj.get("req") or obj
                    return dict(req), "redis"
        except Exception as e:
            logger.warning("load_ticket_redis_failed: %s", e)
    if CONFIRMSTORE_ENABLE:
        with suppress(Exception):
            for it in ConfirmStore.pending():
                if str(it.get("ticket_id")) == str(ticket_id):
                    return dict(it.get("req") or it), "memory"
    return None, "none"

async def _delete_ticket(ticket_id: str, source: str, final_status: Optional[bool] = None) -> None:
    event: Dict[str, Any] = {
        "ts": time.time(),
        "ticket_id": ticket_id,
        "status": final_status,
        "src": source,
        "ns": NS,
        "reason": ("expired" if final_status is None else ("approved" if final_status else "rejected")),
    }
    fetched_req: Optional[Dict[str, Any]] = None
    if aioredis and REDIS_URL and source == "redis":
        with suppress(Exception):
            r = await _get_redis_cached()
            if r:
                raw = await r.get(f"{NS}:ticket:{ticket_id}")
                if raw:
                    obj = json.loads(raw)
                    fetched_req = obj.get("req") or obj
    if not fetched_req and source == "memory" and CONFIRMSTORE_ENABLE:
        with suppress(Exception):
            for it in ConfirmStore.pending():
                if str(it.get("ticket_id")) == str(ticket_id):
                    fetched_req = it.get("req") or it
                    break
    if fetched_req:
        event["symbol"] = str(fetched_req.get("symbol", "")).upper()
        event["side"] = str(fetched_req.get("side", "")).upper()
        event["expiry_ts"] = fetched_req.get("expiry_ts")
        event["note"] = fetched_req.get("note")
        base = f"{ticket_id}:{event.get('symbol', '')}:{event.get('side', '')}"
        event["idem"] = hashlib.md5(base.encode("utf-8")).hexdigest()[:10]
    else:
        event["symbol"] = ""
        event["side"] = ""
        event["idem"] = hashlib.md5(f"{ticket_id}".encode("utf-8")).hexdigest()[:10]
    if aioredis and REDIS_URL:
        with suppress(Exception):
            r = await _get_redis_cached()
            if r:
                key_good = f"{NS}:expired_log"
                key_bad = f"{NS}:expired_log_bad"
                key = key_good if (event.get("symbol") and event.get("side")) else key_bad
                await r.lpush(key, json.dumps(event, ensure_ascii=False, separators=(",", ":")))
                await r.ltrim(key, 0, 2999)
                await r.delete(f"{NS}:ticket:{ticket_id}")
    with suppress(Exception):
        ConfirmStore.remove(ticket_id)

@router.post("/ops/ticket")
async def create_ticket(payload: Dict[str, Any] = Body(...), request: Request = None):
    symbol = (payload.get("symbol") or "").upper().strip()
    side = (payload.get("side") or "").upper().strip()
    qty = float(payload.get("qty") or payload.get("quantity") or 0)
    lev = int(payload.get("leverage") or payload.get("lev") or 0)
    note = payload.get("note") or ""
    position_side = (payload.get("position_side") or payload.get("positionSide") or "BOTH").upper()
    budget = float(payload.get("budget") or payload.get("budget_usd") or 0.0)
    if not (symbol and side):
        raise HTTPException(status_code=422, detail="Missing fields (symbol/side).")
    tid = payload.get("ticket_id") or f"T_{secrets.token_hex(4)}"

    with suppress(Exception):
        if isinstance(payload.get("tp_splits"), str):
            payload["tp_splits"] = [float(x) for x in str(payload["tp_splits"]).split(",") if x.strip()]

    if ETA_SMART_ENABLE and (payload.get("tp1") or payload.get("tp2") or payload.get("tp3")):
        price_now = None
        with suppress(Exception):
            price_now = await get_last_price_async(symbol)
        def _smart(symbol: str, side: str, price_now: Optional[float], tps: List[Optional[float]]) -> Dict[str, Any]:
            try:
                if not price_now:
                    return {}
                out: Dict[str, Any] = {}
                for i, tp in enumerate(tps, start=1):
                    if tp and tp > 0:
                        dist_bps = abs((tp - price_now) / price_now) * 10_000
                        out[f"eta_tp{i}_min"] = max(1, int(dist_bps / max(1, ETA_VELOCITY_WINDOW)))
                out.setdefault("eta_open_min", out.get("eta_tp1_min", 2))
                return out
            except Exception:
                return {}
        etas = _smart(symbol, side, price_now, [payload.get("tp1"), payload.get("tp2"), payload.get("tp3")])
        payload.update(etas)

    lev_min = payload.get("leverage_min") or (payload.get("leverage_range") or [None, None])[0]
    lev_max = payload.get("leverage_max") or (payload.get("leverage_range") or [None, None])[-1]
    bud_min = payload.get("budget_min") or (payload.get("budget_range") or [None, None])[0]
    bud_max = payload.get("budget_max") or (payload.get("budget_range") or [None, None])[-1]

    req_body: Dict[str, Any] = {
        "ticket_id": tid,
        "symbol": symbol,
        "side": side,
        "qty": qty,
        "leverage": lev,
        "position_side": position_side,
        "budget": budget,
        "note": note,
        "leverage_min": lev_min,
        "leverage_max": lev_max,
        "budget_min": bud_min,
        "budget_max": bud_max,
        "score": payload.get("score"),
        "eta_open_min": payload.get("eta_open_min"),
        "tp1": payload.get("tp1"),
        "tp2": payload.get("tp2"),
        "tp3": payload.get("tp3"),
        "eta_tp1_min": payload.get("eta_tp1_min"),
        "eta_tp2_min": payload.get("eta_tp2_min"),
        "eta_tp3_min": payload.get("eta_tp3_min"),
        "sl": payload.get("sl"),
        "prob_overall_pct": payload.get("prob_overall_pct"),
        "prob_tp1_pct": payload.get("prob_tp1_pct"),
        "prob_tp2_pct": payload.get("prob_tp2_pct"),
        "prob_tp3_pct": payload.get("prob_tp3_pct"),
        "tp_splits": payload.get("tp_splits"),
        "expiry_ts": payload.get("expiry_ts"),
    }

    persisted = False
    if aioredis and REDIS_URL:
        try:
            r = await _get_redis_cached()
            if r:
                rec = {"ts": time.time(), "req": req_body, "note": note}
                await r.setex(f"{NS}:ticket:{tid}", OPS_TICKET_TTL_SEC, json.dumps(rec, ensure_ascii=False, separators=(",", ":")))
                persisted = True
        except Exception as e:
            logger.warning("redis_set_failed: %s", e)
    if not persisted:
        if REQUIRE_REDIS and REDIS_URL:
            logger.error("ticket_persist_failed: REQUIRE_REDIS=true but Redis unavailable")
            raise HTTPException(status_code=503, detail="storage_unavailable: redis_required")
        if CONFIRMSTORE_ENABLE or (not REDIS_URL):
            try:
                ConfirmStore.create(dict(req_body))
                persisted = True
            except Exception as e:
                logger.exception("confirmstore_create_failed: %s", e)
            with suppress(Exception):
                persisted = bool(ConfirmStore.pending())

    with suppress(Exception):
        inc_approvals_created()

    with suppress(Exception):
        cli = _get_shared_async_client()
        px = await get_last_price_async(symbol) or 0.0
        spread_pct = 0.0
        try:
            r = await cli.get(_fut_http() + "/fapi/v1/ticker/bookTicker", params={"symbol": symbol}, timeout=httpx.Timeout(6.0))
            if r.status_code == 200:
                bd = r.json()
                bid = float(bd.get("bidPrice") or 0.0)
                ask = float(bd.get("askPrice") or 0.0)
                if bid > 0 and ask > 0:
                    spread_pct = abs(ask - bid) / ((ask + bid) / 2.0) * 100.0
        except Exception:
            pass
        atr_pct = 0.0
        kl = await _fetch_klines_http(symbol, "15m", 120)
        if kl:
            ind = _compute_indicators_from_klines(kl, period=14)
            price = float(ind.get("price") or 0.0) or px
            atr = float(ind.get("atr") or 0.0)
            atr_pct = (atr / price) * 100.0 if price > 0 else 0.0
        notional = float(budget or 0.0)
        if notional <= 0 and px > 0 and qty > 0 and lev > 0:
            notional = float(px) * float(qty) / max(1.0, float(lev))
        try:
            est_bps = estimate_impact_slip_bps(spread_pct, atr_pct, notional, max_bps=float(os.getenv("IMPACT_SLIP_BPS_MAX", "25") or 25.0))
            set_last_slip_estimate_bps(float(est_bps))
        except Exception:
            pass

    base = PUBLIC_HOST.rstrip("/") if PUBLIC_HOST else (str(request.base_url).rstrip("/") if request else "")
    preview_url = _build_signed_link(base, "/ops/ui/ticket/signed", tid, ttl_sec=900, action="preview")
    approve_url = _build_signed_link(base, "/ops/approve/signed", tid, ttl_sec=900, action="approve")
    reject_url = _build_signed_link(base, "/ops/reject/signed", tid, ttl_sec=900, action="reject")

    manage_url = ""
    try:
        sym_for_btn = str(symbol or "").upper()
        manage_url = _build_signed_link(base, "/manage-once/signed", sym_for_btn, ttl_sec=600, action="manage")
        if "?" in manage_url:
            manage_url += f"&symbol={sym_for_btn}"
        else:
            manage_url += f"?symbol={sym_for_btn}"
    except Exception:
        manage_url = ""

    lines = [
        "⚠️ <b>Approval Needed</b>",
        f"• Ticket: <code>{_md_html(tid)}</code>",
        f"• {_md_html(symbol)} {_md_html(side)} qty=<code>{_md_html(qty)}</code> lev=<code>{_md_html(lev)}</code>",
    ]
    for i in (1, 2, 3):
        if req_body.get(f"tp{i}") is not None:
            tp_val = req_body.get(f"tp{i}")
            row = f"• TP{i}: <code>{_md_html(str(tp_val))}</code>"
            if req_body.get(f"eta_tp{i}_min") is not None:
                row += f"  ETA:<code>{req_body[f'eta_tp{i}_min']}m</code>"
            if req_body.get(f"prob_tp{i}_pct") is not None:
                row += f"  P(s):<code>{req_body[f'prob_tp{i}_pct']}%</code>"
            lines.append(row)
    if req_body.get("sl") is not None:
        lines.append(f"• SL: <code>{_md_html(req_body['sl'])}</code>")
    if req_body.get("tp_splits"):
        lines.append(f"• TP Splits: <code>{_md_html(req_body['tp_splits'])}</code>")
    if req_body.get("prob_overall_pct") is not None:
        lines.append(f"• Success %: <code>{_md_html(req_body['prob_overall_pct'])}%</code>")
    if req_body.get("expiry_ts") is not None:
        lines.append(f"• Expires: <code>{_md_html(req_body['expiry_ts'])}</code>")
    if note:
        lines.append(f"• Note: {_md_html(note)}")
    lines.append("— — —")
    lines.append("בחר:")
    pretty = "\n".join(lines)
    try:
        tg_resp = await _send_telegram_html(pretty,
                                            approve_url=approve_url or None,
                                            reject_url=reject_url or None,
                                            preview_url=preview_url or None,
                                            manage_url=manage_url or None)
    except Exception as e:
        logger.warning("telegram_send_failed (non-fatal): %s", e)
        tg_resp = {"ok": False, "skipped": True, "error": str(e)}

    return {
        "ok": True,
        "ticket_id": tid,
        "approve_url": approve_url,
        "reject_url": reject_url,
        "preview_url": preview_url,
        "manage_url": manage_url,
        "telegram_result": tg_resp,
    }

def _decide_flow_by_mode(ticket: Dict[str, Any]) -> str:
    mode = _parse_mode(ticket.get("note"))
    if mode in ("MARKET", "HYBRID", "AUTO"):
        return mode
    if callable(decide_execution_mode):
        with suppress(Exception):
            m = decide_execution_mode(ticket)  # type: ignore
            if isinstance(m, str) and m.upper() in ("MARKET", "HYBRID", "AUTO"):
                return m.upper()
    return "HYBRID" if os.getenv("TP_LADDER_ON_APPROVE", "1").lower() in ("1", "true", "yes", "on") else "MARKET"

def _render_ticket_html(ticket_id: str, rec: Dict[str, Any], base: str) -> HTMLResponse:
    approve_url = _build_signed_link(base, "/ops/approve/signed", ticket_id, ttl_sec=900, action="approve")
    reject_url = _build_signed_link(base, "/ops/reject/signed", ticket_id, ttl_sec=900, action="reject")
    body = (
        "<!doctype html><meta charset='utf-8'>"
        "<body style='font-family:sans-serif;max-width:880px;margin:2rem auto;line-height:1.45'>"
        f"<h2 style='margin:0 0 1rem 0'>Ticket Preview · <code>{_md_html(ticket_id)}</code></h2>"
        "<div style='margin:.5rem 0 1rem 0'>"
        f"<a href='{approve_url}' style='display:inline-block;padding:.6rem 1rem;background:#16a34a;color:#fff;border-radius:9px;text-decoration:none'>✅ Approve</a>"
        f"<a href='{reject_url}' style='display:inline-block;padding:.6rem 1rem;background:#dc2626;color:#fff;border-radius:9px;text-decoration:none;margin-left:.6rem'>❌ Reject</a>"
        "</div>"
        "<table style='border-collapse:collapse;width:100%;border:1px solid #eee'>"
        f"{_rows_kv_html(rec)}"
        "</table>"
        "<p style='color:#777;margin-top:1rem'>טיפ: ניתן לאשר/לדחות גם מהטלגרם.</p>"
        "</body>"
    )
    return HTMLResponse(body)

@router.get("/ops/ui/ticket")
async def ui_ticket(ticket_id: str = Query(...), request: Request = None):
    if not API_BEARER_TOKEN:
        raise HTTPException(status_code=503, detail="Route protection enabled but API_BEARER_TOKEN missing")
    auth = request.headers.get("Authorization", "") if request else ""
    if not (auth.startswith("Bearer ") and auth.split(" ", 1)[1].strip() == API_BEARER_TOKEN):
        raise HTTPException(status_code=401, detail="Unauthorized")
    rec, _ = await _load_ticket(ticket_id)
    if not rec:
        return _html("⚠️ לא נמצא כרטיס או שפג תוקפו.")
    base = PUBLIC_HOST.rstrip("/") if PUBLIC_HOST else (str(request.base_url).rstrip("/") if request else "")
    return _render_ticket_html(ticket_id, rec, base)

@router.get("/ops/ui/ticket/signed")
async def ui_ticket_signed(ticket_id: str = Query(...), exp: str = Query(...), sig: str = Query(...), request: Request = None):
    if not _verify_signed_params(ticket_id, exp, sig, "/ops/ui/ticket/signed"):
        raise HTTPException(status_code=401, detail="Bad or expired signature")
    rec, _ = await _load_ticket(ticket_id)
    if not rec:
        return _html("⚠️ לא נמצא כרטיס או שפג תוקפו.")
    base = PUBLIC_HOST.rstrip("/") if PUBLIC_HOST else (str(request.base_url).rstrip("/") if request else "")
    return _render_ticket_html(ticket_id, rec, base)

@router.get("/public/ticket/inspect", tags=["public"])
async def public_ticket_inspect(ticket_id: str = Query(...)):
    rec, _ = await _load_ticket(ticket_id)
    if rec:
        return JSONResponse({"ok": True, "ticket_id": ticket_id, "found": True, "key": f"{NS}:ticket:{ticket_id}", "data": rec})
    return JSONResponse({"ok": True, "ticket_id": ticket_id, "found": False}, status_code=404)

def _maybe_protect_routes(request: Request) -> None:
    _require_bearer(request)

@router.get("/ops/approve")
async def approve(ticket_id: str = Query(..., description="ticket_id"), request: Request = None):
    _maybe_protect_routes(request)
    return await _approve_core(ticket_id)

@router.get("/ops/reject")
async def reject(ticket_id: str = Query(..., description="ticket_id"), request: Request = None):
    _maybe_protect_routes(request)
    return await _reject_core(ticket_id)

@router.get("/ops/approve/signed")
async def approve_signed(ticket_id: str = Query(...), exp: str = Query(...), sig: str = Query(...)):
    if not _verify_signed_params(ticket_id, exp, sig, "/ops/approve/signed"):
        raise HTTPException(status_code=401, detail="Bad or expired signature")
    return await _approve_core(ticket_id)

@router.get("/ops/reject/signed")
async def reject_signed(ticket_id: str = Query(...), exp: str = Query(...), sig: str = Query(...)):
    if not _verify_signed_params(ticket_id, exp, sig, "/ops/reject/signed"):
        raise HTTPException(status_code=401, detail="Bad or expired signature")
    return await _reject_core(ticket_id)

@router.post("/ops/approve/signed")
async def approve_signed_post(request: Request, payload: Dict[str, Any] = Body(...)):
    """
    גוף צפוי: {"approve": true|false, "ticket_id": "...", "exp": <optional>}
    """
    raw = await request.body()
    ok, reason = _verify_http_signature(request, raw, route_path="/ops/approve/signed")
    if not ok:
        hdrs = {}
        try:
            if os.getenv("SIG_TS_ENFORCE", "0").lower() in ("1","true","yes","on"):
                hdrs["Replay-Window"] = os.getenv("SIG_TS_SKEW_SEC", "900")
        except Exception:
            pass
        raise HTTPException(status_code=401, detail="Bad signature", headers=hdrs)
    await _enforce_nonce_once(request)
    _require_not_expired(payload.get("exp"))
    ticket_id = str(payload.get("ticket_id") or "").strip()
    approved = bool(payload.get("approve") is True)
    if not ticket_id:
        raise HTTPException(status_code=422, detail="Missing ticket_id")
    if not approved:
        return await _reject_core(ticket_id)
    return await _approve_core(ticket_id)

@router.post("/ops/reject/signed")
async def reject_signed_post(request: Request, payload: Dict[str, Any] = Body(...)):
    raw = await request.body()
    ok, reason = _verify_http_signature(request, raw, route_path="/ops/reject/signed")
    if not ok:
        hdrs = {}
        try:
            if os.getenv("SIG_TS_ENFORCE", "0").lower() in ("1","true","yes","on"):
                hdrs["Replay-Window"] = os.getenv("SIG_TS_SKEW_SEC", "900")
        except Exception:
            pass
        raise HTTPException(status_code=401, detail="Bad signature", headers=hdrs)
    await _enforce_nonce_once(request)
    _require_not_expired(payload.get("exp"))
    try:
        ticket_id = str(payload.get("ticket_id") or "").strip()
        approved = bool(payload.get("approve") is True)
    except Exception:
        raise HTTPException(status_code=422, detail="bad_payload")
    if not ticket_id:
        raise HTTPException(status_code=422, detail="missing_fields")
    if approved:
        raise HTTPException(status_code=422, detail="approve_true_on_reject_endpoint")
    return await _reject_core(ticket_id)

# --- בטוח: עטיפת smart_manage_now (אם קיים) ---
async def _smart_manage_now(symbol: str,
                            offset_bps: Optional[int] = None,
                            pcts: Optional[List[float]] = None,
                            splits: Optional[List[float]] = None,
                            atr_mult: Optional[float] = None) -> Dict[str, Any]:
    fn = None
    with suppress(Exception):
        from routes.manager import smart_manage_now as _fn  # type: ignore
        fn = _fn
    if fn is None:
        with suppress(Exception):
            from app.manager import smart_manage_now as _fn  # type: ignore
            fn = _fn
    if fn is None:
        return {"ok": True, "delegated": False, "skipped": True, "reason": "smart_manage_now_not_available"}

    params = dict(symbol=symbol, offset_bps=offset_bps, pcts=pcts, splits=splits, atr_mult=atr_mult)
    params = _filter_kwargs_for_callable(fn, params)
    try:
        if inspect.iscoroutinefunction(fn):  # type: ignore[arg-type]
            return await fn(**params)  # type: ignore[misc]
        return await asyncio.to_thread(lambda: fn(**params))  # type: ignore[misc]
    except Exception as e:
        return {"ok": False, "error": "smart_manage_now_failed", "detail": f"{e}"}

async def _try_mark_decided(ticket_id: str, decision: str, ttl: int = 30) -> bool:
    if not (aioredis and REDIS_URL):
        bucket = getattr(app.state, "_decided_mem", None)
        if bucket is None:
            bucket = {}
            app.state._decided_mem = bucket
        now = time.time()
        for k, ts in list(bucket.items()):
            try:
                if now - float(ts) > 300:
                    bucket.pop(k, None)
            except Exception:
                bucket.pop(k, None)
        key_any = f"{ticket_id}:ANY"
        if key_any in bucket:
            return False
        bucket[key_any] = now
        return True
    r = await _get_redis_cached()
    if not r:
        return True
    key_any = f"{NS}:decided:{ticket_id}:ANY"
    ok = await r.setnx(key_any, "1")
    if ok:
        with suppress(Exception):
            await r.expire(key_any, ttl)
    return bool(ok)

async def _approve_core(ticket_id: str):
    if not await _try_mark_decided(ticket_id, "approve"):
        return _html("⚠️ בקשה זו כבר טופלה (כפילות נמנעה).")

    ticket, source = await _load_ticket(ticket_id)
    if not ticket:
        return _html("⚠️ קישור שגוי או שפג תוקף האישור.")
    with suppress(Exception):
        for k in ("blocked_by_rr_min", "blocked_by_velocity", "velocity_error"):
            ticket.pop(k, None)

    ENTRY_SCORE_MIN = float(os.getenv("ENTRY_SCORE_MIN", "0") or 0)
    if ENTRY_SCORE_MIN > 0 and compute_pretrade_score is not None:
        try:
            inc_scan_eval()
        except Exception:
            pass
        try:
            kl = await _fetch_klines_http(str(ticket.get("symbol", "")), interval=os.getenv("ENTRY_SCORE_INTERVAL", "15m"), limit=120)
            adx = atr_pct = 0.0
            if kl:
                ind = _compute_indicators_from_klines(kl, period=14)
                price = float(ind.get("price") or 0.0)
                atr = float(ind.get("atr") or 0.0)
                adx = float(ind.get("adx") or 0.0)
                atr_pct = (atr / price) * 100.0 if price > 0 else 0.0
            res = compute_pretrade_score(kl, adx=adx, atr_pct=atr_pct) if kl else {"score": 0.0, "features": {}}
            score = float(res.get("score", 0.0))
            ticket["score"] = score
            with suppress(Exception):
                set_last_entry_score(score)
            if score < ENTRY_SCORE_MIN:
                with suppress(Exception):
                    inc_scan_blocked()
                with suppress(Exception):
                    await _send_telegram_html(
                        "🚫 <b>Approval Blocked (Checklist)</b>\n"
                        f"• Ticket: <code>{_md_html(ticket_id)}</code>\n"
                        f"• { _md_html(str(ticket.get('symbol',''))) } { _md_html(str(ticket.get('side',''))) }\n"
                        f"• score=<code>{score:.2f}</code>, min=<code>{ENTRY_SCORE_MIN:.2f}</code>"
                    )
                await _delete_ticket(ticket_id, source, final_status=False)
                return _html(f"⛔️ נחסם ע״י Checklist · score={score:.2f} < {ENTRY_SCORE_MIN:.2f}")
            else:
                with suppress(Exception):
                    inc_scan_passed()
        except Exception as e:
            logger.warning("checklist_gate_failed (permissive allow): %s", e)

    t2 = await _apply_auto_qty_on_ticket_async(ticket)
    if t2 is None:
        return _html("⚠️ שגיאה: לא ניתן להביא מחיר עדכני לצורך חישוב כמות אוטומטית.")
    ticket = t2
    if float(ticket.get("qty") or 0) <= 0 or int(ticket.get("leverage") or 0) <= 0:
        return _html("⚠️ שגיאה: qty/leverage חסרים גם לאחר ניסיון חישוב אוטומטי.")
    flow = _decide_flow_by_mode(ticket)
    exec_res = await (
        _execute_trade(ticket) if flow == "MARKET"
        else _execute_trade_armed(ticket) if flow == "HYBRID"
        else (_execute_trade_armed(ticket) if any(ticket.get(k) for k in ("tp1", "tp2", "tp3", "sl"))
              else _execute_trade(ticket))
    )
    ok = bool(exec_res.get("ok"))
    entered = bool(exec_res.get("entered"))
    if (not ok) and (not entered) and flow in ("HYBRID", "AUTO") and (os.getenv("PROPOSE_BLOCK_ON_FAIL", "0").lower() not in ("1", "true", "yes", "on")):
        retry_res = await _execute_trade(ticket)
        ok = bool(retry_res.get("ok"))
        exec_res = {"primary": "HYBRID", "fallback_market": retry_res, "primary_error": exec_res}

    try:
        if ok:
            inc_approve_ok()
        else:
            inc_approve_fail()
    except Exception:
        pass

    if ok:
        try:
            sm = {
                "enable": os.getenv("SMART_MANAGE_ON_APPROVE", "1").lower() in ("1", "true", "yes", "on"),
                "offset_bps": int(os.getenv("SMART_MANAGE_BE_OFFSET_BPS",
                                    os.getenv("BE_BPS",
                                    os.getenv("TRAIL_OFFSET_BPS",
                                    os.getenv("TP_BE_OFFSET_BPS", "5"))))),
                "pcts": [float(x) for x in (os.getenv("SMART_MANAGE_PCTS") or "3,6,10,16").split(",") if x.strip()],
                "splits": [float(x) for x in (os.getenv("SMART_MANAGE_SPLITS") or "0.25,0.25,0.25,0.25").split(",") if x.strip()],
                "atr_mult": float(os.getenv("SMART_MANAGE_TRAIL_ATR_MULT", "0") or 0) or None,
            }
            if sm.get("enable", True):
                await _smart_manage_now(
                    str(ticket.get("symbol", "")).upper(),
                    offset_bps=sm.get("offset_bps"),
                    pcts=sm.get("pcts"),
                    splits=sm.get("splits"),
                    atr_mult=sm.get("atr_mult"),
                )
        except Exception as e:
            logger.warning("smart_manage_trigger_failed: %s", e)
    with suppress(Exception):
        sym, side, qty = ticket.get("symbol", ""), ticket.get("side", ""), ticket.get("qty", "")
        msg = (
            f"✅ <b>Approved</b>\n• Ticket: <code>{_md_html(ticket_id)}</code>\n"
            f"• {_md_html(sym)} {_md_html(side)} qty=<code>{_md_html(qty)}</code>\n• Flow: <code>{flow}</code>\n— — —\nבוצע והועבר לניהול."
            if ok
            else
            f"⚠️ <b>Approve Failed</b>\n• Ticket: <code>{_md_html(ticket_id)}</code>\n"
            f"• {_md_html(sym)} {_md_html(side)} qty=<code>{_md_html(qty)}</code>\n• Flow: <code>{flow}</code>\n— — —\n"
            f"שגיאה: <code>{_md_html(json.dumps(exec_res, ensure_ascii=False))}</code>"
        )
        await _send_telegram_html(msg)
    await _delete_ticket(ticket_id, source, final_status=ok)
    return _html("✅ אושר — הוזמן ונכנס לניהול דינמי.") if ok else _html("⚠️ שגיאה בביצוע — ראה פירוט בטלגרם/לוגים.")

async def _reject_core(ticket_id: str):
    if not await _try_mark_decided(ticket_id, "reject"):
        return _html("⚠️ בקשה זו כבר טופלה (כפילות נמנעה).")

    ticket, source = await _load_ticket(ticket_id)
    if not ticket:
        return _html("⚠️ קישור שגוי או שפג תוקף האישור/דחייה.")

    try:
        inc_reject()
    except Exception:
        pass

    sym, side, qty = (str(ticket.get("symbol", "")) or "").upper(), str(ticket.get("side", "")).upper(), ticket.get("qty", "")
    with suppress(Exception):
        await _send_telegram_html(
            f"⛔️ <b>Rejected</b>\n• Ticket: <code>{_md_html(ticket_id)}</code>\n• {_md_html(sym)} {_md_html(side)} qty=<code>{_md_html(qty)}</code>\n— — —\nהבקשה נדחתה."
        )
    await _delete_ticket(ticket_id, source, final_status=False)
    return _html("⛔️ נדחה — הכרטיס הוסר.")

# ==================== Indicator & profile helpers ====================
PROFILE_AUTO_SELECT = os.getenv("PROFILE_AUTO_SELECT", "1").lower() in ("1", "true", "yes", "on")

PROFILE_BASE_BE_BPS = int(os.getenv("PROFILE_BASE_BE_BPS", os.getenv("BE_BPS", "5")))
PROFILE_BASE_PCTS = [float(x) for x in (os.getenv("PROFILE_BASE_PCTS", "3,6,10,16")).split(",") if x.strip()]
PROFILE_BASE_SPLITS = [float(x) for x in (os.getenv("PROFILE_BASE_SPLITS", "0.25,0.25,0.25,0.25")).split(",") if x.strip()]
PROFILE_BASE_ATR_MULT = float(os.getenv("PROFILE_BASE_ATR_MULT", "0") or 0) or None

PROFILE_EXTREME_BE_BPS = int(os.getenv("PROFILE_EXTREME_BE_BPS", "2"))
PROFILE_EXTREME_PCTS = [float(x) for x in (os.getenv("PROFILE_EXTREME_PCTS", "2,4,7,12")).split(",") if x.strip()]
PROFILE_EXTREME_SPLITS = [float(x) for x in (os.getenv("PROFILE_EXTREME_SPLITS", "0.20,0.25,0.25,0.30")).split(",") if x.strip()]
PROFILE_EXTREME_ATR_MULT = float(os.getenv("PROFILE_EXTREME_ATR_MULT", "1.6"))

ADX_EXTREME_MIN = float(os.getenv("ADX_EXTREME_MIN", "28"))
ATRPCT_EXTREME_MIN = float(os.getenv("ATRPCT_EXTREME_MIN", "0.007"))

def _wilder_smooth(values: List[float], period: int) -> List[float]:
    if not values or period <= 0 or len(values) < period:
        return []
    smoothed = [sum(values[:period]) / period]
    for v in values[period:]:
        smoothed.append((smoothed[-1] * (period - 1) + v) / period)
    return smoothed

def _compute_indicators_from_klines(klines: List[List[Any]], period: int = 14) -> Dict[str, float]:
    try:
        highs = [float(k[2]) for k in klines]
        lows = [float(k[3]) for k in klines]
        closes = [float(k[4]) for k in klines]
        if len(closes) < period + 2:
            return {"atr": 0.0, "adx": 0.0, "price": closes[-1] if closes else 0.0}
        trs, plus_dm, minus_dm = [], [], []
        for i in range(1, len(closes)):
            h, l, ph, pl, pc = highs[i], lows[i], highs[i - 1], lows[i - 1], closes[i - 1]
            tr = max(h - l, abs(h - pc), abs(l - pc))
            trs.append(tr)
            up_move = h - ph
            down_move = pl - l
            plus_dm.append(up_move if (up_move > down_move and up_move > 0) else 0.0)
            minus_dm.append(down_move if (down_move > up_move and down_move > 0) else 0.0)
        atr_series = _wilder_smooth(trs, period)
        plus_dm_s = _wilder_smooth(plus_dm, period)
        minus_dm_s = _wilder_smooth(minus_dm, period)
        if not (atr_series and plus_dm_s and minus_dm_s):
            return {"atr": 0.0, "adx": 0.0, "price": closes[-1]}
        atr = atr_series[-1]
        plus_di = [(p / atr_series[i]) * 100 if atr_series[i] > 0 else 0.0 for i, p in enumerate(plus_dm_s)]
        minus_di = [(m / atr_series[i]) * 100 if atr_series[i] > 0 else 0.0 for i, m in enumerate(minus_dm_s)]
        dx = []
        for i in range(min(len(plus_di), len(minus_di))):
            s = plus_di[i] + minus_di[i]
            d = abs(plus_di[i] - minus_di[i])
            dx.append((d / s) * 100 if s > 0 else 0.0)
        adx_series = _wilder_smooth(dx, period)
        adx = adx_series[-1] if adx_series else 0.0
        return {"atr": float(atr), "adx": float(adx), "price": float(closes[-1])}
    except Exception:
        return {"atr": 0.0, "adx": 0.0, "price": 0.0}

async def _select_profile_for_symbol(client, symbol: str, payload: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, float], str]:
    try:
        klines = client.futures_klines(symbol=symbol, interval="1m", limit=60)
    except Exception:
        klines = []
    indicators = _compute_indicators_from_klines(klines or [], period=14)
    price = float(indicators.get("price") or 0.0)
    atr = float(indicators.get("atr") or 0.0)
    adx = float(indicators.get("adx") or 0.0)
    atr_pct = (atr / price) if price > 0 else 0.0

    use_extreme = PROFILE_AUTO_SELECT and ((adx >= ADX_EXTREME_MIN) or (atr_pct >= ATRPCT_EXTREME_MIN))
    profile_name = "EXTREME" if use_extreme else "BASE"

    if use_extreme:
        prof = dict(offset_bps=PROFILE_EXTREME_BE_BPS, pcts=PROFILE_EXTREME_PCTS[:], splits=PROFILE_EXTREME_SPLITS[:], atr_mult=PROFILE_EXTREME_ATR_MULT)
    else:
        prof = dict(offset_bps=PROFILE_BASE_BE_BPS, pcts=PROFILE_BASE_PCTS[:], splits=PROFILE_BASE_SPLITS[:], atr_mult=PROFILE_BASE_ATR_MULT)

    if isinstance(payload.get("offset_bps"), int):
        prof["offset_bps"] = int(payload["offset_bps"])
    if payload.get("pcts"):
        with suppress(Exception):
            prof["pcts"] = [float(x) for x in payload["pcts"]]
    if payload.get("splits"):
        with suppress(Exception):
            prof["splits"] = [float(x) for x in payload.get("splits")]
    if payload.get("atr_mult") is not None:
        with suppress(Exception):
            prof["atr_mult"] = float(payload["atr_mult"])

    return prof, {"price": price, "atr": atr, "adx": adx}, profile_name

# --- pause windows ---
def _parse_pause_windows(spec: str) -> List[Tuple[int, int]]:
    windows: List[Tuple[int, int]] = []
    for part in [p.strip() for p in (spec or "").split(",") if p.strip()]:
        p = part.rstrip("Zz")
        if "-" not in p:
            continue
        a, b = [x.strip() for x in p.split("-", 1)]
        def _hm(s: str) -> Optional[int]:
            try:
                hh, mm = s.split(":")
                h = int(hh); m = int(mm)
                if 0 <= h < 24 and 0 <= m < 60:
                    return h * 60 + m
            except Exception:
                return None
            return None
        s = _hm(a); e = _hm(b)
        if s is None or e is None:
            continue
        windows.append((s, e))
    return windows

def _in_pause_window_utc(now: Optional[time.struct_time] = None) -> bool:
    if not TRAIL_PAUSE_WINDOWS:
        return False
    try:
        t = now or time.gmtime()
        cur = t.tm_hour * 60 + t.tm_min
        for s, e in _parse_pause_windows(TRAIL_PAUSE_WINDOWS):
            if s <= e:
                if s <= cur < e:
                    return True
            else:
                if cur >= s or cur < e:
                    return True
    except Exception:
        return False
    return False

@router.post("/manage-once")
async def manage_once(request: Request, payload: Dict[str, Any] = Body(...)):
    try:
        if not getattr(request.state, "_signed_override", False):
            _require_bearer(request)
    except Exception:
        _require_bearer(request)

    symbol = (payload.get("symbol") or "").upper().strip()
    if not symbol:
        raise HTTPException(status_code=422, detail="missing symbol")
    try:
        from binance.client import Client  # type: ignore
    except Exception as e:
        return {"ok": True, "delegated": False, "skipped": True, "reason": "binance_client_import_failed", "detail": str(e)}
    api_key = os.getenv("BINANCE_API_KEY", "").strip()
    api_sec = os.getenv("BINANCE_API_SECRET", "").strip()
    if not api_key or not api_sec:
        return {"ok": True, "delegated": False, "skipped": True, "reason": "binance_keys_missing"}
    client = Client(api_key, api_sec)
    _align_position_mode(client)

    try:
        positions = client.futures_position_information(symbol=symbol)
        has_any = any(abs(float(p.get("positionAmt") or 0.0)) > 0 for p in positions)
        if not has_any:
            return {"ok": True, "skipped": True, "reason": "no_open_position"}
    except Exception as e:
        return {"ok": False, "error": "position_fetch_failed", "detail": str(e)}

    tick, step = _get_filters(client, symbol)

    prof, indicators, prof_name = await _select_profile_for_symbol(client, symbol, payload)
    if _in_pause_window_utc():
        return {
            "ok": True,
            "skipped": True,
            "reason": "paused_window",
            "profile": prof_name,
            "indicators": indicators,
        }

    try:
        res = await _smart_manage_now(
            symbol,
            offset_bps=int(prof.get("offset_bps") or PROFILE_BASE_BE_BPS),
            pcts=list(prof.get("pcts") or PROFILE_BASE_PCTS),
            splits=list(prof.get("splits") or PROFILE_BASE_SPLITS),
            atr_mult=(prof.get("atr_mult") if prof.get("atr_mult") is not None else PROFILE_BASE_ATR_MULT),
        )
    except Exception as e:
        return {"ok": False, "error": "smart_manage_now_failed", "detail": str(e)}
    return {"ok": True, "delegated": True, "profile": prof_name, "indicators": indicators, "result": res}

@router.get("/manage-once/signed", tags=["manager"])
async def manage_once_signed(symbol: str = Query(...), exp: str = Query(...), sig: str = Query(...), request: Request = None):
    if not _verify_signed_params(symbol, exp, sig, "/manage-once/signed"):
        raise HTTPException(status_code=401, detail="Bad or expired signature")
    class _Req:
        state = type("S", (), {"_signed_override": True})
    payload = {
        "symbol": str(symbol).upper(),
        "offset_bps": int(os.getenv("PROFILE_BASE_BE_BPS", os.getenv("BE_BPS", "5"))),
        "pcts": [float(x) for x in (os.getenv("PROFILE_BASE_PCTS", "3,6,10,16")).split(",") if x.strip()],
        "splits": [float(x) for x in (os.getenv("PROFILE_BASE_SPLITS", "0.25,0.25,0.25,0.25")).split(",") if x.strip()],
        "atr_mult": float(os.getenv("PROFILE_BASE_ATR_MULT", os.getenv("TRAIL_ATR_MULT", "1.6"))),
    }
    return await manage_once(_Req(), payload)  # type: ignore

# ----------------- Mount router (כבר קיים מעל) & STARTUP/SHUTDOWN -----------------
app.include_router(router)

@app.on_event("startup")
async def _on_startup():
    try:
        # מוודא שקצות הציבור זמינים (topk/now) גם אם ראוטרים חיצוניים לא נטענו
        _ensure_public_fallbacks()
    except Exception as e:
        logger.warning("public_fallbacks.ensure.failed: %s", e)

    # פותרים כתובות Binance ברקע (לא חוסם את ההעלאה)
    try:
        asyncio.create_task(_resolve_binance_endpoints())
    except Exception as e:
        logger.warning("binance_endpoints.bootstrap.failed: %s", e)

    # מגדיר Webhook לטלגרם (אם מופעל ב-ENV) – ברקע כדי לא לעכב startup
    try:
        asyncio.create_task(_ensure_telegram_webhook())
    except Exception as e:
        logger.warning("telegram_webhook.ensure.failed: %s", e)

    logger.info("startup.ready v=%s http2=%s redis=%s",
                APP_VERSION, _http2_enabled_runtime(), bool(aioredis and REDIS_URL))

    # Auto-load routes package (depending on mode)
    if ROUTES_AUTOLOAD:
        if ROUTES_AUTOLOAD_MODE in ("background", "bg", "async"):
            try:
                asyncio.create_task(asyncio.to_thread(_routes_autoload_now))
                logger.info("routes_autoload: scheduled (background)")
            except Exception as e:
                logger.warning("routes_autoload: background schedule failed: %s", e)
                # fallback to immediate
                _routes_autoload_now()
        else:
            # eager (safe & deterministic before traffic)
            _routes_autoload_now()

@app.on_event("shutdown")
async def _on_shutdown():
    # סוגרים httpx.AsyncClient משותף
    with suppress(Exception):
        cli = getattr(app.state, "shared_async_client", None)
        if cli and not cli.is_closed:
            await cli.aclose()

    # סוגרים Redis אם נפתח
    with suppress(Exception):
        r = getattr(app.state, "redis", None)
        if r:
            await r.aclose()

    logger.info("shutdown.complete")

# ----------------- LIGHTWEIGHT ROOTS (תמיד זמינים) -----------------
@app.get("/", include_in_schema=False)
async def root():
    return {
        "ok": True,
        "name": APP_TITLE,
        "version": APP_VERSION,
        "ts": int(time.time()),
        "ui": {"poll_ms": UI_POLL_MS, "idle_stop_sec": UI_IDLE_STOP_SEC},
    }

@app.get("/version", tags=["public"])
async def version():
    return {"name": APP_TITLE, "version": APP_VERSION}

# ==================== __main__ ====================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=_port(),
        log_level=LOG_LEVEL.lower(),
        reload=False,
        workers=int(os.getenv("UVICORN_WORKERS", "1") or 1),
        http="h11" if not _http2_enabled_runtime() else "auto",
    )




















































































































































































































































































































































































































































































































































































































































































































































































































































































































































































































































































































































































































































































































































































































































































































































































































































































































































































































































































































































































































































































































































































































































































































































































