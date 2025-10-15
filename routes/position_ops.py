# routes/position_ops.py
from __future__ import annotations

import os
import time
import math
import hashlib
import logging
import asyncio
from typing import Any, Dict, List, Optional, Tuple
from contextlib import suppress

from fastapi import APIRouter, Body, Header, HTTPException, Query, Request

# Anti-Replay
with suppress(Exception):
    from utils.anti_replay import verify_request  # type: ignore

# Telegram notifier (כפתורי אינליין אחרי פעולות)
with suppress(Exception):
    from utils.telegram_notifier import TelegramNotifier  # type: ignore

logger = logging.getLogger("algogpt.position_ops")
router = APIRouter(prefix="/position-ops", tags=["position-ops"])

# =========================
# Utils: uniform OK/ERR payloads
# =========================
def _ok(**data) -> Dict[str, Any]:
    d = {"ok": True}
    d.update(data)
    return d

def _err(reason: str, **data) -> Dict[str, Any]:
    d = {"ok": False, "reason": reason}
    d.update(data)
    return d

# =========================
# Telegram notify helpers (fire-and-forget גם מתוך threadpool)
# =========================
def _notify_ops(symbol: str, action_name: str) -> None:
    """
    שולח הודעת טלגרם קצרה עם מקלדת אינליין
    לא חוסם את שרשור הראוט. בטוח גם אם אין event loop קיים בת׳רד.
    """
    if "TelegramNotifier" not in globals():
        return
    loop: Optional[asyncio.AbstractEventLoop] = None
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(TelegramNotifier.send_ops_action_result(symbol, action_name))  # type: ignore[attr-defined]
        return
    except Exception:
        pass
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(TelegramNotifier.send_ops_action_result(symbol, action_name))  # type: ignore[attr-defined]
    except Exception:
        pass
    finally:
        if loop:
            with suppress(Exception):
                loop.close()

def _maybe_notify(symbol: Optional[str], action_name: str, res: Dict[str, Any]) -> None:
    if not symbol or not isinstance(res, dict) or not res.get("ok", False) or res.get("skipped"):
        return
    _notify_ops(symbol, action_name)

# =========================
# Guard (אופציונלי, שקט אם חסר)
# =========================
GUARD_ENSURE_AFTER_OPS = (os.getenv("GUARD_ENSURE_AFTER_OPS", "1").lower() in ("1", "true", "yes", "on"))
with suppress(Exception):
    from utils.guard_stop import ensure_protective_stop  # type: ignore

def _ensure_guard(symbol: str, *, prefer_mode: str = "native") -> None:
    if not GUARD_ENSURE_AFTER_OPS:
        return
    with suppress(Exception):
        ensure_protective_stop(symbol, prefer_mode=prefer_mode)  # type: ignore

# =========================
# Helpers: auth (Bearer) — רכה
# =========================
API_BEARER_TOKEN = (os.getenv("API_BEARER_TOKEN") or os.getenv("API_TOKEN") or "").strip()

def _auth_ok(auth_header: Optional[str]) -> bool:
    if not API_BEARER_TOKEN:
        return True
    if not auth_header or not auth_header.startswith("Bearer "):
        return False
    return (auth_header.split(" ", 1)[1].strip() == API_BEARER_TOKEN)

def _anti_replay_required() -> bool:
    return os.getenv("ANTI_REPLAY_ENABLE", "0").lower() in ("1", "true", "yes", "on") and \
           os.getenv("ANTI_REPLAY_REQUIRE_SIGNATURE", "0").lower() in ("1", "true", "yes", "on")

# =========================
# Order IDs
# =========================
def _coid_fit(s: str, limit: int = 32) -> str:
    if len(s) <= limit:
        return s
    h = hashlib.md5(s.encode("utf-8")).hexdigest()[:7]
    return s[: limit - (1 + len(h))] + "_" + h

def _build_client_order_id(symbol: str, side: str, role: str = "ENTRY") -> str:
    prefix = (os.getenv("ORDER_ID_PREFIX") or "ALG").strip() or "ALG"
    sym = str(symbol).upper()
    side = str(side).upper()
    role = str(role).upper()
    ts = int(time.time())
    return _coid_fit(f"{prefix}_{sym}_{side}_{ROLE_MAP.get(role, role)}_{ts}", 32)

