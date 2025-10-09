from __future__ import annotations

import os
import json
import time
import hmac
import re
import httpx
import hashlib
import secrets
import logging
import traceback
import inspect
import asyncio
import threading
from contextlib import suppress
from typing import Any, Dict, List, Optional, Callable, Tuple, Union
from collections import Counter

from fastapi import FastAPI, Request, HTTPException, Body, Query, APIRouter
from fastapi.responses import JSONResponse, PlainTextResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

# =================================================
# Logging
# =================================================
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("algogpt.main")

# =================================================
# Inline ENV defaults (safe, non-secret)
# =================================================
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

# =================================================
# Simple in-memory ConfirmStore (fallback; behind flag)
# =================================================
class ConfirmStore:
    _items: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def create(cls, req: Dict[str, Any]) -> None:
        tid = str(req.get("ticket_id") or f"T_{int(time.time())}_{secrets.token_hex(3)}")
        cls._items[tid] = {"ticket_id": tid, "req": dict(req), "ts": time.time(), "approved": None}
        logger.debug("ConfirmStore.create: %s", tid)

    @classmethod
    def decide(cls, ticket_id: str, approved: bool) -> None:
        it = cls._items.get(str(ticket_id))
        if it:
            it["approved"] = bool(approved)
        logger.debug("ConfirmStore.decide: %s -> %s", ticket_id, approved)

    @classmethod
    def pending(cls) -> List[Dict[str, Any]]:
        return [v for v in cls._items.values() if v.get("approved") is None]

    @classmethod
    def remove(cls, ticket_id: str) -> None:
        cls._items.pop(str(ticket_id), None)

# =================================================
# FastAPI App
# =================================================
app = FastAPI(
    title=os.getenv("APP_TITLE", "AlgoGPT Supervisor"),
    version=os.getenv("APP_VERSION", "1.0.0"),
    docs_url=os.getenv("DOCS_URL", "/docs"),
    redoc_url=os.getenv("REDOC_URL", "/redoc"),
    openapi_url=os.getenv("OPENAPI_URL", "/openapi.json"),
)

# CORS
CORS_ALLOW_ORIGINS = os.getenv("CORS_ALLOW_ORIGINS", "*")
CORS_ALLOW_HEADERS = os.getenv("CORS_ALLOW_HEADERS", "*")
CORS_ALLOW_METHODS = os.getenv("CORS_ALLOW_METHODS", "*")
CORS_ALLOW_CREDENTIALS = os.getenv("CORS_ALLOW_CREDENTIALS", "0").lower() in ("1", "true", "yes", "on")

# אם יש צורך באישורים (credentials) אסור '*' — ניתן לספק רשימת דומיינים ב-ENV חלופי
_origins_list = [o.strip() for o in CORS_ALLOW_ORIGINS.split(",")] if CORS_ALLOW_ORIGINS else ["*"]
if CORS_ALLOW_CREDENTIALS and _origins_list == ["*"]:
    strict_env = [o.strip() for o in (os.getenv("CORS_ALLOW_ORIGINS_STRICT","")).split(",") if o.strip()]
    if strict_env:
        _origins_list = strict_env
    else:
        logger.warning("CORS: allow_credentials=True but allow_origins='*'. "
                       "Consider setting CORS_ALLOW_ORIGINS_STRICT with explicit domains.")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins_list,
    allow_credentials=CORS_ALLOW_CREDENTIALS,
    allow_methods=[m.strip() for m in CORS_ALLOW_METHODS.split(",")] if CORS_ALLOW_METHODS else ["*"],
    allow_headers=[h.strip() for h in CORS_ALLOW_HEADERS.split(",")] if CORS_ALLOW_HEADERS else ["*"],
)

# Security headers (basic hardening)
@app.middleware("http")
async def _security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    resp.headers.setdefault("Cross-Origin-Resource-Policy", "same-site")
    # HSTS אם מאחורי HTTPS ומופעל ב-ENV
    if os.getenv("ENABLE_HSTS","0").lower() in ("1","true","yes","on"):
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains; preload")
    return resp

# =================================================
# Helpers
# =================================================
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

# =================================================
# OPS APPROVE Router
# =================================================
router = APIRouter(tags=["ops-approval"])

with suppress(Exception):
    from utils.guard_stop import ensure_protective_stop  # type: ignore

def record_approval_created(): ...
def record_approval_approved(): ...
def record_approval_rejected(): ...
with suppress(Exception):
    from routes.metrics import (  # type: ignore
        record_approval_created as _rac,
        record_approval_approved as _raa,
        record_approval_rejected as _rar,
    )
    record_approval_created = _rac
    record_approval_approved = _raa
    record_approval_rejected = _rar

try:
    import redis.asyncio as aioredis  # type: ignore
except Exception:
    aioredis = None  # type: ignore

NS                   = os.getenv("REDIS_NAMESPACE", "ops-supervisor-web").strip() or "ops-supervisor-web"
REDIS_URL            = os.getenv("REDIS_URL", "").strip()
PUBLIC_HOST          = (os.getenv("PUBLIC_HOST") or os.getenv("WEBHOOK_HOST") or "").strip()
HMAC_SECRET          = (os.getenv("WEBHOOK_HMAC_SECRET") or os.getenv("OPS_SIGN_SECRET") or "").strip()
ADMIN_CHAT_ID        = os.getenv("TELEGRAM_CHAT_ID") or os.getenv("ADMIN_CHAT_ID")
BOT_TOKEN            = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
API_BEARER_TOKEN     = (os.getenv("API_BEARER_TOKEN") or os.getenv("API_TOKEN") or "").strip()
TICKET_TTL_SEC       = int(os.getenv("OPS_TICKET_TTL_SEC", "1800"))
ETA_SMART_ENABLE     = (os.getenv("ETA_SMART_ENABLE","0").lower() in ("1","true","yes","on"))
ETA_VELOCITY_WINDOW  = int(os.getenv("ETA_VELOCITY_WINDOW","30"))
DEFAULT_INTERVAL     = os.getenv("DEFAULT_INTERVAL","15m")

def _bool_env(name: str, default: bool=False) -> bool:
    return str(os.getenv(name, "1" if default else "0")).lower() in ("1","true","yes","on")

TP_LADDER_ON_APPROVE            = _bool_env("TP_LADDER_ON_APPROVE", False)
APPROVAL_FAIL_OPEN_ON_VELOCITY  = _bool_env("APPROVAL_FAIL_OPEN_ON_VELOCITY", True)
VELOCITY_LOG_LEVEL              = (os.getenv("VELOCITY_LOG_LEVEL","WARNING") or "WARNING").upper()
DEBUG_APPROVE_HTML              = _bool_env("DEBUG_APPROVE_HTML", False)
APPROVE_FALLBACK_TO_MARKET      = not _bool_env("PROPOSE_BLOCK_ON_FAIL", False)

HEALTH_TP1_ENABLE = _bool_env("HEALTH_TP1_ENABLE", True)
HEALTH_TP1_INTERVAL_SEC = int(os.getenv("HEALTH_TP1_INTERVAL_SEC", "600"))
TP1_TAGS = [t.strip() for t in (os.getenv("TP1_TAGS","") or "").split(",") if t.strip()]
SL_TAGS = [t.strip() for t in (os.getenv("SL_TAGS","SL,STOP,STOP_LOSS,STOP_LOSS_LIMIT,STOP_MARKET") or "").split(",") if t.strip()]

# Optional: protect approve/reject with Bearer behind ENV flag
PROTECT_APPROVE_ROUTES = _bool_env("PROTECT_APPROVE_ROUTES", False)
# Optional: protect digest routes
PROTECT_DIGEST_ROUTES  = _bool_env("PROTECT_DIGEST_ROUTES", False)

