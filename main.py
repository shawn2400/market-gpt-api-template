# main.py
from __future__ import annotations

import os
import json
import time
import hmac
import math
import re
import httpx
import hashlib
import secrets
import logging
import traceback
import inspect
import asyncio
from contextlib import suppress
from typing import Any, Dict, List, Optional, Callable, Tuple
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
# Simple in-memory ConfirmStore (fallback)
# =================================================
class ConfirmStore:
    """
    Very small in-memory ticket store used as a fallback when Redis isn't available.
    {
        "ticket_id": str,
        "req": dict,
        "ts": float,
        "approved": None|bool
    }
    """
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in CORS_ALLOW_ORIGINS.split(",")] if CORS_ALLOW_ORIGINS else ["*"],
    allow_credentials=CORS_ALLOW_CREDENTIALS,
    allow_methods=[m.strip() for m in CORS_ALLOW_METHODS.split(",")] if CORS_ALLOW_METHODS else ["*"],
    allow_headers=[h.strip() for h in CORS_ALLOW_HEADERS.split(",")] if CORS_ALLOW_HEADERS else ["*"],
)

# =================================================
# OPS APPROVE (inlined router)
# =================================================
router = APIRouter(tags=["ops-approval"])

# --- Guard import (quiet) ---
with suppress(Exception):
    from utils.guard_stop import ensure_protective_stop  # type: ignore

# optional metrics (no-op fallbacks)
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

# Optional Redis
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

# ===== Health TP1 config =====
HEALTH_TP1_ENABLE = _bool_env("HEALTH_TP1_ENABLE", True)
HEALTH_TP1_INTERVAL_SEC = int(os.getenv("HEALTH_TP1_INTERVAL_SEC", "600"))
TP1_TAGS = [t.strip() for t in (os.getenv("TP1_TAGS","") or "").split(",") if t.strip()]
SL_TAGS = [t.strip() for t in (os.getenv("SL_TAGS","SL,STOP,STOP_LOSS,STOP_LOSS_LIMIT,STOP_MARKET") or "").split(",") if t.strip()]

# =================================================
# ClientOrderId builder (recommended format)
# =================================================
def _coid_fit(s: str, limit: int = 32) -> str:
    if len(s) <= limit:
        return s
    h = hashlib.md5(s.encode("utf-8")).hexdigest()[:7]
    return f"{s[:limit-8]}_{h}"

def build_client_order_id(symbol: str, side: str, role: str = "ENTRY", extra: Optional[str] = None) -> str:
    """
    Recommended format (<=32 chars safe): {PREFIX}_{SYM}_{SIDE}_{ROLE}_{TS}[_{EXTRA}]
    PREFIX from ORDER_ID_PREFIX (default ALG_MAIN).
    ROLE in: ENTRY | TP1 | TP2 | TP3 | SL | BE | TRAIL | MANUAL
    """
    prefix = (os.getenv("ORDER_ID_PREFIX") or "ALG_MAIN").strip() or "ALG_MAIN"
    sym = str(symbol).upper()
    sd  = str(side).upper()
    role = str(role).upper()
    ts = int(time.time())
    base = f"{prefix}_{sym}_{sd}_{role}_{ts}"
    if extra:
        base = f"{base}_{re.sub(r'[^A-Z0-9]+','',str(extra).upper())}"
    return _coid_fit(base, 32)

# Position sizing (AUTO_QTY)
try:
    from app.utils.position_sizing import ensure_final_qty  # type: ignore
except Exception:
    with suppress(Exception):
        from utils.position_sizing import ensure_final_qty  # type: ignore
    if "ensure_final_qty" not in globals():
        def ensure_final_qty(ticket: Dict[str, Any], price: float) -> Dict[str, Any]:
            return ticket

# Prices
def _get_last_price(symbol: str) -> Optional[float]:
    with suppress(Exception):
        from utils.binance_client import get_price  # type: ignore
        p = get_price(symbol)
        if p:
            return float(p)
    with suppress(Exception):
        from binance.client import Client  # type: ignore
        api_key = os.getenv("BINANCE_API_KEY","").strip()
        api_sec = os.getenv("BINANCE_API_SECRET","").strip()
        if not api_key or not api_sec:
            return None
        cli = Client(api_key, api_sec)
        info = cli.futures_symbol_ticker(symbol=symbol)
        if info and "price" in info:
            return float(info["price"])
    return None

# Helpers
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

async def _redis():
    if not (aioredis and REDIS_URL):
        return None
    return aioredis.from_url(REDIS_URL, decode_responses=True)