ROLE_MAP = {
    "ENTRY": "ENTRY",
    "BE": "BE",
    "TRAIL": "TRAIL",
    "SL": "SL",
    "TP": "TP",
    "TP1": "TP1",
    "TP2": "TP2",
    "TP3": "TP3",
    "CLOSE": "CLOSE",
}

with suppress(Exception):
    from utils.order_ids import build_client_order_id  # type: ignore
    _build_client_order_id = build_client_order_id  # override אם קיים

# =========================
# Quantize
# =========================
def _fallback_filters() -> Dict[str, Any]:
    return {
        "price_tick": float(os.getenv("DEFAULT_PRICE_TICK", "0.01")),
        "qty_step": float(os.getenv("DEFAULT_QTY_STEP", "0.001")),
    }

def _round_step(v: float, step: float) -> float:
    if step <= 0:
        return v
    return math.floor(v / step + 1e-12) * step

def _quantize_price(symbol: str, price: float, flt: Dict[str, Any]) -> float:
    step = float(flt.get("price_tick", 0.0) or 0.0)
    return round(_round_step(price, step), 8) if step > 0 else round(price, 8)

def _quantize_qty(symbol: str, qty: float, flt: Dict[str, Any]) -> float:
    step = float(flt.get("qty_step", 0.0) or 0.0)
    return round(_round_step(qty, step), 8) if step > 0 else round(qty, 8)

with suppress(Exception):
    from utils.quantize import quantize_price as _qp, quantize_qty as _qq  # type: ignore
    def _quantize_price(symbol: str, price: float, flt: Dict[str, Any]) -> float:  # type: ignore
        return _qp(symbol, price, flt)
    def _quantize_qty(symbol: str, qty: float, flt: Dict[str, Any]) -> float:  # type: ignore
        return _qq(symbol, qty, flt)

# =========================
# Binance client (soft)
# =========================
def _get_client_soft() -> Tuple[Optional[Any], Optional[str]]:
    try:
        from binance.client import Client  # type: ignore
    except Exception as e:
        return None, f"binance_import_failed: {e}"
    api_key = os.getenv("BINANCE_API_KEY", "").strip()
    api_sec = os.getenv("BINANCE_API_SECRET", "").strip()
    if not api_key or not api_sec:
        return None, "binance_keys_missing"
    try:
        return Client(api_key, api_sec), None
    except Exception as e:
        return None, f"binance_client_init_failed: {e}"

def _align_position_mode(client) -> None:
    mode_override = (os.getenv("POSITION_MODE_OVERRIDE", "") or "").strip().lower()
    with suppress(Exception):
        if mode_override in ("hedge", "dual", "dual_side", "dual_side_position", "dualposition"):
            client.futures_change_position_mode(dualSidePosition="true")
        elif mode_override in ("oneway", "one_way", "single", "single_side", "oneside"):
            client.futures_change_position_mode(dualSidePosition="false")

# =========================
# EXCHANGE INFO CACHE (anti-burst)
# =========================
_EXINFO_CACHE: Dict[str, Any] = {"ts": 0.0, "data": None}
_EXINFO_TTL = float(os.getenv("EXCHANGE_INFO_TTL_SEC", "900") or 900)
_EXINFO_WARNED_AT = 0.0

def _fetch_exchange_info_cached(client) -> Dict[str, Any]:
    global _EXINFO_CACHE, _EXINFO_WARNED_AT
    now = time.time()
    if _EXINFO_CACHE["data"] and (now - _EXINFO_CACHE["ts"] < _EXINFO_TTL):
        return _EXINFO_CACHE["data"]
    try:
        data = client.futures_exchange_info() or {}
        _EXINFO_CACHE = {"ts": now, "data": data}
        return data
    except Exception as e:
        if _EXINFO_CACHE["data"]:
            if now - _EXINFO_WARNED_AT > _EXINFO_TTL:
                logger.warning("exchange_info_rate_limited_using_cache: %s", e)
                _EXINFO_WARNED_AT = now
            return _EXINFO_CACHE["data"]
        if now - _EXINFO_WARNED_AT > _EXINFO_TTL:
            logger.warning("exchange_info_unavailable_no_cache_yet: %s (using fallback filters)", e)
            _EXINFO_WARNED_AT = now
        return {}