# --- New flags: prod behavior ---
CONFIRMSTORE_ENABLE = _bool_env("CONFIRMSTORE_ENABLE", False)  # default off
REQUIRE_REDIS       = _bool_env("REQUIRE_REDIS", True)         # default on (fail-closed)

# Signed approve anti-replay
SIGNED_TS_MAX_SKEW_SEC = int(os.getenv("SIGNED_TS_MAX_SKEW_SEC", "60") or "60")
SIGNED_NONCE_TTL_SEC   = int(os.getenv("SIGNED_NONCE_TTL_SEC", "120") or "120")

# Order ID helper
try:
    from utils.order_ids import build_client_order_id  # type: ignore
except Exception:
    def _coid_fit_local(s: str, limit: int = 36) -> str:
        if len(s) <= limit:
            return s
        h = hashlib.md5(s.encode("utf-8")).hexdigest()[:6]
        return f"{s[:limit-(len(h)+1)]}_{h}"
    def build_client_order_id(symbol: str, side: str, role: str = "ENTRY", extra: Optional[str] = None) -> str:
        prefix = (os.getenv("ORDER_ID_PREFIX") or "ALG").strip() or "ALG"
        sym = str(symbol).upper()
        sd  = str(side).upper()
        rl  = str(role).upper().replace("@","_")
        ts = str(int(time.time()*1000))
        base = "-".join([prefix, sym, sd, rl, ts] + ([str(extra)] if extra else []))
        return _coid_fit_local(base, 36)

# Position sizing helper
try:
    from app.utils.position_sizing import ensure_final_qty  # type: ignore
except Exception:
    with suppress(Exception):
        from utils.position_sizing import ensure_final_qty  # type: ignore
    if "ensure_final_qty" not in globals():
        def ensure_final_qty(ticket: Dict[str, Any], price: float) -> Dict[str, Any]:
            return ticket

# -------------------------------------------------
# Shared HTTP & Redis clients (reuse connections)
# -------------------------------------------------
_shared_client_lock = threading.Lock()

def _get_shared_async_client() -> httpx.AsyncClient:
    cli: Optional[httpx.AsyncClient] = getattr(app.state, "shared_async_client", None)
    if cli and not cli.is_closed:
        return cli
    # create under a lock to avoid races on startup
    with _shared_client_lock:
        cli = getattr(app.state, "shared_async_client", None)
        if cli and not cli.is_closed:
            return cli
        timeout = httpx.Timeout(connect=2.5, read=15.0, write=10.0)
        limits = httpx.Limits(max_connections=100, max_keepalive_connections=20)
        cli = httpx.AsyncClient(timeout=timeout, limits=limits)
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
# --- Ticket helpers (Redis + optional ConfirmStore fallback) ---
async def _load_ticket(ticket_id: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """
    מחזיר (ticket, source) כאשר source ∈ {"redis","memory","none"}
    """
    # Redis קודם
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

    # ConfirmStore fallback — רק אם מאופשר
    if CONFIRMSTORE_ENABLE:
        with suppress(Exception):
            for it in ConfirmStore.pending():
                if str(it.get("ticket_id")) == str(ticket_id):
                    return dict(it.get("req") or it), "memory"

    return None, "none"

async def _delete_ticket(ticket_id: str, source: str, final_status: Optional[bool] = None) -> None:
    """
    מוחק את הכרטיס ממקור האחסון, ומוסיף לוג ל-Redis על expirations/decisions.
    אם לא נמצא – שקט.
    """
    # --- Build event for digest (/ops/digest/expired) ---
    event: Dict[str, Any] = {
        "ts": time.time(),
        "ticket_id": ticket_id,
        "status": final_status,                 # True/False/None
        "src": source,                          # "redis" | "memory" | "none"
        "ns": NS,
        "reason": ("expired" if final_status is None else ("approved" if final_status else "rejected")),
    }

    # Try enrich event with symbol/side/idempotency (idem)
    fetched_req: Optional[Dict[str, Any]] = None
    if aioredis and REDIS_URL:
        with suppress(Exception):
            r = await _get_redis_cached()
            if r:
                if source == "redis":
                    raw = await r.get(f"{NS}:ticket:{ticket_id}")
                    if raw:
                        obj = json.loads(raw)
                        fetched_req = obj.get("req") or obj
                elif source == "memory":
                    pass
    if not fetched_req and source in ("memory",):
        if CONFIRMSTORE_ENABLE:
            with suppress(Exception):
                for it in ConfirmStore.pending():
                    if str(it.get("ticket_id")) == str(ticket_id):
                        fetched_req = it.get("req") or it
                        break

    if fetched_req:
        event["symbol"] = str(fetched_req.get("symbol","")).upper()
        event["side"]   = str(fetched_req.get("side","")).upper()
        event["expiry_ts"] = fetched_req.get("expiry_ts")
        event["note"] = fetched_req.get("note")
        base = f"{ticket_id}:{event.get('symbol','')}:{event.get('side','')}"
        event["idem"] = hashlib.md5(base.encode("utf-8")).hexdigest()[:10]
    else:
        event["symbol"] = ""
        event["side"] = ""
        event["idem"] = hashlib.md5(f"{ticket_id}".encode("utf-8")).hexdigest()[:10]

    # Push to Redis list(s)
    if aioredis and REDIS_URL:
        with suppress(Exception):
            r = await _get_redis_cached()
            if r:
                key_good = f"{NS}:expired_log"
                key_bad  = f"{NS}:expired_log_bad"
                key = key_good if (event.get("symbol") and event.get("side")) else key_bad
                payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
                await r.lpush(key, payload)
                await r.ltrim(key, 0, 2999)  # keep last ~3000 events

    # --- Actual deletion ---
    if source in ("redis", "none"):
        if aioredis and REDIS_URL:
            with suppress(Exception):
                r = await _get_redis_cached()
                if r:
                    await r.delete(f"{NS}:ticket:{ticket_id}")

    with suppress(Exception):
        ConfirmStore.remove(ticket_id)

    logger.info("ticket_deleted: id=%s source=%s status=%s", ticket_id, source, final_status)

def _smart_etas(symbol: str, side: str, price_now: Optional[float],
                tp1: Optional[float], tp2: Optional[float], tp3: Optional[float]) -> Dict[str, Any]:
    """
    חישוב ETA גס לפי חלון מהירות מוגדר (ETA_VELOCITY_WINDOW).
    """
    try:
        if not price_now:
            return {}
        targets = []
        for i, tp in enumerate([tp1, tp2, tp3], start=1):
            if tp and tp > 0:
                dist_bps = abs((tp - price_now) / price_now) * 10_000
                eta_min = max(1, int(dist_bps / max(1, ETA_VELOCITY_WINDOW)))
                targets.append((i, eta_min))
        out: Dict[str, Any] = {}
        for i, eta in targets:
            out[f"eta_tp{i}_min"] = eta
        out.setdefault("eta_open_min", out.get("eta_tp1_min", 2))
        return out
    except Exception as e:
        logger.debug("smart_etas_failed: %s", e)
        return {}

# ------------------------------
# PRICE HELPERS — async-first
# ------------------------------
async def get_last_price_async(symbol: str) -> Optional[float]:
    sym = symbol.upper()

    # 1) local client (thread)
    with suppress(Exception):
        from utils.binance_client import get_price  # type: ignore
        val = await asyncio.to_thread(get_price, sym)
        if val:
            v = float(val)
            if v > 0:
                return v

    # 2) HTTP async
    for url in (
        "https://fapi.binance.com/fapi/v1/ticker/price",
        "https://api.binance.com/api/v3/ticker/price",
    ):
        try:
            cli = _get_shared_async_client()
            r = await cli.get(url, params={"symbol": sym})
            if r.status_code == 200:
                data = r.json()
                p = float(data.get("price"))
                if p > 0:
                    return p
        except Exception:
            continue

    # 3) official SDK (thread)
    with suppress(Exception):
        from binance.client import Client  # type: ignore
        api_key = os.getenv("BINANCE_API_KEY","").strip()
        api_sec = os.getenv("BINANCE_API_SECRET","").strip()
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

# HTML helpers
def _md_html(s: str) -> str:
    return str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

def _html(msg: str) -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html><meta charset='utf-8'>"
        "<body style='font-family:sans-serif;max-width:720px;margin:3rem auto;line-height:1.5'>"
        f"<h2 style='margin:0 0 .5rem 0'>{msg}</h2>"
        "<p style='color:#666'>אפשר לחזור חזרה לטלגרם.</p>"
        "</body>"
    )