# Mode parsing
_MODE_RX = re.compile(r"\[mode:\s*(MARKET|HYBRID|AUTO)\s*\]", flags=re.I)
def _parse_mode(note: Optional[str]) -> Optional[str]:
    if not note:
        return None
    m = _MODE_RX.search(str(note))
    return m.group(1).upper() if m else None

# Telegram
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
    try:
        async with httpx.AsyncClient(timeout=12.0) as cli:
            r = await cli.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json=payload)
        try:
            data = r.json()
        except Exception:
            data = {"ok": False, "status": r.status_code, "text": r.text}
        return data
    except Exception as e:
        return {"ok": False, "error": str(e)}

# utils: dynamic kwargs filter
def _filter_kwargs_for_callable(fn: Callable[..., Any], kwargs: Dict[str, Any]) -> Dict[str, Any]:
    try:
        sig = inspect.signature(fn)
        allowed = set(sig.parameters.keys())
        return {k: v for k, v in kwargs.items() if k in allowed}
    except Exception:
        bad = {"tp_kind","sl_kind","entry_kind","entry_offset","tp_offset","sl_offset"}
        return {k: v for k, v in kwargs.items() if k not in bad}

def _is_code_4061(err: Exception | str) -> bool:
    s = str(err)
    return "code=-4061" in s or "position side does not match" in s.lower()

# Position mode alignment
def _align_position_mode(client) -> None:
    mode_override = (os.getenv("POSITION_MODE_OVERRIDE","") or "").strip().lower()
    with suppress(Exception):
        if mode_override in ("hedge","dual","dual_side","dual_side_position","dualposition"):
            client.futures_change_position_mode(dualSidePosition="true")
        elif mode_override in ("oneway","one_way","single","single_side","oneside"):
            client.futures_change_position_mode(dualSidePosition="false")

# Execution backends
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

# Smart ETA
def _calc_velocity_per_min(symbol: str, interval: str, window_min: int) -> Optional[float]:
    try:
        from utils.get_klines import get_klines_sync  # type: ignore
        m = {"1m":1, "3m":3, "5m":5, "15m":15, "30m":30, "1h":60}.get(interval, 15)
        n = max(10, math.ceil(window_min / m) + 5)
        kl = get_klines_sync(symbol, interval=interval, limit=n) or []

        closes: List[float]
        try:
            if 'DataFrame' in str(type(kl)):
                cols = getattr(kl, 'columns', [])
                if hasattr(kl, 'columns') and ('close' in cols):
                    closes = [float(x) for x in kl['close'].tolist()]
                else:
                    closes = [float(x) for x in kl.iloc[:, 4].tolist()]
            else:
                closes = [float(x[4]) for x in kl if len(x) >= 5]
        except Exception:
            closes = [float(x[4]) for x in kl if isinstance(x, (list, tuple)) and len(x) >= 5]

        if len(closes) < 2:
            return None
        deltas = [abs(closes[i] - closes[i-1]) for i in range(1, len(closes))]
        avg_per_candle = sum(deltas) / len(deltas)
        per_min = avg_per_candle / m
        return per_min if per_min > 0 else None
    except Exception as e:
        (logger.info if VELOCITY_LOG_LEVEL == "INFO" else logger.warning)("velocity_calc_failed: %s", e)
        return None

def _smart_etas(symbol: str, side: str, price_now: Optional[float], tp1=None, tp2=None, tp3=None,
                interval: str = DEFAULT_INTERVAL, window_min: int = ETA_VELOCITY_WINDOW) -> Dict[str, Optional[int]]:
    vpm = _calc_velocity_per_min(symbol, interval, window_min)
    if not (price_now and isinstance(vpm, (int, float)) and vpm > 0):
        return {"eta_tp1_min": None, "eta_tp2_min": None, "eta_tp3_min": None}
    def _eta(tgt):
        if tgt is None: return None
        dist = abs(float(tgt) - float(price_now))
        return int(math.ceil(dist / vpm)) if vpm > 0 else None
    return {"eta_tp1_min": _eta(tp1), "eta_tp2_min": _eta(tp2), "eta_tp3_min": _eta(tp3)}

# Storage abstraction (redis + ConfirmStore)
import json as _json

async def _load_ticket(tid: str) -> Tuple[Optional[Dict[str, Any]], str]:
    if aioredis and REDIS_URL:
        try:
            r = await _redis()
            if r:
                raw = await r.get(f"{NS}:ticket:{tid}")
                if raw:
                    rec = _json.loads(raw)
                    from time import time as _now
                    if (_now() - float(rec.get("ts", 0))) <= TICKET_TTL_SEC:
                        return (rec.get("req") or rec), "redis"
        except Exception as e:
            logger.warning("redis_load_failed: %s", e)
    try:
        for it in (ConfirmStore.pending() or []):
            if str(it.get("ticket_id")) == str(tid):
                return (it.get("req") or it), "confirmstore"
    except Exception as e:
        logger.warning("confirmstore_load_failed: %s", e)
    return None, "none"

