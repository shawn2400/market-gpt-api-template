# routes/ops_approve.py
from __future__ import annotations

import os, json, time, hmac, hashlib, secrets, logging, math, re, inspect, traceback
from contextlib import suppress
from typing import Any, Dict, Optional, List, Callable

from fastapi import APIRouter, HTTPException, Body, Query, Request
from fastapi.responses import HTMLResponse
import httpx

logger = logging.getLogger("algogpt.ops_approve")
router = APIRouter(tags=["ops-approval"])

# --- (optional) metrics wiring ---
try:
    from routes.metrics import (
        record_approval_created,
        record_approval_approved,
        record_approval_rejected,
    )
except Exception:  # no metrics installed
    def record_approval_created(): ...
    def record_approval_approved(): ...
    def record_approval_rejected(): ...

# -------- Optional Redis ----------
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

TP_LADDER_ON_APPROVE       = _bool_env("TP_LADDER_ON_APPROVE", False)
APPROVAL_FAIL_OPEN_ON_VELOCITY = _bool_env("APPROVAL_FAIL_OPEN_ON_VELOCITY", True)
VELOCITY_LOG_LEVEL         = (os.getenv("VELOCITY_LOG_LEVEL","WARNING") or "WARNING").upper()
DEBUG_APPROVE_HTML         = _bool_env("DEBUG_APPROVE_HTML", False)
APPROVE_FALLBACK_TO_MARKET = not _bool_env("PROPOSE_BLOCK_ON_FAIL", False)

SMART_MANAGE_ON_APPROVE    = _bool_env("SMART_MANAGE_ON_APPROVE", False)
SMART_MANAGE_BE_OFFSET_BPS = int(os.getenv("SMART_MANAGE_BE_OFFSET_BPS", os.getenv("TP_BE_OFFSET_BPS","8")))
SMART_MANAGE_PCTS          = [float(x) for x in (os.getenv("SMART_MANAGE_PCTS","") or "").split(",") if x.strip()] or None
SMART_MANAGE_SPLITS        = [float(x) for x in (os.getenv("SMART_MANAGE_SPLITS","") or "").split(",") if x.strip()] or None
SMART_MANAGE_TRAIL_ATR_MULT= float(os.getenv("SMART_MANAGE_TRAIL_ATR_MULT","0") or 0) or None

# -------- ConfirmStore fallback ----------
try:
    from utils.trade_executor import ConfirmStore  # type: ignore
except Exception:
    try:
        from app.trade_executor import ConfirmStore  # type: ignore
    except Exception:
        class ConfirmStore:  # type: ignore
            _P: Dict[str, Dict[str, Any]] = {}
            @classmethod
            def pending(cls) -> List[Dict[str, Any]]:
                return list(cls._P.values())
            @classmethod
            def create(cls, payload: Dict[str, Any]) -> str:
                tid = payload.get("ticket_id") or f"TKT-{int(time.time()*1000)}"
                payload["ticket_id"] = tid
                payload.setdefault("created_ts", int(time.time()))
                payload.setdefault("ttl_sec", TICKET_TTL_SEC)
                cls._P[tid] = payload
                return tid
            @classmethod
            def get(cls, ticket_id: str) -> Optional[Dict[str, Any]]:
                return cls._P.get(ticket_id)
            @classmethod
            def decide(cls, ticket_id: str, approved: bool) -> Dict[str, Any]:
                it = cls._P.pop(ticket_id, None)
                if not it:
                    return {"ok": False, "error": "not_found"}
                it["approved"] = approved
                it["decided_ts"] = int(time.time())
                return {"ok": True, "approved": approved, "ticket_id": ticket_id}

# -------- Position sizing (AUTO_QTY) ----------
try:
    from app.utils.position_sizing import ensure_final_qty  # type: ignore
except Exception:
    from utils.position_sizing import ensure_final_qty  # type: ignore

# -------- ClientOrderId builder (36 chars, sanitized) ----------
try:
    from utils.order_ids import build_client_order_id  # type: ignore
except Exception:
    # פולבק קטן כדי לא לשבור — אותו פורמט, מגבלה 36, hash קצר
    import hashlib as _hl
    def _coid_fit_local(s: str, limit: int = 36) -> str:
        s = re.sub(r'[^A-Za-z0-9._:/-]', '_', str(s))
        if len(s) <= limit:
            return s
        h = _hl.md5(s.encode("utf-8")).hexdigest()[:6]
        return f"{s[:limit-(len(h)+1)]}_{h}"
    def build_client_order_id(symbol: str, side: str, role: str = "ENTRY", extra: Optional[str] = None) -> str:
        prefix = (os.getenv("ORDER_ID_PREFIX") or "ALG").strip() or "ALG"
        sym = str(symbol).upper().strip()
        sd  = str(side).upper().strip()
        rl  = str(role).upper().strip().replace("@", "_")
        ts  = str(int(time.time() * 1000))
        parts = [prefix, sym, sd, rl, ts]
        if extra:
            parts.append(str(extra))
        return _coid_fit_local("-".join(parts), 36)