def _sign_hex(secret_hex_or_text: str, payload: bytes) -> str:
    key = bytes.fromhex(secret_hex_or_text) if len(secret_hex_or_text)==64 else secret_hex_or_text.encode("utf-8")
    return hmac.new(key, payload, hashlib.sha256).hexdigest()

_MODE_RX = re.compile(r"\[mode:\s*(MARKET|HYBRID|AUTO)\s*\]", flags=re.I)
def _parse_mode(note: Optional[str]) -> Optional[str]:
    if not note:
        return None
    m = _MODE_RX.search(str(note))
    return m.group(1).upper() if m else None

async def _send_telegram_html(text: str, approve_url: Optional[str] = None,
                              reject_url: Optional[str] = None, preview_url: Optional[str] = None) -> Dict[str, Any]:
    if not BOT_TOKEN or not ADMIN_CHAT_ID:
        return {"ok": False, "skipped": True}
    try:
        chat_id: Any = int(ADMIN_CHAT_ID) if str(ADMIN_CHAT_ID).isdigit() else ADMIN_CHAT_ID
    except Exception:
        chat_id = ADMIN_CHAT_ID

    payload: Dict[str, Any] = {
        "chat_id": chat_id,
        "text": text, "parse_mode": "HTML", "disable_web_page_preview": True,
    }
    if approve_url or reject_url or preview_url:
        row: List[Dict[str, Any]] = []
        if preview_url: row.append({"text":"👁 Preview","url":preview_url})
        if approve_url: row.append({"text":"✅ Approve","url":approve_url})
        if reject_url:  row.append({"text":"❌ Reject","url":reject_url})
        payload["reply_markup"] = {"inline_keyboard":[row]}

    # retry קטן עבור 429/5xx + כיבוד retry_after אם קיים
    for attempt in range(3):
        try:
            cli = _get_shared_async_client()
            r = await cli.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json=payload,
                timeout=httpx.Timeout(10.0, connect=2.5)
            )
            try:
                data = r.json()
            except Exception:
                data = {}
            if r.status_code < 400 and data.get("ok"):
                return {
                    "ok": True,
                    "status": r.status_code,
                    "text_raw": r.text,
                    **({"result": data.get("result")} if "result" in data else {}),
                }
            if r.status_code in (429, 500, 502, 503, 504):
                retry_after = 0.0
                try:
                    retry_after = float(r.headers.get("Retry-After","0"))
                except Exception:
                    pass
                await asyncio.sleep(max(retry_after, 0.6 * (attempt + 1)))
                continue
            return {"ok": False, "status": r.status_code, "text_raw": r.text}
        except Exception as e:
            if attempt == 2:
                return {"ok": False, "error": str(e)}
            await asyncio.sleep(0.6 * (attempt + 1))
    return {"ok": False, "error": "telegram_send_exhausted"}

def _filter_kwargs_for_callable(fn: Callable[..., Any], kwargs: Dict[str, Any]) -> Dict[str, Any]:
    try:
        sig = inspect.signature(fn)
        allowed = set(sig.parameters.keys())
        return {k: v for k, v in kwargs.items() if k in allowed}
    except Exception:
        bad = {"tp_kind","sl_kind","entry_kind","entry_offset","tp_offset","sl_offset"}
        return {k: v for k, v in kwargs.items() if k not in bad}

def _is_code_4061(err: Union[Exception, str]) -> bool:
    s = str(err)
    return "code=-4061" in s or "position side does not match" in s.lower()

def _align_position_mode(client) -> None:
    mode_override = (os.getenv("POSITION_MODE_OVERRIDE","") or "").strip().lower()
    with suppress(Exception):
        if mode_override in ("hedge","dual","dual_side","dual_side_position","dualposition"):
            client.futures_change_position_mode(dualSidePosition="true")
        elif mode_override in ("oneway","one_way","single","single_side","oneside"):
            client.futures_change_position_mode(dualSidePosition="false")

# --- Execute trades (MARKET/HYBRID/AUTO) ---
async def _execute_trade(ticket: Dict[str, Any]) -> Dict[str, Any]:
    with suppress(Exception):
        from utils.trade_executor import place_futures_market  # type: ignore
        return await place_futures_market(ticket)
    try:
        from binance.client import Client  # type: ignore
    except Exception as e:
        logger.error("binance import failed: %s", e)
        return {"ok": False, "error": "binance_client_import_failed", "detail": str(e)}

    try:
        api_key = os.getenv("BINANCE_API_KEY","").strip()
        api_sec = os.getenv("BINANCE_API_SECRET","").strip()
        if not api_key or not api_sec:
            return {"ok": False, "error": "binance_keys_missing"}
        client = Client(api_key, api_sec)

        _align_position_mode(client)

        symbol   = str(ticket.get("symbol","")).upper()
        side     = str(ticket.get("side","")).upper()
        qty      = float(ticket.get("qty") or ticket.get("quantity") or 0)
        leverage = int(ticket.get("leverage") or 1)
        if not(symbol and side in ("BUY","SELL") and qty > 0 and leverage > 0):
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
        if pos_side_supplied in ("LONG","SHORT"):
            attempt_order["positionSide"] = pos_side_supplied

        try:
            order = client.futures_create_order(**attempt_order)
            return {"ok": True, "exchange": "binance_futures", "order": order}
        except Exception as e1:
            if not _is_code_4061(e1):
                raise
            try:
                retry_kwargs = dict(base_kwargs)
                order = client.futures_create_order(**retry_kwargs)
                return {"ok": True, "exchange": "binance_futures", "order": order, "retry": "no_positionSide"}
            except Exception as e2:
                try:
                    retry2_kwargs = dict(base_kwargs)
                    retry2_kwargs["positionSide"] = "LONG" if side == "BUY" else "SHORT"
                    order = client.futures_create_order(**retry2_kwargs)
                    return {"ok": True, "exchange": "binance_futures", "order": order, "retry": "derived_positionSide"}
                except Exception as e3:
                    logger.error("futures_create_order retries failed: first=%s, no_ps=%s, derived=%s", e1, e2, e3)
                    return {
                        "ok": False,
                        "error": "order_failed",
                        "detail": str(e3),
                        "first_error": str(e1),
                        "second_error": str(e2),
                    }
    except Exception as e:
        logger.error("futures_create_order failed: %s", e)
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
        return {"ok": False, "error": "execute_trade_live_missing", "detail": "not found in utils/app"}

    symbol   = str(ticket.get("symbol","")).upper()
    side     = str(ticket.get("side","")).upper()
    qty      = float(ticket.get("qty") or ticket.get("quantity") or 0)
    leverage = int(ticket.get("leverage") or ticket.get("lev") or 0)

    raw_ps  = str(ticket.get("position_side") or ticket.get("positionSide") or "").upper()
    pos_side = raw_ps if raw_ps in ("LONG","SHORT") else ("LONG" if side=="BUY" else "SHORT")

    tps_raw = [ticket.get("tp1"), ticket.get("tp2"), ticket.get("tp3")]
    tp_targets = [float(x) for x in tps_raw if x is not None and str(x) not in ("0","0.0") and float(x) > 0]
    sl_targets = [float(ticket.get("sl"))] if (ticket.get("sl") not in (None, 0, "0", "0.0")) else None

    if not(symbol and side in ("BUY","SELL") and qty > 0 and leverage > 0):
        return {"ok": False, "error": "bad_ticket_params"}

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
        tp_splits= ticket.get("tp_splits"),
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
        logger.error("armed_execute failed: %s", e)
        return {"ok": False, "error": "armed_execute_failed", "detail": f"{e}", "trace": traceback.format_exc()}