async def _delete_ticket(tid: str, source: str) -> None:
    if source == "redis" and aioredis and REDIS_URL:
        try:
            r = await _redis()
            if r:
                await r.delete(f"{NS}:ticket:{tid}")
                return
        except Exception as e:
            logger.warning("redis_delete_failed: %s", e)
    with suppress(Exception):
        ConfirmStore.decide(tid, approved=False)

# -------------------- Smart-Manage helper (immediate after approve) --------------------
async def _smart_manage_now(symbol: str,
                            offset_bps: Optional[int] = None,
                            pcts: Optional[List[float]] = None,
                            splits: Optional[List[float]] = None,
                            atr_mult: Optional[float] = None) -> Dict[str, Any]:
    """
    Triggers /position-ops/manage-once for a given symbol via internal HTTP.
    Controlled by SMART_MANAGE_ON_APPROVE and SMART_MANAGE_* envs.
    """
    base = PUBLIC_HOST.rstrip("/") if PUBLIC_HOST else ""
    token = API_BEARER_TOKEN
    if not base or not token:
        return {"ok": False, "skipped": True, "reason": "missing base or token"}

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

    try:
        async with httpx.AsyncClient(timeout=15.0) as cli:
            r = await cli.post(f"{base}/position-ops/manage-once",
                               headers={"Authorization": f"Bearer {token}"},
                               json=body)
        return {"ok": r.status_code < 300, "status": r.status_code, "text": r.text}
    except Exception as e:
        logger.warning("smart_manage_now_error: %s", e)
        return {"ok": False, "error": str(e)}

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

# -------------------- API: Create Ticket --------------------
@router.post("/ops/ticket", summary="Create approval ticket (Redis + ConfirmStore) – sends Telegram with Preview/Approve/Reject")
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

    # Smart ETA
    if ETA_SMART_ENABLE and (payload.get("tp1") or payload.get("tp2") or payload.get("tp3")):
        price_now = None
        with suppress(Exception):
            price_now = _get_last_price(symbol)
        etas = _smart_etas(symbol, side, price_now, payload.get("tp1"), payload.get("tp2"), payload.get("tp3"))
        for k, v in etas.items():
            payload.setdefault(k, v)

    # optional flags
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

    # RR check (optional)
    with suppress(Exception):
        rr_min_flag = float(req_body.get("rr_min") or 0.0)
        rr_env_lo   = float(os.getenv("APPROVAL_RR_MIN", "0") or "0")
        rr_min_eff  = max(rr_min_flag, rr_env_lo)
        if rr_min_eff > 0 and req_body.get("sl"):
            current = float(_get_last_price(symbol) or 0)
            tp1 = float(req_body.get("tp1") or 0); sl = float(req_body.get("sl") or 0)
            rr  = None
            if side == "BUY" and current > 0 and tp1 > 0 and sl > 0:
                reward = abs(tp1 - current); risk = abs(current - sl); rr = (reward / risk) if risk > 0 else None
            elif side == "SELL" and current > 0 and tp1 > 0 and sl > 0:
                reward = abs(current - tp1); risk = abs(sl - current); rr = (reward / risk) if risk > 0 else None
            if rr is not None and rr < rr_min_eff:
                req_body["blocked_by_rr_min"] = True

    with suppress(Exception):
        ConfirmStore.create(dict(req_body))
    record_approval_created()

    if aioredis and REDIS_URL:
        try:
            r = await _redis()
            if r:
                rec = {"ts": time.time(), "req": req_body, "note": note}
                await r.setex(f"{NS}:ticket:{tid}", TICKET_TTL_SEC, json.dumps(rec, ensure_ascii=False, separators=(",", ":")))
        except Exception as e:
            logger.warning("redis_set_failed: %s", e)

    base = PUBLIC_HOST.rstrip("/") if PUBLIC_HOST else (str(request.base_url).rstrip("/") if request else "")
    approve_url = f"{base}/ops/approve?ticket_id={tid}" if base else ""
    reject_url  = f"{base}/ops/reject?ticket_id={tid}"  if base else ""
    preview_url = f"{base}/ops/ui/ticket?ticket_id={tid}" if base else ""

    lines = []
    lines.append("⚠️ <b>Approval Needed</b>")
    lines.append(f"• Ticket: <code>{_md_html(tid)}</code>")
    lines.append(f"• {_md_html(symbol)} {_md_html(side)} qty=<code>{qty}</code> lev=<code>{lev}</code>")
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