def _get_filters(client, symbol: str) -> Dict[str, Any]:
    try:
        ex = _fetch_exchange_info_cached(client) or {}
        for s in ex.get("symbols", []) or []:
            if str(s.get("symbol", "")).upper() == symbol.upper():
                price_tick = None
                qty_step = None
                for f in s.get("filters", []) or []:
                    ft = f.get("filterType")
                    if ft == "PRICE_FILTER":
                        with suppress(Exception):
                            price_tick = float(f.get("tickSize") or 0.0)
                    if ft == "LOT_SIZE":
                        with suppress(Exception):
                            qty_step = float(f.get("stepSize") or 0.0)
                out = {"price_tick": price_tick or 0.0, "qty_step": qty_step or 0.0}
                return out if (out["price_tick"] or out["qty_step"]) else _fallback_filters()
    except Exception:
        pass
    return _fallback_filters()

with suppress(Exception):
    from utils.quantize import get_filters as _unused_gf  # type: ignore

# =========================
# Position & price helpers (עשויים לזרוק — נתפוס בראוטים)
# =========================
def _fetch_position_side_qty_entry(client, symbol: str) -> Tuple[str, float, float]:
    infos = client.futures_position_information(symbol=symbol) or []
    if not infos:
        raise HTTPException(status_code=404, detail="No position information")
    pos = infos[0]
    qty = float(pos.get("positionAmt") or 0.0)
    ep = float(pos.get("entryPrice") or 0.0)
    if abs(qty) < 1e-12:
        raise HTTPException(status_code=409, detail="No open position")
    side = "BUY" if qty > 0 else "SELL"
    return side, abs(qty), ep

def _last_price(client, symbol: str) -> float:
    p = client.futures_symbol_ticker(symbol=symbol.upper())
    return float(p["price"])

def _cancel_open_conditional(client, symbol: str,
                             kinds=("STOP", "TAKE_PROFIT", "TRAILING_STOP_MARKET"),
                             *, strict: bool = False) -> int:
    """
    strict=False (ברירת מחדל) — ביטול רחב: טיפוסים ב-kinds או כל טיפוס שמכיל STOP/TAKE_PROFIT
    strict=True  — ביטול טיפוסים בדיוק כפי שמופיעים ב-kinds בלבד (למשל ביטול TRAILING בלבד)
    """
    n = 0
    for o in client.futures_get_open_orders(symbol=symbol.upper()) or []:
        typ = (o.get("type") or "").upper()
        should = (typ in kinds) if strict else (typ in kinds or "STOP" in typ or "TAKE_PROFIT" in typ)
        if should:
            with suppress(Exception):
                client.futures_cancel_order(symbol=symbol.upper(), orderId=o["orderId"])
                n += 1
    return n

# =========================
# Gates (TP1/min profit)
# =========================
def _tp1_filled(client, symbol: str) -> bool:
    tags = [t.strip().upper() for t in (os.getenv("TP1_TAGS", "TP1,tp1,tp_1,TAKE_PROFIT_1").split(","))]
    try:
        orders = client.futures_get_all_orders(symbol=symbol.upper(), limit=120) or []
        for o in orders:
            st = (o.get("status") or "").upper()
            cid = ((o.get("clientOrderId") or "") + " " + (o.get("origClientOrderId") or "")).upper()
            typ = (o.get("type") or "").upper()
            # מזוהה כ-TP1 אם הוזמן TAKE_PROFIT כלשהו ומולא, או אם clientOrderId מכיל אחד מהתגיות
            if st == "FILLED" and (
                "TP1" in cid or any(t in cid for t in tags) or "TAKE_PROFIT" in typ
            ):
                return True
    except Exception:
        pass
    return False