# --- Smart manage after approve ---
async def _smart_manage_now(symbol: str,
                            offset_bps: Optional[int] = None,
                            pcts: Optional[List[float]] = None,
                            splits: Optional[List[float]] = None,
                            atr_mult: Optional[float] = None) -> Dict[str, Any]:
    base = get_internal_base()
    token = API_BEARER_TOKEN
    if not token:
        return {"ok": False, "skipped": True, "reason": "missing token"}

    body: Dict[str, Any] = {"symbol": symbol}
    if offset_bps is not None:
        body["offset_bps"] = offset_bps
    if pcts is not None:
        body["pcts"] = pcts
    if splits is not None:
        body["splits"] = splits
    if atr_mult is not None:
        body["callback_rate"] = None
        body["atr_mult"] = atr_mult

    timeout = httpx.Timeout(10.0, connect=2.5)
    retries = 2
    for attempt in range(retries + 1):
        try:
            cli = _get_shared_async_client()
            r = await cli.post(f"{base}/position-ops/manage-once",
                               headers={"Authorization": f"Bearer {token}"},
                               json=body, timeout=timeout)
            if r.status_code in (200, 201, 202, 204, 304, 409):
                return {"ok": r.status_code < 400, "status": r.status_code, "text": r.text}
            await asyncio.sleep(0.5 + attempt * 0.75)
        except Exception as e:
            if attempt >= retries:
                logger.warning("smart_manage_now_error: %s", e)
                return {"ok": False, "error": str(e)}
            await asyncio.sleep(0.5 + attempt * 0.75)
    return {"ok": False, "error": "smart_manage_exhausted"}

def _smart_manage_env() -> Dict[str, Any]:
    def _parse_floats_csv(val: Optional[str]) -> Optional[List[float]]:
        if not val:
            return None
        try:
            return [float(x.strip()) for x in str(val).split(",") if str(x).strip()]
        except Exception:
            return None

    return {
        "enable": _bool_env("SMART_MANAGE_ON_APPROVE", False),
        "offset_bps": int(os.getenv("SMART_MANAGE_BE_OFFSET_BPS", os.getenv("TP_BE_OFFSET_BPS","8"))),
        "pcts": _parse_floats_csv(os.getenv("SMART_MANAGE_PCTS")),
        "splits": _parse_floats_csv(os.getenv("SMART_MANAGE_SPLITS")),
        "atr_mult": float(os.getenv("SMART_MANAGE_TRAIL_ATR_MULT","0") or 0) or None,
    }

# --- API: create ticket ---
@router.post("/ops/ticket")
async def create_ticket(
    payload: Dict[str, Any] = Body(...),
    request: Request = None,
):
    symbol = (payload.get("symbol") or "").upper().strip()
    side   = (payload.get("side") or "").upper().strip()
    qty    = float(payload.get("qty") or payload.get("quantity") or 0)
    lev    = int(payload.get("leverage") or payload.get("lev") or 0)
    note   = payload.get("note") or ""
    position_side = (payload.get("position_side") or payload.get("positionSide") or "BOTH").upper()
    budget = float(payload.get("budget") or payload.get("budget_usd") or 0.0)

    if not (symbol and side):
        raise HTTPException(status_code=422, detail="Missing fields (symbol/side). qty/leverage may be auto at approve.")

    tid = payload.get("ticket_id") or f"T_{secrets.token_hex(4)}"

    if ETA_SMART_ENABLE and (payload.get("tp1") or payload.get("tp2") or payload.get("tp3")):
        price_now = None
        with suppress(Exception):
            price_now = await get_last_price_async(symbol)
        etas = _smart_etas(symbol, side, price_now, payload.get("tp1"), payload.get("tp2"), payload.get("tp3"))
        for k, v in etas.items():
            payload.setdefault(k, v)

    def apply_note_flags(note: str, ticket: Dict[str, Any]) -> Dict[str, Any]:
        with suppress(Exception):
            from routes.ops_flags import apply_note_flags as _anf  # type: ignore
            return _anf(note, ticket)
        return ticket

    req_body: Dict[str, Any] = {
        "ticket_id": tid, "symbol": symbol, "side": side, "qty": qty,
        "leverage": lev, "position_side": position_side, "budget": budget, "note": note,
        "score": payload.get("score"), "eta_open_min": payload.get("eta_open_min"),
        "tp1": payload.get("tp1"), "tp2": payload.get("tp2"), "tp3": payload.get("tp3"),
        "eta_tp1_min": payload.get("eta_tp1_min"), "eta_tp2_min": payload.get("eta_tp2_min"), "eta_tp3_min": payload.get("eta_tp3_min"),
        "sl": payload.get("sl"), "prob_overall_pct": payload.get("prob_overall_pct"),
        "prob_tp1_pct": payload.get("prob_tp1_pct"), "prob_tp2_pct": payload.get("prob_tp2_pct"), "prob_tp3_pct": payload.get("prob_tp3_pct"),
        "expiry_ts": payload.get("expiry_ts"),
    }
    req_body = apply_note_flags(note, req_body)

    with suppress(Exception):
        rr_min_flag = float(req_body.get("rr_min") or 0.0)
        rr_env_lo   = float(os.getenv("APPROVAL_RR_MIN", "0") or "0")
        rr_min_eff  = max(rr_min_flag, rr_env_lo)
        if rr_min_eff > 0 and req_body.get("sl"):
            current = float((await get_last_price_async(symbol)) or 0)
            tp1 = float(req_body.get("tp1") or 0); sl = float(req_body.get("sl") or 0)
            rr  = None
            if side == "BUY" and current > 0 and tp1 > 0 and sl > 0:
                reward = abs(tp1 - current); risk = abs(current - sl); rr = (reward / risk) if risk > 0 else None
            elif side == "SELL" and current > 0 and tp1 > 0 and sl > 0:
                reward = abs(current - tp1); risk = abs(sl - current); rr = (reward / risk) if risk > 0 else None
            if rr is not None and rr < rr_min_eff:
                req_body["blocked_by_rr_min"] = True

    # --- Persist ticket ---
    persisted = False
    # Redis = מקור אמת חובה אם REQUIRE_REDIS=True
    if aioredis and REDIS_URL:
        try:
            r = await _get_redis_cached()
            if r:
                rec = {"ts": time.time(), "req": req_body, "note": note}
                await r.setex(f"{NS}:ticket:{tid}", TICKET_TTL_SEC, json.dumps(rec, ensure_ascii=False, separators=(",", ":")))
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

    record_approval_created()

    base = PUBLIC_HOST.rstrip("/") if PUBLIC_HOST else (str(request.base_url).rstrip("/") if request else "")
    approve_url = f"{base}/ops/approve?ticket_id={tid}" if base else ""
    reject_url  = f"{base}/ops/reject?ticket_id={tid}"  if base else ""
    preview_url = f"{base}/ops/ui/ticket?ticket_id={tid}" if base else ""

    lines = []
    lines.append("⚠️ <b>Approval Needed</b>")
    lines.append(f"• Ticket: <code>{_md_html(tid)}</code>")
    lines.append(f"• {_md_html(symbol)} {_md_html(side)} qty=<code>{_md_html(qty)}</code> lev=<code>{_md_html(lev)}</code>")
    if req_body.get("score") is not None:       lines.append(f"• Score: <code>{req_body['score']}</code>")
    if req_body.get("eta_open_min") is not None:lines.append(f"• ETA Open: <code>{req_body['eta_open_min']}m</code>")
    for i in (1,2,3):
        tpv = req_body.get(f"tp{i}"); etv = req_body.get(f"eta_tp{i}_min"); prv = req_body.get(f"prob_tp{i}_pct")
        if tpv is not None:
            row = f"• TP{i}: <code>{tpv}</code>"
            if etv is not None: row += f"  ETA:<code>{etv}m</code>"
            if prv is not None: row += f"  P(s):<code>{prv}%</code>"
            lines.append(row)
    if req_body.get("sl") is not None: lines.append(f"• SL: <code>{req_body['sl']}</code>")
    mode = _parse_mode(note)
    if mode: lines.append(f"• Mode: <code>{mode}</code>")
    if req_body.get("tp_splits"): lines.append(f"• TP Splits: <code>{req_body['tp_splits']}</code>")
    if req_body.get("blocked_by_rr_min"): lines.append("• RR Check: <code>Below RR_MIN (manual review)</code>")
    if req_body.get("prob_overall_pct") is not None: lines.append(f"• Success %: <code>{req_body['prob_overall_pct']}%</code>")
    if req_body.get("expiry_ts") is not None:        lines.append(f"• Expires: <code>{req_body['expiry_ts']}</code>")
    if note: lines.append(f"• Note: {_md_html(note)}")
    lines.append("— — —")
    lines.append("בחר:")
    pretty = "\n".join(lines)
    tg_resp = await _send_telegram_html(pretty, approve_url=approve_url or None, reject_url=reject_url or None, preview_url=preview_url or None)

    return {
        "ok": True, "ticket_id": tid,
        "approve_url": approve_url, "reject_url": reject_url, "preview_url": preview_url,
        "telegram_result": tg_resp
    }