def _apply_auto_qty_on_ticket(ticket: Dict[str, Any]) -> Dict[str, Any] | None:
    symbol = (ticket.get("symbol") or "").upper()
    price = _get_last_price(symbol)
    if not price or float(price) <= 0:
        return None
    new_ticket = ensure_final_qty(dict(ticket), float(price))
    ps = str(new_ticket.get("position_side") or new_ticket.get("positionSide") or "").upper()
    if ps == "BOTH":
        new_ticket.pop("positionSide", None)
        new_ticket["position_side"] = ""
    return new_ticket

# -------------------- UI Helpers --------------------
def _require_bearer(request: Request) -> None:
    if not API_BEARER_TOKEN:
        return
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ") or auth.split(" ", 1)[1].strip() != API_BEARER_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

def _badge(text: str, color: str) -> str:
    return f"<span style='display:inline-block;padding:.15rem .45rem;border-radius:999px;font-size:.8rem;color:#fff;background:{color}'>{_md_html(text)}</span>"

def _status_badge(status: str) -> str:
    s = (status or "").upper()
    color = "#6b7280"
    if s == "NEW": color = "#3b82f6"
    elif s == "PARTIALLY_FILLED": color = "#f59e0b"
    elif s == "FILLED": color = "#10b981"
    elif s in ("CANCELED","EXPIRED","REJECTED"): color = "#ef4444"
    return _badge(s, color)

def _role_badge(role: str) -> str:
    r = (role or "").upper()
    color = "#6b7280"
    if r.startswith("TP"): color = "#16a34a"
    elif r == "SL": color = "#dc2626"
    elif r == "ENTRY": color = "#3b82f6"
    elif r in ("BE","TRAIL"): color = "#a855f7"
    return _badge(r, color)

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

# -------------------- UI: Ticket preview --------------------
@router.get("/ops/ui/ticket", summary="Simple HTML preview for a ticket")
async def ui_ticket(ticket_id: str = Query(...), request: Request = None):
    _require_bearer(request)
    rec, _ = await _load_ticket(ticket_id)
    if not rec:
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

# -------------------- UI: Pending list --------------------
@router.get("/ops/ui/pending", summary="List pending approval tickets")
async def ui_pending(request: Request = None):
    _require_bearer(request)
    base = PUBLIC_HOST.rstrip("/") if PUBLIC_HOST else (str(request.base_url).rstrip("/") if request else "")
    items: List[Dict[str, Any]] = []

    # from Redis (fresh by TTL)
    if aioredis and REDIS_URL:
        with suppress(Exception):
            r = await _redis()
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

    # from ConfirmStore
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