# -------- Prices ----------
def _get_last_price(symbol: str) -> Optional[float]:
    """
    מנסה להביא מחיר מסינקים קיימים; נופל חזרה ל-binance client אם צריך.
    שים לב: קריאות ל-Binance הן סינכרוניות — עטוף ב-suppress כדי לא לתקוע את הלולאה.
    """
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

# -------- Helpers ----------
def _md_html(s: str) -> str:
    return str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

def _html(msg: str) -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html><meta charset='utf-8'>"
        "<body style='font-family:sans-serif;max-width:560px;margin:3rem auto;line-height:1.5'>"
        f"<h2 style='margin:0 0 .5rem 0'>{msg}</h2>"
        "<p style='color:#666'>אפשר לחזור חזרה לטלגרם.</p>"
        "</body>"
    )

def _sign_hex(secret_hex_or_text: str, payload: bytes) -> str:
    key = bytes.fromhex(secret_hex_or_text) if len(secret_hex_or_text)==64 else secret_hex_or_text.encode("utf-8")
    return hmac.new(key, payload, hashlib.sha256).hexdigest()

# keep a single redis connection factory
async def _redis():
    if not (aioredis and REDIS_URL):
        return None
    return aioredis.from_url(REDIS_URL, decode_responses=True)

# -------- Mode parsing ----------
_MODE_RX = re.compile(r"\[mode:\s*(MARKET|HYBRID|AUTO)\s*\]", flags=re.I)
def _parse_mode(note: Optional[str]) -> Optional[str]:
    if not note:
        return None
    m = _MODE_RX.search(str(note))
    return m.group(1).upper() if m else None

# -------- Telegram --------
async def _send_telegram_html(text: str,
                              approve_url: Optional[str] = None,
                              reject_url: Optional[str] = None,
                              preview_url: Optional[str] = None) -> Dict[str, Any]:
    if not BOT_TOKEN or not ADMIN_CHAT_ID:
        return {"ok": False, "skipped": True}
    payload: Dict[str, Any] = {
        "chat_id": int(ADMIN_CHAT_ID) if str(ADMIN_CHAT_ID).isdigit() else ADMIN_CHAT_ID,
        "text": text, "parse_mode": "HTML", "disable_web_page_preview": True,
    }
    if approve_url or reject_url or preview_url:
        row: List[Dict[str, Any]] = []
        if preview_url: row.append({"text":"👁 Preview","url":preview_url})
        if approve_url: row.append({"text":"✅ Approve","url":approve_url})
        if reject_url:  row.append({"text":"❌ Reject","url":reject_url})
        payload["reply_markup"] = {"inline_keyboard":[row]}
    try:
        # timeout מגן — מונע "היתקעות" אם טלגרם לא עונה
        async with httpx.AsyncClient(timeout=httpx.Timeout(12.0, connect=5.0)) as cli:
            r = await cli.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json=payload)
        try:
            data = r.json()
        except Exception:
            data = {"ok": False, "status": r.status_code, "text": r.text}
        return data
    except Exception as e:
        return {"ok": False, "error": str(e)}

# -------- utils: dynamic kwargs filter --------
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

# -------- Position mode alignment ----------
def _align_position_mode(client) -> None:
    mode_override = (os.getenv("POSITION_MODE_OVERRIDE","") or "").strip().lower()
    with suppress(Exception):
        if mode_override in ("hedge","dual","dual_side","dual_side_position","dualposition"):
            client.futures_change_position_mode(dualSidePosition="true")
        elif mode_override in ("oneway","one_way","single","single_side","oneside"):
            client.futures_change_position_mode(dualSidePosition="false")