def _decide_flow_by_mode(ticket: Dict[str, Any]) -> str:
    mode = _parse_mode(ticket.get("note"))
    if mode in ("MARKET", "HYBRID", "AUTO"):
        return mode
    return "HYBRID" if TP_LADDER_ON_APPROVE else "MARKET"

async def _apply_auto_qty_on_ticket_async(ticket: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    symbol = (ticket.get("symbol") or "").upper()
    price = await get_last_price_async(symbol)
    if not price or float(price) <= 0:
        return None
    new_ticket = ensure_final_qty(dict(ticket), float(price))
    ps = str(new_ticket.get("position_side") or new_ticket.get("positionSide") or "").upper()
    if ps == "BOTH":
        new_ticket.pop("positionSide", None)
        new_ticket["position_side"] = ""
    return new_ticket

def _require_bearer(request: Request) -> None:
    if not API_BEARER_TOKEN:
        return
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ") or auth.split(" ", 1)[1].strip() != API_BEARER_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

def _maybe_protect_routes(request: Request) -> None:
    if not PROTECT_APPROVE_ROUTES:
        return
    if not API_BEARER_TOKEN:
        # fail closed if protection enabled but token missing
        raise HTTPException(status_code=503, detail="Route protection enabled but API_BEARER_TOKEN missing")
    _require_bearer(request)

def _rows_kv_html(t: Dict[str, Any]) -> str:
    def cv(k, default="—"):
        v = t.get(k, default)
        return default if v in (None, "", []) else _md_html(str(v))
    rows = []
    for k in ("ticket_id","symbol","side","qty","leverage","position_side","budget","score",
              "tp1","tp2","tp3","sl","eta_tp1_min","eta_tp2_min","eta_tp3_min",
              "prob_overall_pct","prob_tp1_pct","prob_tp2_pct","prob_tp3_pct",
              "tp_splits","expiry_ts","note"):
        rows.append(f"<tr><th style='text-align:left;padding:.35rem .6rem;background:#fafafa'>{k}</th>"
                    f"<td style='padding:.35rem .6rem'>{cv(k)}</td></tr>")
    return "\n".join(rows)

# --- UI routes (HTML) ---
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
    approve_url = f"{base}/ops/approve?ticket_id={ticket_id}"
    reject_url  = f"{base}/ops/reject?ticket_id={ticket_id}"

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
        "<p style='color:#777;margin-top:1rem'>טיפ: ניתן לקרוא/לאשר גם מהטלגרם.</p>"
        "</body>"
    )
    return HTMLResponse(body)

@router.get("/ops/ui/pending")
async def ui_pending(request: Request = None):
    _require_bearer(request)
    base = PUBLIC_HOST.rstrip("/") if PUBLIC_HOST else (str(request.base_url).rstrip("/") if request else "")
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
                req = it.get("req") or it
                items.append(req)

    if not items:
        return _html("אין כרטיסים ממתינים כרגע.")

    rows = []
    for t in items:
        raw_tid = str(t.get("ticket_id",""))
        tid_disp = _md_html(raw_tid)
        sym = _md_html(str(t.get("symbol","")))
        side = _md_html(str(t.get("side","")))
        qty = _md_html(str(t.get("qty","")))
        lev = _md_html(str(t.get("leverage","")))
        link = f"{base}/ops/ui/ticket?ticket_id={raw_tid}"
        rows.append(
            f"<tr>"
            f"<td style='padding:.4rem .6rem'><a href='{link}'>👁 {tid_disp}</a></td>"
            f"<td style='padding:.4rem .6rem'>{sym}</td>"
            f"<td style='padding:.4rem .6rem'>{side}</td>"
            f"<td style='padding:.4rem .6rem'>{qty}</td>"
            f"<td style='padding:.4rem .6rem'>{lev}</td>"
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
        "<tbody>"
        + "\n".join(rows) +
        "</tbody></table>"
        "</body>"
    )
    return HTMLResponse(body)