# -------------------- UI: Live Orders (TP/SL/Entry)
@router.get("/ops/ui/orders", summary="List open orders for a symbol (highlights TP1 via tags)")
async def ui_orders(symbol: str = Query(..., description="Symbol, e.g. SOLUSDT"), request: Request = None):
    _require_bearer(request)
    try:
        from binance.client import Client  # type: ignore
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"binance import failed: {e}")

    api_key = os.getenv("BINANCE_API_KEY","").strip()
    api_sec = os.getenv("BINANCE_API_SECRET","").strip()
    if not api_key or not api_sec:
        raise HTTPException(status_code=500, detail="BINANCE keys missing")

    client = Client(api_key, api_sec)
    sym = symbol.upper().strip()
    with suppress(Exception):
        _align_position_mode(client)

    try:
        orders = client.futures_get_open_orders(symbol=sym) or []
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"futures_get_open_orders error: {e}")

    tp1_tags = set(t.upper() for t in TP1_TAGS) if TP1_TAGS else set()
    sl_tags = set(t.upper() for t in SL_TAGS)

    def detect_role(o: Dict[str, Any]) -> str:
        typ = (o.get("type") or "").upper()
        cid = (o.get("clientOrderId") or "").upper()
        if "TAKE_PROFIT" in typ:
            role_guess = "TP?"
            for t in ("TP1","TP_1","TP-1","TAKE_PROFIT_1"):
                if t in cid:
                    return "TP1"
            if "TP2" in cid: return "TP2"
            if "TP3" in cid: return "TP3"
            if any(t in cid for t in tp1_tags):
                return "TP1"
            return role_guess
        if "STOP" in typ or any(t in cid for t in sl_tags):
            return "SL"
        if "ENTRY" in cid or "OPEN" in cid:
            return "ENTRY"
        return "OTHER"

    try:
        last_price = _get_last_price(sym) or 0.0
    except Exception:
        last_price = 0.0

    enriched: List[Dict[str, Any]] = []
    for o in orders:
        role = detect_role(o)
        enriched.append({**o, "_role": role})

    if not any(x["_role"] == "TP1" for x in enriched):
        tps = [x for x in enriched if x["_role"].startswith("TP")]
        if len(tps) >= 1 and last_price > 0:
            def dist(o):
                p = float(o.get("price") or o.get("stopPrice") or 0) or 0.0
                return abs(p - last_price)
            tps_sorted = sorted(tps, key=dist)
            if tps_sorted:
                tps_sorted[0]["_role"] = "TP1"

    base = PUBLIC_HOST.rstrip("/") if PUBLIC_HOST else (str(request.base_url).rstrip("/") if request else "")
    health_link = f"{base}/health/tp1?symbols={sym}"

    head = (
        "<!doctype html><meta charset='utf-8'>"
        "<body style='font-family:sans-serif;max-width:1100px;margin:2rem auto;line-height:1.5'>"
        f"<h2 style='margin:0 0 .6rem 0'>Open Orders · <code>{_md_html(sym)}</code></h2>"
        f"<div style='margin:0 0 1rem 0'><a href='{health_link}' style='text-decoration:none'>{_badge('Check TP1 Health', '#0ea5e9')} 🔍</a></div>"
        "<table style='border-collapse:collapse;width:100%;border:1px solid #eee'>"
        "<thead><tr style='background:#fafafa'>"
        "<th style='text-align:left;padding:.45rem .6rem'>Status</th>"
        "<th style='text-align:left;padding:.45rem .6rem'>Role</th>"
        "<th style='text-align:left;padding:.45rem .6rem'>Type</th>"
        "<th style='text-align:left;padding:.45rem .6rem'>Side</th>"
        "<th style='text-align:right;padding:.45rem .6rem'>Qty</th>"
        "<th style='text-align:right;padding:.45rem .6rem'>Price</th>"
        "<th style='text-align:right;padding:.45rem .6rem'>Stop</th>"
        "<th style='text-align:left;padding:.45rem .6rem'>Client ID</th>"
        "<th style='text-align:left;padding:.45rem .6rem'>ReduceOnly</th>"
        "<th style='text-align:left;padding:.45rem .6rem'>PositionSide</th>"
        "<th style='text-align:left;padding:.45rem .6rem'>Time</th>"
        "</tr></thead><tbody>"
    )
    rows = []
    def fmt_float(x):
        try:
            f = float(x)
            return f"{f:.6g}"
        except Exception:
            return str(x or "")

    for o in enriched:
        status = _status_badge(str(o.get("status","")))
        role_badge = _role_badge(o.get("_role","OTHER"))
        typ = _md_html(str(o.get("type","")))
        side = _md_html(str(o.get("side","")))
        qty = fmt_float(o.get("origQty") or o.get("origqty"))
        price = fmt_float(o.get("price"))
        stop = fmt_float(o.get("stopPrice"))
        coid = _md_html(str(o.get("clientOrderId","")))
        ro = "Yes" if str(o.get("reduceOnly","false")).lower() == "true" else "No"
        ps = _md_html(str(o.get("positionSide","")))
        t_ms = int(o.get("time") or o.get("updateTime") or 0)
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(t_ms/1000)) + "Z" if t_ms else "—"

        highlight = "background:#f0fff4" if o.get("_role") == "TP1" else "background:#fff"
        rows.append(
            f"<tr style='{highlight}'>"
            f"<td style='padding:.4rem .6rem'>{status}</td>"
            f"<td style='padding:.4rem .6rem;font-weight:600'>{role_badge}</td>"
            f"<td style='padding:.4rem .6rem'>{typ}</td>"
            f"<td style='padding:.4rem .6rem'>{side}</td>"
            f"<td style='padding:.4rem .6rem;text-align:right'>{qty}</td>"
            f"<td style='padding:.4rem .6rem;text-align:right'>{price}</td>"
            f"<td style='padding:.4rem .6rem;text-align:right'>{stop}</td>"
            f"<td style='padding:.4rem .6rem'><code>{coid}</code></td>"
            f"<td style='padding:.4rem .6rem'>{ro}</td>"
            f"<td style='padding:.4rem .6rem'>{ps}</td>"
            f"<td style='padding:.4rem .6rem'>{ts}</td>"
            f"</tr>"
        )
    if not rows:
        rows.append("<tr><td colspan='11' style='padding:.8rem .6rem;color:#6b7280'>No open orders.</td></tr>")
    tail = "</tbody></table></body>"
    return HTMLResponse(head + "\n".join(rows) + tail)