# =========================
# Public endpoints
# =========================
@router.get("/status")
def status(symbol: str = Query(..., description="Symbol, e.g. BTCUSDT"),
           authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    if not _auth_ok(authorization):
        raise HTTPException(status_code=401, detail="Unauthorized")
    client, err = _get_client_soft()
    if not client:
        return _ok(skipped=True, reason=err or "no_client")
    _align_position_mode(client)
    try:
        side, qty, entry = _fetch_position_side_qty_entry(client, symbol)
        last = 0.0
        with suppress(Exception):
            last = _last_price(client, symbol)
        be_bps = int(os.getenv("TP_BE_OFFSET_BPS", "5") or 5)
        be_price = float(entry) * (1.0 - be_bps / 10_000.0) if side == "BUY" else float(entry) * (1.0 + be_bps / 10_000.0)
        flt = _get_filters(client, symbol)
        be_price = _quantize_price(symbol, be_price, flt)
        tp1_hit = _tp1_filled(client, symbol)
        return _ok(symbol=symbol.upper(), has_position=True, side=side, qty=qty, entry=entry,
                   last=last, be_candidate=be_price, tp1_filled=tp1_hit)
    except HTTPException as e:
        if e.status_code == 409:
            return _ok(symbol=symbol.upper(), has_position=False, reason="no_open_position")
        raise
    except Exception as e:
        return _err("status_failed", detail=str(e))

@router.post("/be")
def place_be(
    request: Request,
    payload: Dict[str, Any] = Body(..., example={"symbol": "BTCUSDT", "offset_bps": 12}),
    authorization: Optional[str] = Header(None),
    x_timestamp: Optional[str] = Header(None, alias="X-Timestamp"),
    x_nonce: Optional[str] = Header(None, alias="X-Nonce"),
    x_signature: Optional[str] = Header(None, alias="X-Signature"),
) -> Dict[str, Any]:
    if not _auth_ok(authorization):
        raise HTTPException(status_code=401, detail="Unauthorized")

    if _anti_replay_required():
        body = payload
        ok, reason = verify_request(x_timestamp, x_nonce, x_signature, "/position-ops/be", body, require_signature=True)  # type: ignore
        if not ok:
            raise HTTPException(status_code=401, detail=f"bad_signature: {reason}")

    symbol = (payload.get("symbol") or "").upper().strip()
    offset_bps = int(payload.get("offset_bps") or os.getenv("TP_BE_OFFSET_BPS", "5") or 5)
    if not symbol:
        raise HTTPException(status_code=422, detail="missing symbol")

    client, err = _get_client_soft()
    if not client:
        return _ok(skipped=True, reason=err or "no_client")
    _align_position_mode(client)

    try:
        side, qty, entry = _fetch_position_side_qty_entry(client, symbol)
    except HTTPException as e:
        if e.status_code == 409:
            return _ok(skipped=True, reason="no_open_position")
        raise

    # price & filters
    flt = _get_filters(client, symbol)
    be_price = float(entry) * (1.0 - offset_bps / 10_000.0) if side == "BUY" else float(entry) * (1.0 + offset_bps / 10_000.0)
    be_price = _quantize_price(symbol, be_price, flt)

    # נבטל פקודות מגנות קודמות
    with suppress(Exception):
        _cancel_open_conditional(client, symbol, kinds=("STOP", "STOP_MARKET", "TRAILING_STOP_MARKET"), strict=False)

    # נצמיד קצת מול המחיר האחרון כדי להימנע מטריגר מיידי
    try:
        last = _last_price(client, symbol)
        tick = float(flt.get("price_tick", 0.0) or 0.0)
        if tick > 0:
            if side == "BUY" and be_price >= last:
                be_price = _quantize_price(symbol, last - tick, flt)
            elif side == "SELL" and be_price <= last:
                be_price = _quantize_price(symbol, last + tick, flt)
    except Exception:
        pass

    # ניצור STOP_MARKET closePosition
    try:
        client.futures_create_order(
            symbol=symbol,
            side="SELL" if side == "BUY" else "BUY",
            type="STOP_MARKET",
            stopPrice=be_price,
            closePosition=True,
            workingType=os.getenv("BINANCE_WORKING_TYPE", "MARK_PRICE"),
            newClientOrderId=_build_client_order_id(symbol, "SELL" if side == "BUY" else "BUY", role="SL@BE"),
        )
    except Exception as e:
        return _err("place_be_failed", detail=str(e))

    _ensure_guard(symbol, prefer_mode="native")
    res = _ok(symbol=symbol, side=side, qty=qty, be_stop_price=be_price, offset_bps=offset_bps)
    _maybe_notify(symbol, "be", res)
    return res

@router.post("/trail")
def place_trailing(
    request: Request,
    payload: Dict[str, Any] = Body(..., example={"symbol": "BTCUSDT", "atr_mult": 1.6}),
    authorization: Optional[str] = Header(None),
    x_timestamp: Optional[str] = Header(None, alias="X-Timestamp"),
    x_nonce: Optional[str] = Header(None, alias="X-Nonce"),
    x_signature: Optional[str] = Header(None, alias="X-Signature"),
) -> Dict[str, Any]:
    if not _auth_ok(authorization):
        raise HTTPException(status_code=401, detail="Unauthorized")

    if _anti_replay_required():
        body = payload
        ok, reason = verify_request(x_timestamp, x_nonce, x_signature, "/position-ops/trail", body, require_signature=True)  # type: ignore
        if not ok:
            raise HTTPException(status_code=401, detail=f"bad_signature: {reason}")

    symbol = (payload.get("symbol") or "").upper().strip()
    atr_mult = payload.get("atr_mult")
    callback_rate = payload.get("callback_rate")
    if not symbol:
        raise HTTPException(status_code=422, detail="missing symbol")

    client, err = _get_client_soft()
    if not client:
        return _ok(skipped=True, reason=err or "no_client")
    _align_position_mode(client)

    try:
        side, qty, entry = _fetch_position_side_qty_entry(client, symbol)
    except HTTPException as e:
        if e.status_code == 409:
            return _ok(skipped=True, reason="no_open_position")
        raise

    # בטל קודם trailing קיים
    with suppress(Exception):
        _cancel_open_conditional(client, symbol, kinds=("TRAILING_STOP_MARKET",), strict=True)

    # חשב callbackRate
    def _calc_callback_rate() -> float:
        if callback_rate:
            try:
                r = float(callback_rate)
                return max(0.1, min(5.0, r))
            except Exception:
                pass
        # ATR-based
        if atr_mult is None:
            with suppress(Exception):
                atr_mult_env = float(os.getenv("TRAIL_ATR_MULT", "1.6"))
                return max(0.1, min(5.0, atr_mult_env))
            return 1.6
        try:
            am = float(atr_mult)
        except Exception:
            am = 1.6
        try:
            kl = client.futures_klines(symbol=symbol, interval="1m", limit=50)
            highs = [float(k[2]) for k in kl]
            lows = [float(k[3]) for k in kl]
            closes = [float(k[4]) for k in kl]
            trs: List[float] = []
            for i in range(1, len(kl)):
                h, l, pc = highs[i], lows[i], closes[i - 1]
                tr = max(h - l, abs(h - pc), abs(l - pc))
                trs.append(tr)
            atr = (sum(trs[-14:]) / float(min(14, len(trs)))) if trs else 0.0
            px = _last_price(client, symbol)
            rate = (atr * am / px) * 100.0 if px > 0 else 0.5
            return max(0.1, min(5.0, rate))
        except Exception:
            return 1.6

    cb = round(float(_calc_callback_rate()), 1)

    try:
        client.futures_create_order(
            symbol=symbol,
            side="SELL" if side == "BUY" else "BUY",
            type="TRAILING_STOP_MARKET",
            callbackRate=cb,
            reduceOnly=True,
            workingType=os.getenv("BINANCE_WORKING_TYPE", "MARK_PRICE"),
            newClientOrderId=_build_client_order_id(symbol, "SELL" if side == "BUY" else "BUY", role="TRAIL"),
        )
    except Exception as e:
        return _err("place_trailing_failed", detail=str(e))

    _ensure_guard(symbol, prefer_mode="native")
    res = _ok(symbol=symbol, side=side, qty=qty, callback_rate=cb)
    _maybe_notify(symbol, "trail", res)
    return res