# --- Approve/Reject flows ---
@router.get("/ops/approve")
async def approve(ticket_id: str = Query(..., description="ticket_id"), request: Request = None):
    _maybe_protect_routes(request)
    ticket, source = await _load_ticket(ticket_id)
    if not ticket:
        return _html("⚠️ קישור שגוי או שפג תוקף האישור.")
    flow = _decide_flow_by_mode(ticket)

    with suppress(Exception):
        for k in ("blocked_by_rr_min","blocked_by_velocity","velocity_error"):
            ticket.pop(k, None)

    # auto sizing
    t2 = await _apply_auto_qty_on_ticket_async(ticket)
    if t2 is None:
        return _html("⚠️ שגיאה: לא ניתן להביא מחיר עדכני לצורך חישוב כמות אוטומטית.")
    ticket = t2
    if float(ticket.get("qty") or 0) <= 0 or int(ticket.get("leverage") or 0) <= 0:
        return _html("⚠️ שגיאה: qty/leverage חסרים גם לאחר ניסיון חישוב אוטומטי (בדוק ENV AUTO_QTY_*).")

    exec_res = await (_execute_trade(ticket) if flow=="MARKET"
                      else _execute_trade_armed(ticket) if flow=="HYBRID"
                      else (_execute_trade_armed(ticket) if any(ticket.get(k) for k in ("tp1","tp2","tp3","sl")) else _execute_trade(ticket)))
    ok = bool(exec_res.get("ok"))

    if (not ok) and flow in ("HYBRID","AUTO") and APPROVE_FALLBACK_TO_MARKET:
        logger.warning("approve_retry_market_after_hybrid_fail: %s", exec_res)
        retry_res = await _execute_trade(ticket)
        ok = bool(retry_res.get("ok"))
        exec_res = {"primary": "HYBRID", "fallback_market": retry_res, "primary_error": exec_res}

    if ok:
        try:
            sm = _smart_manage_env()
            if sm["enable"]:
                sym = str(ticket.get("symbol","")).upper()
                sm_result = await _smart_manage_now(sym,
                                                    offset_bps=sm["offset_bps"],
                                                    pcts=sm["pcts"],
                                                    splits=sm["splits"],
                                                    atr_mult=sm["atr_mult"])
                logger.info("smart_manage_after_approve: %s -> %s", sym, sm_result)
        except Exception as e:
            logger.warning("smart_manage_after_approve_failed: %s", e)

        with suppress(Exception):
            sym = str(ticket.get("symbol","")).upper()
            ensure_protective_stop(sym, prefer_mode="quantities")

    if not ok:
        logger.warning("approve_failed: ticket=%s flow=%s detail=%s", ticket_id, flow, json.dumps(exec_res, ensure_ascii=False))

    try:
        sym, side, qty = ticket.get("symbol",""), ticket.get("side",""), ticket.get("qty","")
        msg = (
            f"✅ <b>Approved</b>\n• Ticket: <code>{_md_html(ticket_id)}</code>\n"
            f"• {_md_html(sym)} {_md_html(side)} qty=<code>{_md_html(qty)}</code>\n• Flow: <code>{flow}</code>\n— — —\nבוצע והועבר לניהול."
            if ok else
            f"⚠️ <b>Approve Failed</b>\n• Ticket: <code>{_md_html(ticket_id)}</code>\n"
            f"• {_md_html(sym)} {_md_html(side)} qty=<code>{_md_html(qty)}</code>\n• Flow: <code>{flow}</code>\n— — —\n"
            f"שגיאה: <code>{_md_html(json.dumps(exec_res, ensure_ascii=False))}</code>"
        )
        await _send_telegram_html(msg)
    except Exception:
        pass

    if ok:
        with suppress(Exception):
            record_approval_approved()
    else:
        with suppress(Exception):
            record_approval_rejected()

    await _delete_ticket(ticket_id, source, final_status=ok)

    if ok:
        return _html("✅ אושר — הוזמן ונכנס לניהול דינמי.")
    if DEBUG_APPROVE_HTML:
        return _html("⚠️ שגיאה בביצוע — " + _md_html(json.dumps(exec_res, ensure_ascii=False)))
    return _html("⚠️ שגיאה בביצוע — ראה פירוט בטלגרם/לוגים.")

@router.get("/ops/approve-link")
async def approve_link(id: str = Query(..., description="ticket_id"), request: Request = None):
    return await approve(ticket_id=id, request=request)

@router.get("/ops/reject")
async def reject(ticket_id: str = Query(..., description="ticket_id"), request: Request = None):
    _maybe_protect_routes(request)
    _, source = await _load_ticket(ticket_id)
    await _delete_ticket(ticket_id, source, final_status=False)
    with suppress(Exception):
        await _send_telegram_html(
            f"❌ <b>Rejected</b>\n• Ticket: <code>{_md_html(ticket_id)}</code>\n— — —\nNo action was taken."
        )
    with suppress(Exception):
        record_approval_rejected()
    return _html("❌ נדחה. לא בוצעה פעולה.")

@router.post("/ops/approve/signed")
async def approve_signed(request: Request):
    if not HMAC_SECRET:
        raise HTTPException(status_code=500, detail="HMAC secret not set")

    # --- Anti-replay headers ---
    ts_hdr = request.headers.get("X-Timestamp")
    nonce  = request.headers.get("X-Nonce") or ""
    if not ts_hdr or not nonce:
        raise HTTPException(status_code=400, detail="Missing X-Timestamp or X-Nonce")
    try:
        ts = float(ts_hdr)
    except Exception:
        raise HTTPException(status_code=400, detail="Bad X-Timestamp")

    now = time.time()
    if abs(now - ts) > SIGNED_TS_MAX_SKEW_SEC:
        raise HTTPException(status_code=401, detail="Timestamp skew too large")

    # Nonce once-only via Redis (if available)
    if aioredis and REDIS_URL:
        r = await _get_redis_cached()
        if not r:
            return JSONResponse(status_code=503, content={"ok": False, "error": "redis_unavailable"})
        used = await r.set(f"{NS}:nonce:{nonce}", "1", ex=SIGNED_NONCE_TTL_SEC, nx=True)
        if not used:
            raise HTTPException(status_code=409, detail="Replay detected")
    elif REQUIRE_REDIS:
        # If Redis is required, fail-closed
        raise HTTPException(status_code=503, detail="Nonce store unavailable")

    raw = await request.body()
    got = request.headers.get("X-Signature", "") or ""
    # signature covers ts + nonce + raw body
    to_sign = f"{ts_hdr}.{nonce}.".encode("utf-8") + raw
    want = _sign_hex(HMAC_SECRET, to_sign)
    if not hmac.compare_digest(got, want):
        raise HTTPException(status_code=401, detail="Bad signature")

    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    t2 = await _apply_auto_qty_on_ticket_async(payload)
    if t2 is None:
        raise HTTPException(status_code=400, detail="AUTO_QTY: failed to fetch last price")
    payload = t2
    if float(payload.get("qty") or 0) <= 0 or int(payload.get("leverage") or 0) <= 0:
        raise HTTPException(status_code=400, detail="AUTO_QTY: qty/leverage missing after auto sizing")

    flow = _decide_flow_by_mode(payload)
    exec_res = await (_execute_trade(payload) if flow=="MARKET"
                      else _execute_trade_armed(payload) if flow=="HYBRID"
                      else (_execute_trade_armed(payload) if any(payload.get(k) for k in ("tp1","tp2","tp3","sl")) else _execute_trade(payload)))
    ok = bool(exec_res.get("ok"))
    if not ok:
        logger.warning("approve_signed_failed: %s", json.dumps(exec_res, ensure_ascii=False))
        if flow in ("HYBRID","AUTO") and APPROVE_FALLBACK_TO_MARKET:
            retry = await _execute_trade(payload)
            if not retry.get("ok"):
                raise HTTPException(status_code=502, detail={"execute_error": exec_res, "fallback_market": retry})
            exec_res = {"primary": exec_res, "fallback_market": retry}
        else:
            raise HTTPException(status_code=502, detail={"execute_error": exec_res})

    try:
        sm = _smart_manage_env()
        if sm["enable"]:
            sym = str(payload.get("symbol","")).upper()
            sm_result = await _smart_manage_now(sym,
                                                offset_bps=sm["offset_bps"],
                                                pcts=sm["pcts"],
                                                splits=sm["splits"],
                                                atr_mult=sm["atr_mult"])
            logger.info("smart_manage_after_approve_signed: %s -> %s", sym, sm_result)
    except Exception as e:
        logger.warning("smart_manage_after_approve_signed_failed: %s", e)

    with suppress(Exception):
        sym = str(payload.get("symbol","")).upper()
        ensure_protective_stop(sym, prefer_mode="quantities")

    with suppress(Exception):
        record_approval_approved()
    return {"ok": True, "ticket_id": payload.get("ticket_id"), "executed": True, "flow": flow, "internal_execute": exec_res}