# -------------------- Approve/Reject/Approve/Signed --------------------
@router.get("/ops/approve", summary="Approve ticket (supports ticket_id) -> executes trade")
async def approve(ticket_id: str = Query(..., description="ticket_id")):
    ticket, source = await _load_ticket(ticket_id)
    if not ticket:
        return _html("⚠️ קישור שגוי או שפג תוקף האישור.")
    flow = _decide_flow_by_mode(ticket)

    with suppress(Exception):
        for k in ("blocked_by_rr_min","blocked_by_velocity","velocity_error"):
            ticket.pop(k, None)

    t2 = _apply_auto_qty_on_ticket(ticket)
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

    # Smart-Manage immediately after approve (if enabled)
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

        # --- Ensure protective stop (Quantities mode) right after open ---
        with suppress(Exception):
            sym = str(ticket.get("symbol","")).upper()
            ensure_protective_stop(sym, prefer_mode="quantities")

    if not ok:
        logger.warning("approve_failed: ticket=%s flow=%s detail=%s", ticket_id, flow, json.dumps(exec_res, ensure_ascii=False))

    try:
        sym, side, qty = ticket.get("symbol",""), ticket.get("side",""), ticket.get("qty","")
        msg = (
            f"✅ <b>Approved</b>\n• Ticket: <code>{_md_html(ticket_id)}</code>\n"
            f"• {_md_html(sym)} {_md_html(side)} qty={qty}\n• Flow: <code>{flow}</code>\n— — —\nבוצע והועבר לניהול."
            if ok else
            f"⚠️ <b>Approve Failed</b>\n• Ticket: <code>{_md_html(ticket_id)}</code>\n"
            f"• {_md_html(sym)} {_md_html(side)} qty={qty}\n• Flow: <code>{flow}</code>\n— — —\n"
            f"שגיאה: <code>{_md_html(json.dumps(exec_res, ensure_ascii=False))}</code>"
        )
        await _send_telegram_html(msg)
    except Exception:
        pass

    with suppress(Exception):
        ConfirmStore.decide(ticket_id, approved=ok)

    with suppress(Exception):
        (record_approval_approved if ok else record_approval_rejected)()

    await _delete_ticket(ticket_id, source)

    if ok:
        return _html("✅ אושר — הוזמן ונכנס לניהול דינמי.")
    if DEBUG_APPROVE_HTML:
        return _html("⚠️ שגיאה בביצוע — " + _md_html(json.dumps(exec_res, ensure_ascii=False)))
    return _html("⚠️ שגיאה בביצוע — ראה פירוט בטלגרם/לוגים.")

@router.get("/ops/approve-link", summary="Approve legacy link (?id=...)")
async def approve_link(id: str = Query(..., description="ticket_id")):
    return await approve(ticket_id=id)

@router.get("/ops/reject", summary="Reject ticket (delete) – supports ticket_id")
async def reject(ticket_id: str = Query(..., description="ticket_id")):
    ticket, source = await _load_ticket(ticket_id)
    await _delete_ticket(ticket_id, source)
    with suppress(Exception):
        await _send_telegram_html(
            f"❌ <b>Rejected</b>\n• Ticket: <code>{_md_html(ticket_id)}</code>\n— — —\nNo action was taken."
        )
    with suppress(Exception):
        ConfirmStore.decide(ticket_id, approved=False)
    with suppress(Exception):
        record_approval_rejected()
    return _html("❌ נדחה. לא בוצעה פעולה.")

@router.post("/ops/approve/signed", summary="Internal signed approve endpoint (executes trade) – signature required")
async def approve_signed(request: Request):
    if not HMAC_SECRET:
        raise HTTPException(status_code=500, detail="HMAC secret not set")
    raw = await request.body()
    got = request.headers.get("X-Signature", "") or ""
    want = _sign_hex(HMAC_SECRET, raw)
    if not hmac.compare_digest(got, want):
        raise HTTPException(status_code=401, detail="Bad signature")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    t2 = _apply_auto_qty_on_ticket(payload)
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

    # Smart-Manage immediately after approve_signed (if enabled)
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

    # --- Ensure protective stop (Quantities mode) right after open ---
    with suppress(Exception):
        sym = str(payload.get("symbol","")).upper()
        ensure_protective_stop(sym, prefer_mode="quantities")

    with suppress(Exception):
        record_approval_approved()
    return {"ok": True, "ticket_id": payload.get("ticket_id"), "executed": True, "flow": flow, "internal_execute": exec_res}

