# main.py
# -*- coding: utf-8 -*-
from __future__ import annotations

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
from fastapi import FastAPI, Request, HTTPException, Body, Query, APIRouter
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
    "TP_MAX_LADDERS": "3",
    "ENABLE_INDICATOR_EXIT": "1",
    "ADX_MIN": "18",
    "NO_PROGRESS_TIMEOUT_MIN": "30",
    "DAILY_LOSS_CAP_USDT": "150",
    "KILL_ON_CAP": "1",
    "PRICE_PROTECT": "1",
    "USE_WS": "1",
    "WS_KEEPALIVE_SEC": "25",
}
for _k, _v in _inline_env_defaults.items():
    os.environ.setdefault(_k, _v)

# ========= Notification policy =========
ONLY_TRADE_NOTIFICATIONS = os.getenv("ONLY_TRADE_NOTIFICATIONS", "1").lower() in ("1", "true", "yes", "on")
STARTUP_NOTIFY_ENABLE = os.getenv("STARTUP_NOTIFY_ENABLE", "0").lower() in ("1", "true", "yes", "on")
HEALTH_TP1_ENABLE = os.getenv("HEALTH_TP1_ENABLE", "0").lower() in ("1", "true", "yes", "on")

# ========= Auto ranges defaults (lev/budget) =========
AUTO_LEV_MIN = int(os.getenv("AUTO_LEV_MIN", "15") or 15)
AUTO_LEV_MAX = int(os.getenv("AUTO_LEV_MAX", "25") or 25)
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
IDEM_TTL_SEC = int(os.getenv("IDEM_TTL_SEC", "60") or 60)
USE_REDIS_IDEM = os.getenv("USE_REDIS_IDEM", "0").lower() in ("1", "true", "yes", "on")
TRAIL_PAUSE_WINDOWS = (os.getenv("TRAIL_PAUSE_WINDOWS", "") or "").strip()   # e.g. "22:00-02:00Z,11:30-12:00Z"
AUTO_TRAIL_ADX_MIN = float(os.getenv("AUTO_TRAIL_ADX_MIN", "0") or 0.0)
AUTO_TRAIL_ATRPCT_MAX = float(os.getenv("AUTO_TRAIL_ATRPCT_MAX", "0") or 0.0)

# === תחזוקת TP: Merge / Rearm / Anti-stale (imports + ENV) ===
try:
    from utils.tp_helper import (  # type: ignore
        maybe_merge_close_tps, maybe_rearm_on_bounce, anti_stale_nudge
    )
except Exception:
    maybe_merge_close_tps = maybe_rearm_on_bounce = anti_stale_nudge = None  # type: ignore

TP_MERGE_TICK_BAND = int(os.getenv("TP_MERGE_TICK_BAND", "1") or 1)
TP_REARM_TICK = int(os.getenv("TP_REARM_TICK", "1") or 1)
ANTI_STALE_MIN = int(os.getenv("ANTI_STALE_MIN", "15") or 15)  # דקות
ANTI_STALE_NUDGE_BPS = float(os.getenv("ANTI_STALE_NUDGE_BPS", "2") or 2.0)

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

# (NEW) מעקב In-memory: כניסה ראשונית ו-TP1 timing
# ייווצרו אם לא קיימים (טעינה/רילוד)
app.state.pos_open_ts = getattr(app.state, "pos_open_ts", {})
app.state.tp1_hit_ts = getattr(app.state, "tp1_hit_ts", {})

# ===== UltraTop integration (mount under /ultra only if enabled) =====
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

# ---------- Safe HEAD & /readyz (first middleware) ----------
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
REQUIRE_REDIS = os.getenv("REQUIRE_REDIS", "1").lower() in ("1", "true", "yes", "on")
CONFIRMSTORE_ENABLE = os.getenv("CONFIRMSTORE_ENABLE", "0").lower() in ("1", "true", "yes", "on")

# ====== Public Cache & Rate limit config ======
PUBLIC_CACHE_MAX_AGE = int(os.getenv("PUBLIC_CACHE_MAX_AGE", "20") or "20")
PUBLIC_CACHE_PATHS = [p.strip() for p in (os.getenv("PUBLIC_CACHE_PATHS", "/scan/public-topk,/scan/public-now,/topk").split(",")) if p.strip()]
RATE_LIMIT_ENABLE = os.getenv("RATE_LIMIT_ENABLE", "1").lower() in ("1", "true", "yes", "on")
PUBLIC_TOPK_RPS = int(os.getenv("PUBLIC_TOPK_RPS", "2") or "2")
PUBLIC_TOPK_WINDOW = int(os.getenv("PUBLIC_TOPK_WINDOW", "3") or "3")
PUBLIC_NOW_RPS = int(os.getenv("PUBLIC_NOW_RPS", "2") or "2")
PUBLIC_NOW_WINDOW = int(os.getenv("PUBLIC_NOW_WINDOW", "3") or "3")

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

# HMAC secret for signed links
HMAC_SECRET = (os.getenv("WEBHOOK_HMAC_SECRET") or os.getenv("OPS_SIGN_SECRET") or "").strip()

# ==================== Security helpers ====================
def _sign_hex(secret_hex_or_text: str, payload: bytes) -> str:
    # שדרוג: נסיון לפענח hex באורך 64, ואם נכשל — להשתמש כטקסט רגיל
    key: bytes
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
        # FIX: גרש לא חוקי תוקן
        cls._items.pop(str(ticket_id), None)


# ==================== (Part 2) ====================

import httpx  # keep import in scope for Part 2

# ==================== Shared HTTP and Redis ====================
try:
    import redis.asyncio as aioredis  # type: ignore
except Exception:
    aioredis = None  # type: ignore

_shared_client_lock = threading.Lock()

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
            max_connections=int(os.getenv("HTTP_MAX_CONNECTIONS", "50")),
            max_keepalive_connections=int(os.getenv("HTTP_MAX_KEEPALIVE", "200")),
        )
        cli = httpx.AsyncClient(timeout=timeout, limits=limits, headers={"User-Agent": f"algogpt/{APP_VERSION}"})
        app.state.shared_async_client = cli
        return cli

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
    if os.getenv("ENABLE_HSTS", "0").lower() in ("1", "true", "yes", "on"):
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains; preload")
    return resp

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
    ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or (request.client.host if request.client else "0.0.0.0")
    rules = {
        "/scan/public-topk": (PUBLIC_TOPK_RPS, PUBLIC_TOPK_WINDOW),
        "/scan/public-now": (PUBLIC_NOW_RPS, PUBLIC_NOW_WINDOW),
        "/topk": (PUBLIC_TOPK_RPS, PUBLIC_TOPK_WINDOW),
    }
    for k, (rps, win) in rules.items():
        if p.startswith(k):
            over = await _rl_hit(k, int(win), int(rps) * int(win), ip)
            if over:
                return JSONResponse({"ok": False, "error": "rate_limited"}, status_code=429)
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
        etag = '"' + hashlib.md5(body).hexdigest() + '"'
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
            return fresh
    except Exception:
        return resp
    return resp