# --- Guard smoke run ---
@router.post("/guard/smoke/run")
async def guard_smoke_run(request: Request, symbols: Optional[str] = Body(None)):
    _require_bearer(request)

    if "ensure_protective_stop" not in globals():
        raise HTTPException(status_code=501, detail="ensure_protective_stop() not available")

    if isinstance(symbols, str) and symbols.strip():
        sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    else:
        sym_list = [s.strip().upper() for s in (os.getenv("WATCHLIST","") or "").split(",") if s.strip()]
    if not sym_list:
        raise HTTPException(status_code=400, detail="no symbols to check")

    results: Dict[str, Any] = {}
    emergencies: List[str] = []

    for s in sym_list:
        try:
            res = ensure_protective_stop(s, prefer_mode="quantities")
        except Exception as e:
            res = {"ok": False, "error": str(e)}

        results[s] = res

        flag = False
        try:
            if isinstance(res, dict):
                flag = bool(res.get("emergency")) or bool(res.get("placed")) or (str(res.get("action","")).lower() in ("emergency","place"))
        except Exception:
            pass
        if flag:
            emergencies.append(s)

    if emergencies:
        lines = ["🚨 <b>Smoke Guard</b> · Emergency protective SL placed", f"• Symbols: <code>{','.join(emergencies)}</code>"]
        await _send_telegram_html("\n".join(lines))

    return {"ok": True, "checked": sym_list, "emergencies": emergencies, "results": results}

# --- Ops digest: expired approvals ---
@router.get("/ops/digest/expired")
async def digest_expired(hours: int = Query(6, ge=1, le=48), request: Request = None):
    if PROTECT_DIGEST_ROUTES:
        _require_bearer(request)
    if not (aioredis and REDIS_URL and BOT_TOKEN and ADMIN_CHAT_ID):
        return {"ok": False, "error": "digest_dependencies_missing"}
    try:
        r = await _get_redis_cached()
        if not r:
            return {"ok": False, "error": "redis_unavailable"}

        key_good = f"{NS}:expired_log"
        key_bad  = f"{NS}:expired_log_bad"

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

        by_sym = Counter((str(e.get("symbol","")).upper(), str(e.get("side","")).upper()) for e in events)
        lines = [f"⏱️ <b>Expired approvals</b> (last {hours}h) · total: <b>{total}</b>"]
        for (sym, side), cnt in by_sym.most_common(20):
            lines.append(f"• {sym} {side}: <code>{cnt}</code>")
        lines.append("— — —")
        lines.append("<b>Last events</b>:")
        for e in events[:5]:
            t = int(e.get("ts", now))
            idem = e.get("idem","")
            sym  = str(e.get("symbol","")).upper()
            side = str(e.get("side","")).upper()
            lines.append(f"• {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(t))}Z · {sym} {side} · <code>{idem}</code>")
        await _send_telegram_html("\n".join(lines))
        return {"ok": True, "sent": True, "count": total}
    except Exception as e:
        logger.warning("digest_expired_failed: %s", e)
        return {"ok": False, "error": str(e)}

# --- Register routers ---
app.include_router(router)

with suppress(Exception):
    from routes.position_ops import router as position_ops_router  # type: ignore
    app.include_router(position_ops_router)

with suppress(Exception):
    from routes.locked_report import router as locked_router  # type: ignore
    app.include_router(locked_router)

with suppress(Exception):
    from routes.scan_public import router as scan_public_router  # type: ignore
    app.include_router(scan_public_router)

with suppress(Exception):
    from routes.scan_top_volume import router as scan_router  # type: ignore
    app.include_router(scan_router)

with suppress(Exception):
    from routes.topk import router as topk_router  # type: ignore
    app.include_router(topk_router)

with suppress(Exception):
    from routes import debug_auth as routes_debug_auth  # type: ignore
    app.include_router(routes_debug_auth.router)

# --- Meta routes ---
@app.get("/", response_class=PlainTextResponse, tags=["meta"])
def root() -> str:
    name = os.getenv("APP_NAME", "algogpt")
    return f"{name} online"

@app.head("/", response_class=PlainTextResponse, tags=["meta"])
def root_head() -> str:
    return ""

@app.get("/health", response_class=PlainTextResponse, tags=["meta"])
@app.head("/health", response_class=PlainTextResponse)
def health() -> str:
    return "ok"

@app.get("/healthz", response_class=PlainTextResponse, tags=["meta"])
def healthz() -> str:
    return "ok"

@app.get("/readyz", response_class=PlainTextResponse, tags=["meta"])
async def readyz() -> str:
    # אם נדרשת זמינות Redis בפרודקשן, בדוק PING
    if REQUIRE_REDIS:
        if not (aioredis and REDIS_URL):
            return PlainTextResponse("redis_unconfigured", status_code=503)
        try:
            r = await _get_redis_cached()
            if not r:
                return PlainTextResponse("redis_unavailable", status_code=503)
            pong = await r.ping()
            if not pong:
                return PlainTextResponse("redis_ping_failed", status_code=503)
        except Exception as e:
            logger.warning("readyz redis ping failed: %s", e)
            return PlainTextResponse("redis_exception", status_code=503)
    return "ok"

@app.get("/health/live", response_class=PlainTextResponse, tags=["meta"])
def health_live() -> str:
    return "ok"

@app.get("/health/strategy-version", tags=["meta"])
def health_strategy_version() -> Dict[str, str]:
    return {"ok": True, "version": os.getenv("ALGOGPT_VERSION", "unknown")}

@app.get("/meta/version", tags=["meta"])
def meta_version() -> Dict[str, str]:
    return {"ok": True, "version": os.getenv("ALGOGPT_VERSION", "unknown")}

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

# --- Health TP1 utils ---
try:
    from utils.health_tp1 import health_check_tp1_tags, quick_check_tp1  # type: ignore
    _health_tp1_loaded = True
except Exception as _e:
    logger.warning("health_tp1 utils import failed: %s", _e)
    _health_tp1_loaded = False

@app.get("/health/tp1", tags=["meta"])
async def health_tp1_now(symbols: Optional[str] = Query(None, description="CSV of symbols; default from WATCHLIST")):
    if not _health_tp1_loaded:
        raise HTTPException(status_code=501, detail="health_tp1 module not loaded")
    sym_list = [s.strip().upper() for s in (symbols.split(",") if symbols else (os.getenv("WATCHLIST","") or "").split(",")) if s.strip()]
    if not sym_list:
        raise HTTPException(status_code=400, detail="no symbols")
    # שימוש ברשימה המעובדת (TP1_TAGS) ולא במחרוזת
    res = await quick_check_tp1(sym_list, tp1_tags=(TP1_TAGS or None), notify_telegram=True)
    return {"ok": True, "result": res}

# --- Global error handler ---
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    error_id = secrets.token_hex(6)
    logger.exception("unhandled_error [%s]: %s %s", error_id, request.method, request.url)
    show_detail = os.getenv("SHOW_INTERNAL_ERRORS", "0").lower() in ("1","true","yes","on") or LOG_LEVEL == "DEBUG"
    payload: Dict[str, Any] = {"ok": False, "error": "internal_error", "id": error_id}
    if show_detail:
        payload["detail"] = str(exc)
    return JSONResponse(status_code=500, content=payload)

# =================================================
# Startup / Shutdown background tasks
# =================================================
_manager_lock = asyncio.Lock()
_manager_backoff = 0.0  # seconds