# -------------------- Smoke: ensure SL on WATCHLIST (alert only on Emergency)
@router.post("/guard/smoke/run", summary="Run ensure_protective_stop() on WATCHLIST. Telegram only on Emergency.")
async def guard_smoke_run(request: Request, symbols: Optional[str] = Body(None)):
    # Bearer required for safety
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
            # prefer quantities mode for protective RO STOP
            res = ensure_protective_stop(s, prefer_mode="quantities")
        except Exception as e:
            res = {"ok": False, "error": str(e)}

        results[s] = res

        # Heuristic: consider it "Emergency" if the guard had to place a brand-new stop or convert to MARKET.
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

@router.get("/ops/digest/expired", summary="Send Telegram digest for expired approval tickets in last N hours")
async def digest_expired(hours: int = Query(6, ge=1, le=48)):
    if not (aioredis and REDIS_URL and BOT_TOKEN and ADMIN_CHAT_ID):
        return {"ok": False, "error": "digest_dependencies_missing"}
    try:
        r = await _redis()
        if not r:
            return {"ok": False, "error": "redis_unavailable"}

        key_good = f"{NS}:expired_log"
        key_bad  = key_good + "}"

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

# Mount routers
app.include_router(router)

# Mount position-ops router (BE/Trail/TP/Close/Manage)
with suppress(Exception):
    from routes.position_ops import router as position_ops_router  # type: ignore
    app.include_router(position_ops_router)

# Mount Locked PnL router (new)
with suppress(Exception):
    from routes.locked_report import router as locked_router  # type: ignore
    app.include_router(locked_router)

# =================================================
# Root / Health / Ready / Debug
# =================================================
@app.get("/", response_class=PlainTextResponse, tags=["meta"])
def root() -> str:
    name = os.getenv("APP_NAME", "algogpt")
    return f"{name} online"

# Health alias for Render
@app.get("/health", response_class=PlainTextResponse, tags=["meta"])
@app.head("/health", response_class=PlainTextResponse)
def health() -> str:
    return "ok"

@app.get("/healthz", response_class=PlainTextResponse, tags=["meta"])
def healthz() -> str:
    return "ok"

@app.get("/readyz", response_class=PlainTextResponse, tags=["meta"])
def readyz() -> str:
    return "ok"

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

# =========================
# Health TP1: startup task + manual endpoint (with built-in fallback if utils missing)
# =========================
try:
    from utils.health_tp1 import health_check_tp1_tags, quick_check_tp1  # type: ignore
    _health_tp1_loaded = True
except Exception as _e:
    logger.warning("health_tp1 module not found (%s) – using built-in fallback", _e)
    _health_tp1_loaded = True

    async def quick_check_tp1(symbols, tp1_tags=None, notify_telegram=False):
        from binance.client import Client  # type: ignore
        api_key = os.getenv("BINANCE_API_KEY","").strip()
        api_sec = os.getenv("BINANCE_API_SECRET","").strip()
        cli = Client(api_key, api_sec)

        tags = tp1_tags or [t.strip() for t in (os.getenv("TP1_TAGS","") or "").split(",") if t.strip()]
        out: Dict[str, Any] = {}
        batch_lines: List[str] = ["🩺 <b>TP1 Health</b>"]

        for sym in symbols:
            symu = str(sym).upper().strip()

            try:
                pos_infos = cli.futures_position_information(symbol=symu) or []
                pos_qty = 0.0
                if pos_infos:
                    q = float(pos_infos[0].get("positionAmt") or 0.0)
                    pos_qty = abs(q)
                if pos_qty < 1e-12:
                    out[symu] = {"skipped_no_position": True}
                    continue
            except Exception:
                pass

            try:
                orders = cli.futures_get_open_orders(symbol=symu)
            except Exception:
                orders = []

            has_tp1 = False
            found = []
            for o in (orders or []):
                coid = ((o.get("clientOrderId") or "") + " " + (o.get("origClientOrderId") or "")).upper()
                if any(t for t in tags if t and t.upper() in coid):
                    has_tp1 = True
                typ = (o.get("type") or "").upper()
                if typ in ("TAKE_PROFIT","TAKE_PROFIT_MARKET","STOP","STOP_MARKET","STOP_LOSS_LIMIT","TAKE_PROFIT_LIMIT"):
                    found.append({
                        "status": o.get("status"),
                        "type": o.get("type"),
                        "side": o.get("side"),
                        "stopPrice": o.get("stopPrice"),
                        "clientOrderId": o.get("clientOrderId"),
                        "reduceOnly": o.get("reduceOnly"),
                        "positionSide": o.get("positionSide","BOTH"),
                        "time": o.get("time"),
                    })

            out[symu] = {"tp1_tags": tags, "tp1_present": has_tp1, "open_conditional": found}
            mark = "✅" if has_tp1 else "⚠️"
            batch_lines.append(f"• {symu}: {mark} {'TP1 found' if has_tp1 else 'TP1 missing'}")

        if notify_telegram and len(batch_lines) > 1:
            await _send_telegram_html("\n".join(batch_lines))

        return out

    async def health_check_tp1_tags(symbols, interval_sec=600):
        while True:
            try:
                await quick_check_tp1(symbols, tp1_tags=TP1_TAGS or None, notify_telegram=True)
            except Exception as e:
                logger.warning("health_tp1_fallback_loop_error: %s", e)
            await asyncio.sleep(max(60, int(interval_sec)))