# -------- Execution backends ----------
async def _execute_trade(ticket: Dict[str, Any]) -> Dict[str, Any]:
    # דרך מתאם פנימי אם זמין
    try:
        from utils.trade_executor import place_futures_market  # type: ignore
        return await place_futures_market(ticket)
    except Exception:
        pass

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
            # retry 1: בלי positionSide
            try:
                retry_kwargs = dict(base_kwargs)
                order = client.futures_create_order(**retry_kwargs)
                return {"ok": True, "exchange": "binance_futures", "order": order, "retry": "no_positionSide"}
            except Exception as e2:
                # retry 2: positionSide נגזר מה-side
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
    try:
        try:
            from utils.trade_executor import execute_trade_live  # type: ignore
        except Exception:
            from app.trade_executor import execute_trade_live  # type: ignore
    except Exception as e:
        logger.error("execute_trade_live missing: %s", e)
        return {"ok": False, "error": "execute_trade_live_missing", "detail": str(e)}

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
        tp_splits=ticket.get("tp_splits"),
        sl_splits=None,
        confirm_first=False,
        telegram_chat_id=int(os.getenv("TELEGRAM_CHAT_ID") or 0),
        position_side=pos_side,
        reduce_only=bool(ticket.get("reduce_only", False)),
    )

    clean = _filter_kwargs_for_callable(execute_trade_live, base_kwargs)

    try:
        res = await execute_trade_live(**clean)
        return res
    except Exception as e:
        logger.error("armed_execute failed: %s", e)
        return {"ok": False, "error": "armed_execute_failed", "detail": f"{e}", "trace": traceback.format_exc()}

# -------- Smart ETA (optional) --------
def _calc_velocity_per_min(symbol: str, interval: str, window_min: int) -> Optional[float]:
    try:
        from utils.get_klines import get_klines_sync  # type: ignore
        m = {"1m":1, "3m":3, "5m":5, "15m":15, "30m":30, "1h":60}.get(interval, 15)
        n = max(10, math.ceil(window_min / m) + 5)
        kl = get_klines_sync(symbol, interval=interval, limit=n) or []

        try:
            if 'DataFrame' in str(type(kl)):
                if hasattr(kl, 'columns') and ('close' in getattr(kl, 'columns', [])):
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
        (logger.info if VELOCITY_LOG_LEVEL=="INFO" else logger.warning)("velocity_calc_failed: %s", e)
        return None

def _smart_etas(symbol: str, side: str, price_now: Optional[float], tp1=None, tp2=None, tp3=None,
                interval: str = DEFAULT_INTERVAL, window_min: int = ETA_VELOCITY_WINDOW) -> Dict[str, Optional[int]]:
    vpm = _calc_velocity_per_min(symbol, interval, window_min)
    if not (price_now and isinstance(vpm, (int, float)) and vpm > 0):
        return {"eta_tp1_min": None, "eta_tp2_min": None, "eta_tp3_min": None}
    def _eta(tgt):
        if tgt is None:
            return None
        dist = abs(float(tgt) - float(price_now))
        return int(math.ceil(dist / vpm)) if vpm > 0 else None
    return {"eta_tp1_min": _eta(tp1), "eta_tp2_min": _eta(tp2), "eta_tp3_min": _eta(tp3)}

# -------- Storage abstraction --------
import json as _json

async def _load_ticket(tid: str):
    if aioredis and REDIS_URL:
        try:
            r = await _redis()
            if r:
                raw = await r.get(f"{NS}:ticket:{tid}")
                if raw:
                    rec = _json.loads(raw)
                    from time import time as _now
                    if (_now() - float(rec.get("ts", 0))) <= TICKET_TTL_SEC:
                        return rec.get("req") or rec, "redis"
        except Exception as e:
            logger.warning("redis_load_failed: %s", e)
    try:
        for it in (ConfirmStore.pending() or []):
            if str(it.get("ticket_id")) == str(tid):
                return it.get("req") or it, "confirmstore"
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

# -------- Smart-manage trigger (internal call) --------
async def _smart_manage_now(symbol: str,
                            offset_bps: Optional[int] = None,
                            pcts: Optional[List[float]] = None,
                            splits: Optional[List[float]] = None,
                            atr_mult: Optional[float] = None) -> Dict[str, Any]:
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
        body["atr_mult"] = atr_mult

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0)) as cli:
            r = await cli.post(
                f"{base}/position-ops/manage-once",
                headers={"Authorization": f"Bearer {token}"},
                json=body
            )
        return {"ok": r.status_code < 300, "status": r.status_code, "text": r.text}
    except Exception as e:
        logger.warning("smart_manage_now_error: %s", e)
        return {"ok": False, "error": str(e)}