@app.on_event("startup")
async def _startup_tasks():
    if getattr(app.state, "bg_started", False):
        logger.info("startup: background already started – skipping")
        return
    app.state.bg_started = True

    async def _notify_bot_online():
        with suppress(Exception):
            await asyncio.sleep(0.7)
            name = os.getenv("APP_TITLE", "AlgoGPT Supervisor")
            env  = os.getenv("ENV", os.getenv("ENVIRONMENT","prod"))
            await _send_telegram_html(f"🟢 <b>Bot online</b> · <code>{name}</code> · env=<code>{env}</code>")
    asyncio.create_task(_notify_bot_online())

    # Health TP1 watchdog
    if _health_tp1_loaded and (os.getenv("HEALTH_TP1_ENABLE","1").lower() in ("1","true","yes","on")):
        watch = [s.strip() for s in (os.getenv("WATCHLIST","") or "").split(",") if s.strip()]
        if watch:
            async def _run_health():
                try:
                    await health_check_tp1_tags(watch, interval_sec=int(os.getenv("HEALTH_TP1_INTERVAL_SEC","600")))
                except asyncio.CancelledError:
                    logger.info("health_tp1 background: cancelled, exiting cleanly")
                    raise
                except Exception as e:
                    logger.warning("health_tp1 background error: %s", e)
            asyncio.create_task(_run_health())
            logger.info("health_tp1 background started (interval=%ss, symbols=%s)",
                        int(os.getenv("HEALTH_TP1_INTERVAL_SEC","600")), ",".join(watch))

    # Periodic manager calls
    async def periodic_manager():
        global _manager_backoff
        await asyncio.sleep(2.0)
        token = API_BEARER_TOKEN
        if not token:
            logger.info("periodic_manager: missing API_BEARER_TOKEN; skipping")
            return
        syms = [s.strip() for s in (os.getenv("WATCHLIST","") or "").split(",") if s.strip()]
        if not syms:
            return
        base = get_internal_base()
        every_sec = max(10, int(os.getenv("TRADE_MANAGER_INTERVAL_SEC","60")))
        per_req_timeout = httpx.Timeout(connect=2.5, read=15.0, write=10.0)
        try:
            while True:
                sleep_extra = _manager_backoff
                if sleep_extra > 0:
                    await asyncio.sleep(sleep_extra)
                async with _manager_lock:
                    try:
                        cli = _get_shared_async_client()
                        for s in syms:
                            r = await cli.post(
                                f"{base}/position-ops/manage-once",
                                headers={"Authorization": f"Bearer {token}"},
                                json={"symbol": s},
                                timeout=per_req_timeout,
                            )
                            if r.status_code < 400:
                                _manager_backoff = max(0.0, _manager_backoff * 0.5 - 2.0)
                            elif r.status_code in (429, 500, 502, 503, 504):
                                _manager_backoff = min((_manager_backoff or 0) * 1.6 + 5, 90)
                                logger.warning("periodic_manager_backoff: status=%s backoff=%ss", r.status_code, _manager_backoff)
                            else:
                                logger.warning("periodic_manager_unexpected_status: %s %s", r.status_code, r.text[:200])
                    except Exception as e:
                        _manager_backoff = min((_manager_backoff or 0) * 1.5 + 5, 90)
                        logger.warning("periodic_manager_error: %r (backoff now %.1fs)", e, _manager_backoff)
                await asyncio.sleep(every_sec)
        except asyncio.CancelledError:
            logger.info("periodic_manager: cancelled, exiting cleanly")
            raise

    if os.getenv("MANAGER_ENABLE","1").lower() in ("1","true","yes","on"):
        asyncio.create_task(periodic_manager())

    # Guarder
    async def periodic_guarder():
        await asyncio.sleep(3.0)
        syms = [s.strip().upper() for s in (os.getenv("WATCHLIST","") or "").split(",") if s.strip()]
        if not syms:
            return
        try:
            while True:
                try:
                    for s in syms:
                        with suppress(Exception):
                            ensure_protective_stop(s, prefer_mode="quantities")
                except Exception:
                    pass
                await asyncio.sleep(int(os.getenv("GUARDER_INTERVAL_SEC","45")))
        except asyncio.CancelledError:
            logger.info("periodic_guarder: cancelled, exiting cleanly")
            raise
    if os.getenv("GUARDER_ENABLE","1").lower() in ("1","true","yes","on"):
        asyncio.create_task(periodic_guarder())

    # Scanner
    async def periodic_scanner():
        try:
            from routes.scan_top_volume import scan_top_volume  # type: ignore
        except Exception as e:
            logger.warning("periodic_scanner_unavailable: %s", e)
            return

        await asyncio.sleep(4.0)
        every       = int(os.getenv("SCAN_CRON_EVERY_SEC", "45") or "45")
        tf          = os.getenv("SCAN_CRON_TIMEFRAME", "15m") or "15m"
        kline_limit = int(os.getenv("SCAN_CRON_KLINES", "200") or "200")
        limit       = int(os.getenv("SCAN_CRON_LIMIT", "12") or "12")
        min_score   = float(os.getenv("SCAN_CRON_MIN_SCORE", "7.0") or "7.0")
        rearm_score = float(os.getenv("SCAN_REARM_SCORE", "6.0") or "6.0")
        dedupe_sec  = int(os.getenv("SCAN_DEDUPE_WINDOW_SEC", "300") or "300")
        ttl_sec     = int(os.getenv("SCAN_TTL_SEC", "900") or "900")
        leverage    = float(os.getenv("DEFAULT_LEVERAGE", "5") or "5")
        stake       = float(os.getenv("DEFAULT_STAKE_USDT", "50") or "50")
        rich        = (os.getenv("SCAN_RICH", "1").lower() in ("1","true","yes","on"))
        chat        = os.getenv("TELEGRAM_CHAT_ID")

        if not chat:
            logger.info("periodic_scanner: TELEGRAM_CHAT_ID missing; skipping")
            return

        try:
            while True:
                try:
                    await scan_top_volume(
                        market="futures",
                        quote="USDT",
                        limit=limit,
                        timeframe=tf,
                        kline_limit=kline_limit,
                        min_score=min_score,
                        require_side=True,
                        notify="telegram",
                        chat_id=str(chat),
                        rich=rich,
                        ttl_sec=ttl_sec,
                        rearm_score=rearm_score,
                        dedupe_window_sec=dedupe_sec,
                        leverage=leverage,
                        stake_usdt=stake,
                    )
                except Exception as e:
                    logger.warning("periodic_scanner_error: %s", e)
                await asyncio.sleep(max(10, every))
        except asyncio.CancelledError:
            logger.info("periodic_scanner: cancelled, exiting cleanly")
            raise

    if os.getenv("SCAN_CRON_ENABLE","1").lower() in ("1","true","yes","on"):
        asyncio.create_task(periodic_scanner())

@app.on_event("shutdown")
async def _shutdown_tasks():
    # close shared HTTP client
    cli: Optional[httpx.AsyncClient] = getattr(app.state, "shared_async_client", None)
    if cli and not cli.is_closed:
        with suppress(Exception):
            await cli.aclose()
    # close redis if present (try both close and pool disconnect for different redis-py versions)
    r = getattr(app.state, "redis", None)
    if r:
        with suppress(Exception):
            await r.close()
        with suppress(Exception):
            await r.connection_pool.disconnect()
    logger.info("shutdown: resources closed, goodbye")

# =================================================
# Uvicorn entry
# =================================================
if __name__ == "__main__":
    import uvicorn
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "10000"))
    reload_ = os.getenv("UVICORN_RELOAD", "0").lower() in ("1", "true", "yes", "on")
    module_target = os.getenv("UVICORN_APP") or f"{os.path.splitext(os.path.basename(__file__))[0]}:app"
    uvicorn.run(module_target, host=host, port=port, reload=reload_)
































































































































































































































































































































































































































































































































































































































