@app.on_event("startup")
async def _startup_tasks():
    # --- one-shot "bot online" ping to Telegram (non-blocking) ---
    async def _notify_bot_online():
        try:
            await asyncio.sleep(0.5)
            name = os.getenv("APP_TITLE", "AlgoGPT Supervisor")
            env  = os.getenv("ENV", os.getenv("ENVIRONMENT","prod"))
            await _send_telegram_html(f"🟢 <b>Bot online</b> · <code>{name}</code> · env=<code>{env}</code>")
        except Exception:
            pass
    asyncio.create_task(_notify_bot_online())

    if _health_tp1_loaded and HEALTH_TP1_ENABLE:
        watch = [s.strip() for s in (os.getenv("WATCHLIST","") or "").split(",") if s.strip()]
        if watch:
            asyncio.create_task(health_check_tp1_tags(watch, interval_sec=HEALTH_TP1_INTERVAL_SEC))
            logger.info("health_tp1 background started (interval=%ss, symbols=%s)", HEALTH_TP1_INTERVAL_SEC, ",".join(watch))

    async def periodic_manager():
        base = PUBLIC_HOST.rstrip("/")
        token = API_BEARER_TOKEN
        if not base or not token:
            return
        syms = [s.strip() for s in (os.getenv("WATCHLIST","") or "").split(",") if s.strip()]
        if not syms:
            return
        while True:
            try:
                async with httpx.AsyncClient(timeout=15.0) as cli:
                    for s in syms:
                        await cli.post(f"{base}/position-ops/manage-once",
                                       headers={"Authorization": f"Bearer {token}"},
                                       json={"symbol": s})
            except Exception as e:
                logger.warning("periodic_manager_error: %s", e)
            await asyncio.sleep(int(os.getenv("TRADE_MANAGER_INTERVAL_SEC","20")))
    if _bool_env("MANAGER_ENABLE", True):
        asyncio.create_task(periodic_manager())

    # Optional: periodic guarder to ensure SL exists on WATCHLIST positions
    async def periodic_guarder():
        syms = [s.strip().upper() for s in (os.getenv("WATCHLIST","") or "").split(",") if s.strip()]
        if not syms:
            return
        while True:
            try:
                for s in syms:
                    with suppress(Exception):
                        ensure_protective_stop(s, prefer_mode="quantities")
            except Exception:
                pass
            await asyncio.sleep(int(os.getenv("GUARDER_INTERVAL_SEC","45")))
    if _bool_env("GUARDER_ENABLE", True):
        asyncio.create_task(periodic_guarder())

@app.get("/health/tp1", tags=["meta"])
async def health_tp1_now(symbols: Optional[str] = Query(None, description="CSV of symbols; default from WATCHLIST")):
    if not _health_tp1_loaded:
        raise HTTPException(status_code=501, detail="health_tp1 module not loaded")
    sym_list = [s.strip().upper() for s in (symbols.split(",") if symbols else (os.getenv("WATCHLIST","") or "").split(",")) if s.strip()]
    if not sym_list:
        raise HTTPException(status_code=400, detail="no symbols")
    res = await quick_check_tp1(sym_list, tp1_tags=TP1_TAGS or None, notify_telegram=True)
    return {"ok": True, "result": res}

# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("unhandled_error: %s %s", request.method, request.url)
    return JSONResponse(
        status_code=500,
        content={"ok": False, "error": "internal_error", "detail": str(exc)},
    )

# Local run
if __name__ == "__main__":
    import uvicorn
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "10000"))
    reload_ = os.getenv("UVICORN_RELOAD", "0").lower() in ("1", "true", "yes", "on")
    uvicorn.run("main:app", host=host, port=port, reload=reload_)
































































































































































































































































































































































































































































































































































































