# ==================== Telegram helpers ====================
def _md_html(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

async def _send_telegram_html(text: str, approve_url: Optional[str] = None,
                              reject_url: Optional[str] = None, preview_url: Optional[str] = None) -> Dict[str, Any]:
    # --- idempotency on Redis to avoid duplicate sends within IDEM_TTL_SEC ---
    if USE_REDIS_IDEM and IDEM_TTL_SEC > 0 and (aioredis and REDIS_URL):
        try:
            r = await _get_redis_cached()
            if r:
                key_payload = json.dumps({"t": text, "a": approve_url, "r": reject_url, "p": preview_url}, ensure_ascii=False, separators=(",", ":"))
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
    if approve_url or reject_url or preview_url:
        row: List[Dict[str, Any]] = []
        if preview_url:
            row.append({"text": "👁 Preview", "url": preview_url})
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
    for url in ("https://fapi.binance.com/fapi/v1/ticker/price", "https://api.binance.com/api/v3/ticker/price"):
        try:
            cli = _get_shared_async_client()
            r = await cli.get(url, params={"symbol": sym}, timeout=httpx.Timeout(10.0))
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

# >>> KL HTTP HELPER (לוקלי; מביא klines ב-HTTP לצ'קליסט)
async def _fetch_klines_http(symbol: str, interval: str = "15m", limit: int = 120) -> List[List[Any]]:
    """
    מחזיר klines בפורמט binance (מערכים) דרך HTTP. Best-effort בלבד.
    """
    sym = symbol.upper()
    if not sym.endswith("USDT"):
        sym += "USDT"
    url = "https://fapi.binance.com/fapi/v1/klines"
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

# ==================== (Part 3) ====================

# ==================== Execute trade helpers ====================
async def _execute_trade(ticket: Dict[str, Any]) -> Dict[str, Any]:
    with suppress(Exception):
        from utils.trade_executor import place_futures_market  # type: ignore
        return await place_futures_market(ticket)
    try:
        from binance.client import Client  # type: ignore
    except Exception as e:
        return {"ok": False, "error": "binance_client_import_failed", "detail": str(e)}
    try:
        api_key = os.getenv("BINANCE_API_KEY", "").strip()
        api_sec = os.getenv("BINANCE_API_SECRET", "").strip()
        if not api_key or not api_sec:
            return {"ok": False, "error": "binance_keys_missing"}
        client = Client(api_key, api_sec)
        _align_position_mode(client)
        symbol = str(ticket.get("symbol", "")).upper()
        side = str(ticket.get("side", "")).upper()
        qty = float(ticket.get("qty") or ticket.get("quantity") or 0)
        leverage = int(ticket.get("leverage") or ticket.get("lev") or 1)
        if not (symbol and side in ("BUY", "SELL") and qty > 0 and leverage > 0):
            return {"ok": False, "error": "bad_ticket_params"}
        with suppress(Exception):
            client.futures_change_leverage(symbol=symbol, leverage=leverage)
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
            return {"ok": True, "exchange": "binance_futures", "order": order}
        except Exception as e1:
            if not _is_code_4061(e1):
                raise
            try:
                order = client.futures_create_order(**base_kwargs)
                return {"ok": True, "exchange": "binance_futures", "order": order, "retry": "no_positionSide"}
            except Exception as e2:
                try:
                    retry2_kwargs = dict(base_kwargs)
                    retry2_kwargs["positionSide"] = "LONG" if side == "BUY" else "SHORT"
                    order = client.futures_create_order(**retry2_kwargs)
                    return {"ok": True, "exchange": "binance_futures", "order": order, "retry": "derived_positionSide"}
                except Exception as e3:
                    return {"ok": False, "error": "order_failed", "detail": str(e3), "first_error": str(e1), "second_error": str(e2)}
    except Exception as e:
        return {"ok": False, "error": "order_failed", "detail": str(e)}

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
        return {"ok": False, "error": "execute_trade_live_missing"}
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
        return {"ok": False, "error": "bad_ticket_params"}
    try:
        from binance.client import Client  # type: ignore
        api_key = os.getenv("BINANCE_API_KEY", "").strip()
        api_sec = os.getenv("BINANCE_API_SECRET", "").strip()
        if api_key and api_sec and leverage > 0 and symbol:
            cli_ = Client(api_key, api_sec)
            _align_position_mode(cli_)
            with suppress(Exception):
                cli_.futures_change_leverage(symbol=symbol, leverage=leverage)
    except Exception:
        pass
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
        res = await execute_trade_live(**clean)  # type: ignore
        return res
    except Exception as e:
        return {"ok": False, "error": "armed_execute_failed", "detail": f"{e}", "trace": traceback.format_exc()}

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
    # TODO: add your single-execution logic here.
    return JSONResponse({"ok": True, "handled_once": True}, status_code=200)

def _require_bearer(request: Request) -> None:
    if os.getenv("PROTECT_APPROVE_ROUTES", "1").lower() not in ("1", "true", "yes", "on"):
        return
    if not API_BEARER_TOKEN:
        raise HTTPException(status_code=503, detail="Route protection enabled but API_BEARER_TOKEN missing")
    auth = request.headers.get("Authorization", "")
    if not (auth.startswith("Bearer ") and auth.split(" ", 1)[1].strip() == API_BEARER_TOKEN):
        raise HTTPException(status_code=401, detail="Unauthorized")

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

    # Smart ETA for TP levels (best-effort)
    if ETA_SMART_ENABLE and (payload.get("tp1") or payload.get("tp2") or payload.get("tp3")):
        price_now = None
        with suppress(Exception):
            price_now = await get_last_price_async(symbol)
        def _smart(symbol: str, side: str, price_now: Optional[float], tps: List[Optional[float]]) -> Dict[str, Any]:
            if not price_now:
                return {}
            out: Dict[str, Any] = {}
            for i, tp in enumerate(tps, start=1):
                if tp and tp > 0:
                    dist_bps = abs((tp - price_now) / price_now) * 10_000
                    out[f"eta_tp{i}_min"] = max(1, int(dist_bps / max(1, ETA_VELOCITY_WINDOW)))
            out.setdefault("eta_open_min", out.get("eta_tp1_min", 2))
            return out
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

    # Persist ticket
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
        if REQUIRE_REDIS:
            raise HTTPException(status_code=503, detail="storage_unavailable: redis_required")
        if CONFIRMSTORE_ENABLE:
            with suppress(Exception):
                ConfirmStore.create(dict(req_body))
            persisted = True

    # Metrics: approvals_created_total++
    with suppress(Exception):
        inc_approvals_created()

    # Soft slip-estimate gauge (best-effort)
    with suppress(Exception):
        # get price + book spread
        cli = _get_shared_async_client()
        px = await get_last_price_async(symbol) or 0.0
        spread_pct = 0.0
        try:
            r = await cli.get("https://fapi.binance.com/fapi/v1/ticker/bookTicker", params={"symbol": symbol}, timeout=httpx.Timeout(6.0))
            if r.status_code == 200:
                bd = r.json()
                bid = float(bd.get("bidPrice") or 0.0)
                ask = float(bd.get("askPrice") or 0.0)
                if bid > 0 and ask > 0:
                    spread_pct = abs(ask - bid) / ((ask + bid) / 2.0) * 100.0
        except Exception:
            pass
        # atr% from klines
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
        est_bps = estimate_impact_slip_bps(spread_pct, atr_pct, notional, max_bps=float(os.getenv("IMPACT_SLIP_BPS_MAX", "25") or 25.0))
        set_last_slip_estimate_bps(float(est_bps))

    base = PUBLIC_HOST.rstrip("/") if PUBLIC_HOST else (str(request.base_url).rstrip("/") if request else "")
    preview_url = _build_signed_link(base, "/ops/ui/ticket/signed", tid, ttl_sec=900, action="preview")
    approve_url = _build_signed_link(base, "/ops/approve/signed", tid, ttl_sec=900, action="approve")
    reject_url = _build_signed_link(base, "/ops/reject/signed", tid, ttl_sec=900, action="reject")

    lines = [
        "⚠️ <b>Approval Needed</b>",
        f"• Ticket: <code>{_md_html(tid)}</code>",
        f"• {_md_html(symbol)} {_md_html(side)} qty=<code>{_md_html(qty)}</code> lev=<code>{_md_html(lev)}</code>",
    ]
    for i in (1, 2, 3):
        if req_body.get(f"tp{i}") is not None:
            row = f"• TP{i}: <code>{req_body[f'tp{i}']}</code>"
            if req_body.get(f"eta_tp{i}_min") is not None:
                row += f"  ETA:<code>{req_body[f'eta_tp{i}_min']}m</code>"
            if req_body.get(f"prob_tp{i}_pct") is not None:
                row += f"  P(s):<code>{req_body[f'prob_tp{i}_pct']}%</code>"
            lines.append(row)
    if req_body.get("sl") is not None:
        lines.append(f"• SL: <code>{req_body['sl']}</code>")
    if req_body.get("tp_splits"):
        lines.append(f"• TP Splits: <code>{req_body['tp_splits']}</code>")
    if req_body.get("prob_overall_pct") is not None:
        lines.append(f"• Success %: <code>{req_body['prob_overall_pct']}%</code>")
    if req_body.get("expiry_ts") is not None:
        lines.append(f"• Expires: <code>{req_body['expiry_ts']}</code>")
    if note:
        lines.append(f"• Note: {_md_html(note)}")
    lines.append("— — —")
    lines.append("בחר:")
    pretty = "\n".join(lines)
    tg_resp = await _send_telegram_html(pretty, approve_url=approve_url or None, reject_url=reject_url or None, preview_url=preview_url or None)

    return {
        "ok": True,
        "ticket_id": tid,
        "approve_url": approve_url,
        "reject_url": reject_url,
        "preview_url": preview_url,
        "telegram_result": tg_resp,
    }

def _decide_flow_by_mode(ticket: Dict[str, Any]) -> str:
    # prefer explicit mode hint in note
    mode = _parse_mode(ticket.get("note"))
    if mode in ("MARKET", "HYBRID", "AUTO"):
        return mode
    # optional external policy from utils.exec_decider
    if callable(decide_execution_mode):
        with suppress(Exception):
            m = decide_execution_mode(ticket)  # type: ignore
            if isinstance(m, str) and m.upper() in ("MARKET", "HYBRID", "AUTO"):
                return m.upper()
    # fallback
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
    _require_bearer(request)
    rec, _ = await _load_ticket(ticket_id)
    if not rec and CONFIRMSTORE_ENABLE:
        with suppress(Exception):
            for it in ConfirmStore.pending():
                if str(it.get("ticket_id")) == str(ticket_id):
                    rec = it.get("req") or it
                    break
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

# --- בטוח: עטיפת smart_manage_now (אם קיים במודול חיצוני) ---
async def _smart_manage_now(symbol: str,
                            offset_bps: Optional[int] = None,
                            pcts: Optional[List[float]] = None,
                            splits: Optional[List[float]] = None,
                            atr_mult: Optional[float] = None) -> Dict[str, Any]:
    """
    Best-effort wrapper: אם קיים מימוש ב-routes.manager/app.manager נשתמש בו.
    אחרת נחזור עם skipped=True ולא נכשיל את הזרימה.
    """
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
        # במקרה של sync
        return await asyncio.to_thread(lambda: fn(**params))  # type: ignore[misc]
    except Exception as e:
        return {"ok": False, "error": "smart_manage_now_failed", "detail": f"{e}"}

async def _approve_core(ticket_id: str):
    ticket, source = await _load_ticket(ticket_id)
    if not ticket:
        return _html("⚠️ קישור שגוי או שפג תוקף האישור.")
    with suppress(Exception):
        for k in ("blocked_by_rr_min", "blocked_by_velocity", "velocity_error"):
            ticket.pop(k, None)

    # --- Checklist Gate (ENTRY_SCORE_MIN) ---
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
    # --- סוף ה-Checklist Gate ---

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
    if (not ok) and flow in ("HYBRID", "AUTO") and (os.getenv("PROPOSE_BLOCK_ON_FAIL", "0").lower() not in ("1", "true", "yes", "on")):
        retry_res = await _execute_trade(ticket)
        ok = bool(retry_res.get("ok"))
        exec_res = {"primary": "HYBRID", "fallback_market": retry_res, "primary_error": exec_res}

    # === Metrics ===
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
                "offset_bps": int(os.getenv("SMART_MANAGE_BE_OFFSET_BPS", os.getenv("TP_BE_OFFSET_BPS", "5"))),
                "pcts": [float(x) for x in (os.getenv("SMART_MANAGE_PCTS") or "4,8,16").split(",") if x.strip()],
                "splits": [float(x) for x in (os.getenv("SMART_MANAGE_SPLITS") or "0.30,0.30,0.40").split(",") if x.strip()],
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
    ticket, source = await _load_ticket(ticket_id)
    if not ticket:
        return _html("⚠️ קישור שגוי או שפג תוקף האישור/דחייה.")

    # === Metrics ===
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

# ==================== Digest/UI/etc. ====================
@router.get("/ops/ui/pending")
async def ui_pending(request: Request = None):
    _require_bearer(request)
    base = PUBLIC_HOST if PUBLIC_HOST else (str(request.base_url).rstrip("/") if request else "")
    items: List[Dict[str, Any]] = []
    if aioredis and REDIS_URL:
        with suppress(Exception):
            r = await _get_redis_cached()
            if r:
                cursor: Any = 0
                while True:
                    res = await r.scan(cursor, match=f"{NS}:ticket:*", count=200)
                    cursor = int(res[0]) if not isinstance(res[0], int) else res[0]
                    keys = res[1]
                    for k in keys:
                        raw = await r.get(k)
                        if not raw:
                            continue
                        obj = json.loads(raw)
                        req = obj.get("req") or {}
                        items.append(req)
                    if cursor == 0:
                        break
    if CONFIRMSTORE_ENABLE:
        with suppress(Exception):
            for it in ConfirmStore.pending() or []:
                items.append(it.get("req") or it)
    if not items:
        return _html("אין כרטיסים ממתינים כרגע.")
    rows = []
    for t in items:
        raw_tid = str(t.get("ticket_id", ""))
        link = f"{base}/ops/ui/ticket?ticket_id={raw_tid}"
        rows.append(
            f"<tr>"
            f"<td style='padding:.4rem .6rem'><a href='{link}'>👁 {_md_html(raw_tid)}</a></td>"
            f"<td style='padding:.4rem .6rem'>{_md_html(str(t.get('symbol','')))}</td>"
            f"<td style='padding:.4rem .6rem'>{_md_html(str(t.get('side','')))}</td>"
            f"<td style='padding:.4rem .6rem'>{_md_html(str(t.get('qty','')))}</td>"
            f"<td style='padding:.4rem .6rem'>{_md_html(str(t.get('leverage','')))}</td>"
            f"</tr>"
        )
    body = (
        "<!doctype html><meta charset='utf-8'>"
        "<body style='font-family:sans-serif;max-width:880px;margin:2rem auto;line-height:1.5'>"
        "<h2 style='margin:0 0 1rem 0'>Pending Approval Tickets</h2>"
        "<table style='border-collapse:collapse;width:100%;border:1px solid #eee'>"
        "<thead><tr style='background:#fafafa'><th style='text-align:left;padding:.4rem .6rem'>Ticket</th>"
        "<th style='text-align:left;padding:.4rem .6rem'>Symbol</th>"
        "<th style='text-align:left;padding:.4rem .6rem'>Side</th>"
        "<th style='text-align:left;padding:.4rem .6rem'>Qty</th>"
        "<th style='text-align:left;padding:.4rem .6rem'>Lev</th>"
        "</tr></thead>"
        "<tbody>" + "\n".join(rows) + "</tbody></table>"
        "</body>"
    )
    return HTMLResponse(body)

# =========== Guard Smoke (סינגל—כפילות הוסרה) ===========
@router.post("/guard/smoke/run")
async def guard_smoke_run(request: Request, symbols: Optional[str] = Body(None)):
    _require_bearer(request)
    try:
        from utils.guard_stop import ensure_protective_stop  # type: ignore
    except Exception:
        raise HTTPException(status_code=501, detail="ensure_protective_stop() not available")
    if isinstance(symbols, str) and symbols.strip():
        sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    else:
        sym_list = WATCHLIST[:]
    if not sym_list:
        raise HTTPException(status_code=400, detail="no symbols to check")
    results: Dict[str, Any] = {}
    emergencies: List[str] = []
    for s in sym_list:
        try:
            res = ensure_protective_stop(s, prefer_mode="quantities")
            results[s] = res
            flag = False
            try:
                if isinstance(res, dict):
                    flag = bool(res.get("emergency")) or bool(res.get("placed")) or (str(res.get("action", "")).lower() in ("emergency", "place"))
            except Exception:
                pass
            if flag:
                emergencies.append(s)
        except Exception as e:
            results[s] = {"ok": False, "error": str(e)}
    if emergencies and not ONLY_TRADE_NOTIFICATIONS:
        await _send_telegram_html("🚨 <b>Smoke Guard</b> · Emergency protective SL placed\n• Symbols: <code>" + ",".join(emergencies) + "</code>")
    return {"ok": True, "checked": sym_list, "emergencies": emergencies, "results": results}

# ==================== Indicator & profile helpers ====================
PROFILE_AUTO_SELECT = os.getenv("PROFILE_AUTO_SELECT", "1").lower() in ("1", "true", "yes", "on")

PROFILE_BASE_BE_BPS = int(os.getenv("PROFILE_BASE_BE_BPS", "5"))
PROFILE_BASE_PCTS = [float(x) for x in (os.getenv("PROFILE_BASE_PCTS", "4,8,16")).split(",") if x.strip()]
PROFILE_BASE_SPLITS = [float(x) for x in (os.getenv("PROFILE_BASE_SPLITS", "0.30,0.30,0.40")).split(",") if x.strip()]
PROFILE_BASE_ATR_MULT = float(os.getenv("PROFILE_BASE_ATR_MULT", "0") or 0) or None

PROFILE_EXTREME_BE_BPS = int(os.getenv("PROFILE_EXTREME_BE_BPS", "2"))
PROFILE_EXTREME_PCTS = [float(x) for x in (os.getenv("PROFILE_EXTREME_PCTS", "2,4,8")).split(",") if x.strip()]
PROFILE_EXTREME_SPLITS = [float(x) for x in (os.getenv("PROFILE_EXTREME_SPLITS", "0.25,0.35,0.40")).split(",") if x.strip()]
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

def _get_filters(client, symbol: str) -> Tuple[float, float]:
    tick = 0.1
    step = 0.001
    try:
        ex = client.futures_exchange_info()
        for s in ex.get("symbols", []):
            if s.get("symbol") == symbol:
                for f in s.get("filters", []):
                    if f.get("filterType") == "PRICE_FILTER":
                        tick = float(f.get("tickSize", tick))
                    if f.get("filterType") == "LOT_SIZE":
                        step = float(f.get("stepSize", step))
                break
    except Exception:
        pass
    return tick, step

# ===== Profile select for /manage-once =====
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
            prof["splits"] = [float(x) for x in payload["splits"]]
    if payload.get("atr_mult") is not None:
        with suppress(Exception):
            prof["atr_mult"] = float(payload["atr_mult"])

    return prof, {"price": price, "atr": atr, "adx": adx}, profile_name

# --- pause windows parser ---
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

    pos_amt = 0.0
    entry_price = None
    side_txt = None
    try:
        positions = client.futures_position_information(symbol=symbol)
        for p in positions:
            amt = float(p.get("positionAmt") or 0.0)
            if abs(amt) > 0:
                pos_amt = amt
                entry_price = float(p.get("entryPrice") or 0.0)
                side_txt = "BUY" if amt > 0 else "SELL"
                break
    except Exception as e:
        return {"ok": False, "error": "position_fetch_failed", "detail": str(e)}

    if not side_txt or not entry_price or abs(pos_amt) <= 0:
        return {"ok": True, "skipped": True, "reason": "no_open_position"}

    tick, step = _get_filters(client, symbol)
    price_now = None
    with suppress(Exception):
        tick_data = client.futures_symbol_ticker(symbol=symbol)
        if tick_data and "price" in tick_data:
            price_now = float(tick_data["price"])
    base_price = price_now or entry_price

    prof, indicators, profile_name = await _select_profile_for_symbol(client, symbol, payload)
    offset_bps = int(prof["offset_bps"])
    pcts: List[float] = list(prof["pcts"])
    splits: List[float] = list(prof["splits"])
    atr_mult = prof["atr_mult"]

    if len(pcts) != len(splits) or not (0.999 <= sum(splits) <= 1.001):
        raise HTTPException(status_code=422, detail="pcts/splits mismatch or splits must sum to 1.0")
    if any(x <= 0 for x in pcts):
        raise HTTPException(status_code=422, detail="pcts must be > 0")
    if any(x <= 0 for x in splits):
        raise HTTPException(status_code=422, detail="splits must be > 0")

    # === החלפה: ניהול בעזרת tp_helper (BE + TP + Trail) ===
    try:
        from utils.tp_helper import manage_once_place_all  # type: ignore
    except Exception as e:
        return {"ok": False, "error": "tp_helper_missing", "detail": str(e)}

    try:
        res = manage_once_place_all(
            client=client,
            symbol=symbol,
            side_txt=side_txt,
            entry_price=float(entry_price),
            price_now=float(base_price),
            qty_abs=float(abs(pos_amt)),
            tick=float(tick),
            step=float(step),
            offset_bps=int(offset_bps),
            pcts=[float(x) for x in pcts],
            splits=[float(x) for x in splits],
            atr=float(indicators.get("atr", 0.0)),
            atr_mult=atr_mult if atr_mult is not None else None,
            working_type=os.getenv("BINANCE_WORKING_TYPE", "MARK_PRICE"),
            coid_builder=build_client_order_id,
            dry_run=False,
        )
    except Exception as e:
        return {"ok": False, "error": "manage_once_place_all_failed", "detail": f"{e}"}

    result = {
        "ok": bool(res.get("ok")),
        "delegated": False,
        "symbol": symbol,
        "side": side_txt,
        "entry": entry_price,
        "be_stop_price": res.get("computed", {}).get("be_price"),
        "tp": res.get("tp"),
        "trail": res.get("trail"),
        "profile": {"name": profile_name, "offset_bps": offset_bps, "pcts": pcts, "splits": splits, "atr_mult": atr_mult},
        "indicators": {
            "adx": round(float(indicators.get("adx", 0.0)), 2),
            "atr": float(indicators.get("atr", 0.0)),
            "price": float(indicators.get("price", 0.0)),
            "atr_pct": round(float(indicators.get("atr", 0.0)) / float(indicators.get("price", 1.0)), 6) if indicators.get("price", 0.0) else 0.0,
            "thresholds": {"ADX_EXTREME_MIN": ADX_EXTREME_MIN, "ATRPCT_EXTREME_MIN": ATRPCT_EXTREME_MIN},
        },
    }
    return result

@router.get("/ops/digest/expired")
async def digest_expired(hours: int = Query(6, ge=1, le=48), request: Request = None):
    if os.getenv("PROTECT_DIGEST_ROUTES", "1").lower() in ("1", "true", "yes", "on"):
        _require_bearer(request)
    if not (aioredis and REDIS_URL and TELEGRAM_BOT_TOKEN and ADMIN_CHAT_ID):
        return {"ok": False, "error": "digest_dependencies_missing"}
    try:
        r = await _get_redis_cached()
        if not r:
            return {"ok": False, "error": "redis_unavailable"}
        key_good = f"{NS}:expired_log"
        key_bad = f"{NS}:expired_log_bad"
        items: List[str] = []
        with suppress(Exception):
            items.extend(await r.lrange(key_good, 0, 2000) or [])
        with suppress(Exception):
            items.extend(await r.lrange(key_bad, 0, 2000) or [])
        now = time.time()
        since = now - (hours * 3600)
        events: List[Dict[str, Any]] = []
        for it in items:
            try:
                obj = json.loads(it)
                if float(obj.get("ts", 0)) >= since:
                    events.append(obj)
            except Exception:
                continue
        events.sort(key=lambda x: x.get("ts", 0), reverse=True)
        total = len(events)
        if total == 0:
            await _send_telegram_html(f"ℹ️ No expired approvals in last {hours}h.")
            return {"ok": True, "sent": True, "count": 0}
        from collections import Counter as _C
        by_sym: _C = _C((str(e.get("symbol", "")).upper(), str(e.get("side", "")).upper()) for e in events)
        lines = [f"⏱️ <b>Expired approvals</b> (last {hours}h) · total: <b>{total}</b>"]
        for (sym, side), cnt in by_sym.most_common(20):
            lines.append(f"• {sym} {side}: <code>{cnt}</code>")
        lines.append("— — —")
        lines.append("<b>Last events</b>:")
        for e in events[:5]:
            t = int(e.get("ts", now))
            idem = e.get("idem", "")
            sym = str(e.get("symbol", "")).upper()
            side = str(e.get("side", "")).upper()
            lines.append(f"• {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(t))}Z · {sym} {side} · <code>{idem}</code>")
        await _send_telegram_html("\n".join(lines))
        return {"ok": True, "sent": True, "count": total}
    except Exception as e:
        logger.warning("digest_expired_failed: %s", e)
        return {"ok": False, "error": str(e)}

async def _telegram_webhook_core(request: Request) -> Dict[str, Any]:
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    TELEGRAM_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
    if TELEGRAM_WEBHOOK_SECRET and secret != TELEGRAM_WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Bad secret")
    _ = await request.body()
    return {"ok": True}

@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    return await _telegram_webhook_core(request)

@app.post("/telegram/hook")
async def telegram_hook_alias(request: Request):
    return await _telegram_webhook_core(request)

# ---- small ping route (listed in SECURITY_PUBLIC_PATHS) ----
@app.get("/telegram/ping", tags=["meta"])
async def telegram_ping():
    return {"ok": True, "ts": int(time.time())}

# ==================== Optional routers include ====================
for mod, tag in (
    ("routes.manager", "manager"),
    ("routes.price", "price"),
    ("routes.scan", "scan"),
    ("routes.scan_top_volume", "scan_top_volume"),
    ("routes.topk", "topk"),
    ("routes.health", "health"),
    ("routes.readyz", "readyz"),
    ("routes.meta", "meta"),
    ("routes.alerts", "alerts"),
    ("routes.ops_ui", "ops-ui"),
    ("routes.ops_flags", "ops-flags"),
    ("routes.position_ops", "position-ops"),
    ("routes.ops_digest", "ops-digest"),
    ("routes.aliases", "aliases"),
    ("routes.public", "Public Feed"),
    ("routes.public_web", "Public Feed"),
    ("routes.ai", "AI"),
    ("routes.metrics", "metrics"),   # <<< /metrics
):
    try:
        module = __import__(mod, fromlist=["router"])
        app.include_router(getattr(module, "router"), tags=[tag])
    except Exception as e:
        logger.warning("%s router not loaded: %s", mod, e)

app.include_router(router)

# ==================== Meta & Diagnostics ====================
@app.get("/", response_class=PlainTextResponse, tags=["meta"])
def root() -> str:
    name = os.getenv("APP_NAME", "algogpt")
    return f"{name} online"

@app.head("/", response_class=PlainTextResponse, tags=["meta"])
def root_head() -> str:
    return ""

@app.get("/meta/version", tags=["meta"])
def meta_version_fallback():
    return {"name": os.getenv("APP_NAME", "algogpt"), "version": os.getenv("ALGOGPT_VERSION", "dev"), "ts": int(time.time()), "ok": True}

@app.head("/meta/version", tags=["meta"])
def meta_version_head():
    return PlainTextResponse("", status_code=200)

@app.get("/health", tags=["meta"])
def health_fallback():
    boot = getattr(app.state, "boot_ts", None)
    return {"ok": True, "uptime_sec": int(time.time() - (boot or time.time()))}

@app.head("/health", tags=["meta"])
def health_head():
    return PlainTextResponse("", status_code=200)

@app.get("/readyz/strict", tags=["meta"])
async def readyz_strict():
    try:
        r = await _get_redis_cached()
        if r:
            await asyncio.wait_for(r.ping(), timeout=0.6)
    except Exception as e:
        logger.warning("readyz.strict.redis_ping_failed: %s", e)
        return PlainTextResponse("redis_fail", status_code=503)
    return PlainTextResponse("ok", status_code=200)

@app.get("/debug/env", tags=["debug"])
def debug_env(keys: Optional[str] = None) -> Dict[str, Any]:
    allowlist = set([k.strip() for k in (keys or "").split(",") if k.strip()]) if keys else set()
    safe: Dict[str, Any] = {}
    for k, v in os.environ.items():
        if any(x in k.upper() for x in ("SECRET", "TOKEN", "KEY", "PASSWORD")):
            continue
        if allowlist and k not in allowlist:
            continue
        safe[k] = v
    return {"ok": True, "env": safe}

@app.head("/debug/env", tags=["debug"])
def debug_env_head():
    return PlainTextResponse("", status_code=200)

# ---- NEW: /meta/routes (diagnostics) ----
@app.get("/meta/routes", tags=["meta"])
async def meta_routes(request: Request):
    # מוגן עם Bearer אם PROTECT_APPROVE_ROUTES=1
    with suppress(Exception):
        _require_bearer(request)
    routes = []
    for r in app.routes:
        methods = []
        try:
            methods = sorted(list(r.methods)) if getattr(r, "methods", None) else []
        except Exception:
            methods = []
        routes.append({
            "path": getattr(r, "path", None),
            "name": getattr(r, "name", None),
            "methods": methods,
        })
    return {"ok": True, "count": len(routes), "routes": routes}

# ---- NEW: /meta/telegram (diagnostics: info/dry/set/send [+ticket links]) ----
@app.get("/meta/telegram", tags=["meta"])
async def meta_telegram(
    request: Request,
    mode: str = Query("info", pattern="^(info|dry|set|send)$"),
    text: Optional[str] = Query("🔎 Diagnostics: test message"),
    chat_id: Optional[str] = Query(None, description="אם לא ניתן — ישתמש ב-ADMIN_CHAT_ID/TELEGRAM_CHAT_ID"),
    ticket_id: Optional[str] = Query(None, description="אופציונלי: אם קיים — נצרף קישורים חתומים approve/reject/preview"),
):
    """
    /meta/telegram?mode=info  -> מצב webhook + getMe
    /meta/telegram?mode=dry   -> dry-run: בונה payload בלבד (לא שולח)
    /meta/telegram?mode=set   -> setWebhook לפי ה-env
    /meta/telegram?mode=send  -> שולח הודעת בדיקה אמיתית (עם idem קל ב-Redis אם קיים)
    """
    with suppress(Exception):
        _require_bearer(request)

    token = TELEGRAM_BOT_TOKEN
    if not token:
        return {"ok": False, "error": "telegram_token_missing"}

    cli = _get_shared_async_client()

    async def tg_get(path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        try:
            r = await cli.get(f"https://api.telegram.org/bot{token}/{path}", params=params, timeout=httpx.Timeout(10.0))
            j = {}
            with suppress(Exception):
                j = r.json()
            return {"status": r.status_code, "data": j}
        except Exception as e:
            return {"status": 0, "error": str(e)}

    def _maybe_links() -> Dict[str, Optional[str]]:
        if not ticket_id:
            return {"preview_url": None, "approve_url": None, "reject_url": None}
        base = PUBLIC_HOST or get_internal_base()
        return {
            "preview_url": _build_signed_link(base, "/ops/ui/ticket/signed", ticket_id, ttl_sec=900, action="preview"),
            "approve_url": _build_signed_link(base, "/ops/approve/signed", ticket_id, ttl_sec=900, action="approve"),
            "reject_url": _build_signed_link(base, "/ops/reject/signed", ticket_id, ttl_sec=900, action="reject"),
        }

    if mode == "info":
        info = await tg_get("getWebhookInfo")
        me = await tg_get("getMe")
        return {
            "ok": True,
            "webhook": info,
            "me": me,
            "configured_host": PUBLIC_HOST,
            "auto_webhook": TELEGRAM_AUTO_WEBHOOK,
        }

    if mode == "dry":
        try:
            default_chat = ADMIN_CHAT_ID if ADMIN_CHAT_ID else None
            cid: Any = chat_id or default_chat
            if cid and str(cid).isdigit():
                cid = int(cid)
            payload = {
                "chat_id": cid,
                "text": text or "🔎 Diagnostics: dry-run",
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }
            # מציגים את הקישורים שיוצמדו (תצוגה מקדימה)
            payload.update({k: v for k, v in _maybe_links().items() if v})
            return {
                "ok": True,
                "dry_run": True,
                "note": "No message was sent. This is only a dry-run preview.",
                "payload_preview": payload,
                "has_chat_id": bool(cid),
                "hints": [
                    "Set TELEGRAM_CHAT_ID/ADMIN_CHAT_ID בסביבה או העבר ?chat_id=<id> בבקשה.",
                ],
            }
        except Exception as e:
            return {"ok": False, "error": f"dry_run_failed: {e}"}

    if mode == "set":
        host = PUBLIC_HOST
        secret = TELEGRAM_WEBHOOK_SECRET
        if not (host and secret):
            return {"ok": False, "error": "missing_host_or_secret", "need": {"PUBLIC_HOST": bool(host), "TELEGRAM_WEBHOOK_SECRET": bool(secret)}}
        try:
            r = await cli.post(
                f"https://api.telegram.org/bot{token}/setWebhook",
                json={
                    "url": f"{host}/telegram/webhook",
                    "secret_token": secret,
                    "drop_pending_updates": True,
                    "max_connections": 40,
                },
                timeout=httpx.Timeout(15.0),
            )
            data = {}
            with suppress(Exception):
                data = r.json()
            return {"ok": (r.status_code == 200 and data.get("ok") is True), "status": r.status_code, "result": data}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # mode == "send"
    try:
        msg_text = text or "🔎 Diagnostics: test message"
        links = _maybe_links()
        if chat_id:
            try:
                cid: Any = int(chat_id) if str(chat_id).isdigit() else chat_id
            except Exception:
                cid = chat_id

            # (FIX) Python uses 'and' not '&&'
            if USE_REDIS_IDEM and IDEM_TTL_SEC > 0 and (aioredis and REDIS_URL):
                try:
                    r = await _get_redis_cached()
                    if r:
                        key_payload = json.dumps({"t": msg_text, "cid": cid, "links": links}, ensure_ascii=False, separators=(",", ":"))
                        idem_key = f"{NS}:idem:tg:{hashlib.md5(key_payload.encode('utf-8')).hexdigest()}"
                        ok = await r.setnx(idem_key, "1")
                        if not ok:
                            return {"ok": True, "skipped": True, "reason": "idem_duplicate"}
                        with suppress(Exception):
                            await r.expire(idem_key, int(IDEM_TTL_SEC))
                except Exception as e:
                    logger.debug("telegram_idem_warning(send): %s", e)

            payload = {
                "chat_id": cid,
                "text": msg_text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }
            # אם יש קישורים — נוסיף inline keyboard
            kb = []
            if links.get("preview_url"):
                kb.append({"text": "👁 Preview", "url": links["preview_url"]})
            if links.get("approve_url"):
                kb.append({"text": "✅ Approve", "url": links["approve_url"]})
            if links.get("reject_url"):
                kb.append({"text": "❌ Reject", "url": links["reject_url"]})
            if kb:
                payload["reply_markup"] = {"inline_keyboard": [kb]}

            r = await cli.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json=payload,
                timeout=httpx.Timeout(10.0),
            )
            data = {}
            with suppress(Exception):
                data = r.json()
            return {
                "ok": (r.status_code == 200 and data.get("ok") is True),
                "status": r.status_code,
                "result": data,
                "used_chat_id": cid,
                "links": links,
            }
        else:
            # שימוש ב-helper כדי להרוויח idem+fallbacks קיימים (ADMIN_CHAT_ID)
            res = await _send_telegram_html(
                msg_text,
                approve_url=links.get("approve_url"),
                reject_url=links.get("reject_url"),
                preview_url=links.get("preview_url"),
            )
            return {"ok": bool(res.get("ok")), "result": res, "used_chat_id": ADMIN_CHAT_ID, "links": links}
    except Exception as e:
        return {"ok": False, "error": f"send_failed: {e}"}

# ==================== Global error handler ====================
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    error_id = secrets.token_hex(6)
    logger.exception("unhandled_error [%s]: %s %s", error_id, request.method, request.url)
    show_detail = os.getenv("SHOW_INTERNAL_ERRORS", "0").lower() in ("1", "true", "yes", "on") or LOG_LEVEL == "DEBUG"
    payload: Dict[str, Any] = {"ok": False, "error": "internal_error", "id": error_id}
    if show_detail:
        payload["detail"] = str(exc)
    return JSONResponse(status_code=500, content=payload)

# -------- NEW: Background real-time trailing manager ----------
async def _trail_rt_loop():
    """
    לולאת Trailing בזמן אמת (Best-effort)
    """
    if not TRAIL_RT_ENABLE:
        return
    try:
        from binance.client import Client  # type: ignore
    except Exception as e:
        logger.warning("trail_rt: binance client missing: %s", e)
        return
    api_key = os.getenv("BINANCE_API_KEY", "").strip()
    api_sec = os.getenv("BINANCE_API_SECRET", "").strip()
    if not (api_key and api_sec):
        logger.warning("trail_rt: missing binance keys")
        return

    client = Client(api_key, api_sec)
    _align_position_mode(client)

    def _symbols_to_check() -> List[str]:
        if TRAIL_RT_WATCH:
            return TRAIL_RT_WATCH[:TRAIL_RT_MAX_SYMBOLS]
        out: List[str] = []
        with suppress(Exception):
            infos = client.futures_account()['positions']
            for p in infos:
                try:
                    amt = float(p.get("positionAmt") or 0.0)
                    if abs(amt) > 0:
                        out.append(str(p.get("symbol")))
                except Exception:
                    continue
        if not out:
            return WATCHLIST[:TRAIL_RT_MAX_SYMBOLS]
        uniq: List[str] = []
        for s in out:
            if s and s not in uniq:
                uniq.append(s)
        return uniq[:TRAIL_RT_MAX_SYMBOLS]

    while True:
        try:
            # Pause windows (UTC)
            if _in_pause_window_utc():
                await asyncio.sleep(max(3, TRAIL_RT_INTERVAL_SEC))
                continue

            syms = _symbols_to_check()
            for sym in syms:
                # position?
                pos_amt = 0.0
                side_txt = None
                entry_price = 0.0
                with suppress(Exception):
                    infos = client.futures_position_information(symbol=sym)
                    for p in infos:
                        amt = float(p.get("positionAmt") or 0.0)
                        if abs(amt) > 0:
                            pos_amt = amt
                            entry_price = float(p.get("entryPrice") or 0.0)
                            side_txt = "BUY" if amt > 0 else "SELL"
                            break

                # (NEW) מעקב פתיחת פוזיציה ראשונית וזמן TP1 (in-memory)
                if side_txt and abs(pos_amt) > 0:
                    with suppress(Exception):
                        if sym not in app.state.pos_open_ts:
                            app.state.pos_open_ts[sym] = int(time.time())
                            app.state.tp1_hit_ts.pop(sym, None)
                else:
                    # אין פוזיציה — ננקה זכרון (לא חובה, אבל מונע stale)
                    with suppress(Exception):
                        app.state.pos_open_ts.pop(sym, None)
                        app.state.tp1_hit_ts.pop(sym, None)
                    continue  # בלי פוזיציה אין המשך ניהול

                # last price
                px_now = entry_price
                with suppress(Exception):
                    t = client.futures_symbol_ticker(symbol=sym)
                    if t and "price" in t:
                        px_now = float(t["price"]) or px_now
                if px_now <= 0:
                    continue

                # indicators (ATR & ADX)
                kl = []
                with suppress(Exception):
                    kl = client.futures_klines(symbol=sym, interval="1m", limit=60)
                ind = _compute_indicators_from_klines(kl or [], period=14)
                atr = float(ind.get("atr") or 0.0)
                adx = float(ind.get("adx") or 0.0)
                atr_pct = (atr / px_now) if px_now > 0 else 0.0

                # Optional filters
                if AUTO_TRAIL_ADX_MIN > 0 and adx < AUTO_TRAIL_ADX_MIN:
                    continue
                if AUTO_TRAIL_ATRPCT_MAX > 0 and atr_pct > AUTO_TRAIL_ATRPCT_MAX:
                    continue

                cb = (atr * TRAIL_RT_ATR_MULT / px_now) * 100.0 if px_now > 0 else 0.5
                cb = max(TRAIL_RT_MIN_CALLBACK, min(TRAIL_RT_MAX_CALLBACK, cb))
                cb = round(cb, 1)

                # inspect open trail orders
                existing = None
                with suppress(Exception):
                    oo = client.futures_get_open_orders(symbol=sym)
                    for o in oo or []:
                        if o.get("type") == "TRAILING_STOP_MARKET":
                            existing = o
                            break

                need_place = False
                need_adjust = False
                if not existing:
                    need_place = True
                else:
                    ex_cb = None
                    with suppress(Exception):
                        ex_cb = float(existing.get("callbackRate"))
                    if ex_cb is None or abs(ex_cb - cb) >= TRAIL_RT_ADJUST_THRESHOLD:
                        need_adjust = True

                if need_adjust:
                    with suppress(Exception):
                        client.futures_cancel_order(symbol=sym, orderId=existing.get("orderId"))  # type: ignore[arg-type]
                    need_place = True

                if need_place:
                    kwargs = dict(
                        symbol=sym,
                        side=("SELL" if side_txt == "BUY" else "BUY"),
                        type="TRAILING_STOP_MARKET",
                        callbackRate=cb,
                        reduceOnly=True,
                        workingType=TRAIL_RT_PRICE_SRC,
                        newClientOrderId=build_client_order_id(sym, ("SELL" if side_txt == "BUY" else "BUY"), role="TRAIL@RT"),
                    )
                    with suppress(Exception):
                        client.futures_create_order(**kwargs)

                # =============== תחזוקת TP: Merge / Rearm / Anti-stale ==================

                # 1) Merge TPs קרובים (קלה)
                if maybe_merge_close_tps:
                    # צריך tick מה-exchange info
                    tick, _step = _get_filters(client, sym)
                    with suppress(Exception):
                        maybe_merge_close_tps(client, sym, tick=tick, tick_band=TP_MERGE_TICK_BAND)

                # 2) Rearm-on-bounce — משתמשים ב-TPים הפתוחים כ"planned"
                last_planned: List[Dict[str, float]] = []
                with suppress(Exception):
                    ro = client.futures_get_open_orders(symbol=sym)
                    for o in ro or []:
                        if str(o.get("type")) == "LIMIT" and str(o.get("reduceOnly")).lower() == "true":
                            last_planned.append({
                                "price": float(o.get("price")),
                                "qty": float(o.get("origQty") or 0.0)
                            })
                if maybe_rearm_on_bounce and last_planned:
                    with suppress(Exception):
                        maybe_rearm_on_bounce(
                            client, sym, side_txt=side_txt, price_now=px_now,
                            last_planned_tps=last_planned, tick=_get_filters(client, sym)[0],
                            rearm_tick=TP_REARM_TICK
                        )

                # 3) Anti-stale nudge — אם עברו ≥ ANTI_STALE_MIN דקות מאז פתיחה ואין TP1
                opened_at = getattr(app.state, "pos_open_ts", {}).get(sym)
                tp1_at = getattr(app.state, "tp1_hit_ts", {}).get(sym)
                if opened_at and (not tp1_at):
                    elapsed_min = (int(time.time()) - int(opened_at)) / 60.0
                    if elapsed_min >= ANTI_STALE_MIN and anti_stale_nudge:
                        with suppress(Exception):
                            anti_stale_nudge(
                                client, sym, side_txt=side_txt,
                                tick=_get_filters(client, sym)[0],
                                nudge_bps=ANTI_STALE_NUDGE_BPS,
                                min_distance_ticks=1
                            )

                # === Best-effort: זיהוי TP1 נלקח (על בסיס הזמנה reduceOnly שמולאה לאחר הפתיחה)
                # אם נמצא — נחתים את הטיימסטמפ ונרשום metric
                with suppress(Exception):
                    if (sym in app.state.pos_open_ts) and (sym not in app.state.tp1_hit_ts):
                        # חיפוש היסטוריית הזמנות אחרונות (קליל)
                        # הערה: אם endpoint לא יחזיר reduceOnly/status, שום דבר לא יקרה — suppress(Exception)
                        orders = client.futures_get_all_orders(symbol=sym, limit=20)
                        # נסדר מהחדשות לישנות
                        for o in reversed(orders or []):
                            if str(o.get("reduceOnly")).lower() == "true" and str(o.get("status")).upper() == "FILLED":
                                app.state.tp1_hit_ts[sym] = int(time.time())
                                observe_time_to_tp1(
                                    int(app.state.tp1_hit_ts[sym]) - int(app.state.pos_open_ts[sym])
                                )
                                break
                # ====================== סוף תחזוקת TP ======================

        except Exception as e:
            logger.debug("trail_rt.loop_error: %s", e)
        await asyncio.sleep(max(3, TRAIL_RT_INTERVAL_SEC))

# --- אזהרות סטארטאפ (אופציונלי, לא חוסם) ---
def _collect_critical_env_warnings() -> List[str]:
    warns: List[str] = []
    if not os.getenv("API_BEARER_TOKEN"):
        warns.append("API_BEARER_TOKEN missing (protected routes might 401).")
    if not os.getenv("BINANCE_API_KEY") or not os.getenv("BINANCE_API_SECRET"):
        warns.append("BINANCE keys missing — trading/management disabled.")
    if (os.getenv("PUBLIC_REQUIRE_BEARER", "0").lower() in ("1", "true", "yes", "on")) and not os.getenv("API_BEARER_TOKEN"):
        warns.append("PUBLIC_REQUIRE_BEARER=1 but API_BEARER_TOKEN is empty.")
    if REQUIRE_REDIS and not REDIS_URL:
        warns.append("REQUIRE_REDIS=1 but REDIS_URL missing.")
    return warns

# ==================== Startup / Shutdown ====================
@app.on_event("startup")
async def _startup_tasks():
    if getattr(app.state, "bg_started", False):
        logger.info("startup: background already started – skipping")
        return
    app.state.bg_started = True
    app.state.boot_ts = time.time()
    _ = _get_shared_async_client()

    env_w = _collect_critical_env_warnings()
    if env_w:
        logger.warning("=== Startup env warnings (%d) ===", len(env_w))
        for w in env_w:
            logger.warning("env: %s", w)

    async def _late_webhook():
        with suppress(Exception):
            if TELEGRAM_AUTO_WEBHOOK:
                await asyncio.sleep(1.0)
                await _ensure_telegram_webhook()
        if STARTUP_NOTIFY_ENABLE and TELEGRAM_BOT_TOKEN and ADMIN_CHAT_ID:
            with suppress(Exception):
                txt = f"🟢 <b>{_md_html(os.getenv('INSTANCE_ID','algogpt'))}</b> up · v{_md_html(APP_VERSION)}"
                await _send_telegram_html(txt)

    asyncio.create_task(_late_webhook())

    if TRAIL_RT_ENABLE:
        asyncio.create_task(_trail_rt_loop())

@app.on_event("shutdown")
async def _shutdown_tasks():
    with suppress(Exception):
        t: Optional[asyncio.Task] = getattr(app.state, "bg_started_task", None)
        if t:
            t.cancel()
            with suppress(Exception):
                await t
    cli: Optional[httpx.AsyncClient] = getattr(app.state, "shared_async_client", None)
    if cli and not getattr(cli, "is_closed", False):
        with suppress(Exception):
            await cli.aclose()
    r = getattr(app.state, "redis", None)
    if r:
        with suppress(Exception):
            await r.close()
        with suppress(Exception):
            pool = getattr(r, "connection_pool", None)
            if pool:
                await pool.disconnect()
    logger.info("Application shutdown complete.")

if __name__ == "__main__":
    import uvicorn
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "10000"))
    reload_ = os.getenv("UVICORN_RELOAD", "0").lower() in ("1", "true", "yes", "on")
    uvicorn.run("main:app", host=host, port=port, reload=reload_, log_level=LOG_LEVEL.lower())





























































































































































































































































































































































































































































































































































































































































