# -------------------- API --------------------
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

    # מקל על ולידציה – qty/lev יכולים להיות 0 כדי לאפשר AUTO_QTY בשלב האישור
    if not (symbol and side):
        raise HTTPException(status_code=422, detail="Missing fields (symbol/side). qty/leverage may be auto at approve.")

    tid = payload.get("ticket_id") or f"T_{secrets.token_hex(4)}"

    # ETA חכם (אם מאופשר)
    if ETA_SMART_ENABLE and (payload.get("tp1") or payload.get("tp2") or payload.get("tp3")):
        price_now = None
        with suppress(Exception):
            price_now = _get_last_price(symbol)
        etas = _smart_etas(symbol, side, price_now, payload.get("tp1"), payload.get("tp2"), payload.get("tp3"))
        for k, v in etas.items():
            payload.setdefault(k, v)

    try:
        from routes.ops_flags import apply_note_flags  # type: ignore
    except Exception:
        def apply_note_flags(note, ticket): return ticket

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

    # RR מינימלי (אופציונלי)
    with suppress(Exception):
        rr_min_flag = float(req_body.get("rr_min") or 0.0)
        rr_env_lo   = float(os.getenv("APPROVAL_RR_MIN", "0") or "0")
        rr_min_eff  = max(rr_min_flag, rr_env_lo)
        if rr_min_eff > 0 and req_body.get("sl"):
            current = float(_get_last_price(symbol) or 0)
            tp1 = float(req_body.get("tp1") or 0)
            sl  = float(req_body.get("sl") or 0)
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
    # נרמול position_side: לא מעבירים "BOTH" הלאה
    ps = str(new_ticket.get("position_side") or new_ticket.get("positionSide") or "").upper()
    if ps == "BOTH":
        new_ticket.pop("positionSide", None)
        new_ticket["position_side"] = ""
    return new_ticket

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

    exec_res = await (
        _execute_trade(ticket) if flow == "MARKET"
        else _execute_trade_armed(ticket) if flow == "HYBRID"
        else (_execute_trade_armed(ticket) if any(ticket.get(k) for k in ("tp1","tp2","tp3","sl")) else _execute_trade(ticket))
    )
    ok = bool(exec_res.get("ok"))

    if (not ok) and flow in ("HYBRID","AUTO") and APPROVE_FALLBACK_TO_MARKET:
        logger.warning("approve_retry_market_after_hybrid_fail: %s", exec_res)
        retry_res = await _execute_trade(ticket)
        ok = bool(retry_res.get("ok"))
        exec_res = {"primary": "HYBRID", "fallback_market": retry_res, "primary_error": exec_res}

    # ניהול אוטומטי מייד אחרי אישור (אם מופעל)
    if ok and SMART_MANAGE_ON_APPROVE:
        with suppress(Exception):
            sym = str(ticket.get("symbol","")).upper()
            sm_res = await _smart_manage_now(
                sym,
                offset_bps=SMART_MANAGE_BE_OFFSET_BPS,
                pcts=SMART_MANAGE_PCTS,
                splits=SMART_MANAGE_SPLITS,
                atr_mult=SMART_MANAGE_TRAIL_ATR_MULT
            )
            logger.info("smart_manage_after_approve: %s -> %s", sym, sm_res)

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
    exec_res = await (
        _execute_trade(payload) if flow == "MARKET"
        else _execute_trade_armed(payload) if flow == "HYBRID"
        else (_execute_trade_armed(payload) if any(payload.get(k) for k in ("tp1","tp2","tp3","sl")) else _execute_trade(payload))
    )
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

    # ניהול מיידי גם ב-signed אם מופעל
    if SMART_MANAGE_ON_APPROVE:
        with suppress(Exception):
            sym = str(payload.get("symbol","")).upper()
            sm_res = await _smart_manage_now(
                sym,
                offset_bps=SMART_MANAGE_BE_OFFSET_BPS,
                pcts=SMART_MANAGE_PCTS,
                splits=SMART_MANAGE_SPLITS,
                atr_mult=SMART_MANAGE_TRAIL_ATR_MULT
            )
            logger.info("smart_manage_after_approve_signed: %s -> %s", sym, sm_res)

    with suppress(Exception):
        record_approval_approved()
    return {"ok": True, "ticket_id": payload.get("ticket_id"), "executed": True, "flow": flow, "internal_execute": exec_res}

@router.get("/ops/digest/expired", summary="Send Telegram digest for expired approval tickets in last N hours")
async def digest_expired(hours: int = Query(6, ge=1, le=48)):
    if not (aioredis and REDIS_URL and BOT_TOKEN and ADMIN_CHAT_ID):
        return {"ok": False, "error": "digest_dependencies_missing"}
    try:
        r = await _redis()
        if not r:
            return {"ok": False, "error": "redis_unavailable"}

        # חלק מלקוחות Redis “מחליקים” שמות מפתחות — נוסיף key חלופי למקרה חריג
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

        from collections import Counter
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







