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

from fastapi import APIRouter, Body, Header
from fastapi import HTTPException  # רק לצורך סוג החריגה, לא נזרוק בראוטים

# Anti-Replay
from utils.anti_replay import verify_request

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

def _cancel_open_conditional(client, symbol: str, kinds=("STOP", "TAKE_PROFIT", "TRAILING_STOP_MARKET")) -> int:
    n = 0
    for o in client.futures_get_open_orders(symbol=symbol.upper()) or []:
        typ = (o.get("type") or "").upper()
        if typ in kinds or "STOP" in typ or "TAKE_PROFIT" in typ:
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
            if st == "FILLED" and ("TAKE_PROFIT" in typ):
                if "TP1" in cid or any(t for t in tags if t and t in cid):
                    return True
    except Exception:
        pass
    return False

def _profit_ok(entry: float, last: float, side: str, min_pct: float) -> bool:
    if min_pct <= 0 or entry <= 0 or last <= 0:
        return True
    move = (last - entry) / entry * 100.0 if side == "BUY" else (entry - last) / entry * 100.0
    return move >= min_pct

def _gate_be_trail(client, symbol: str, side: str, entry: float) -> Tuple[bool, str]:
    want_tp1 = (os.getenv("SMART_MANAGE_AFTER_TP1", "0").lower() in ("1", "true", "yes", "on"))
    min_profit = float(os.getenv("TRAIL_MIN_PROFIT_PCT", "0") or 0)
    last = 0.0
    with suppress(Exception):
        last = _last_price(client, symbol)
    if want_tp1 and not _tp1_filled(client, symbol):
        return (False, "blocked_by_tp1_not_filled")
    if min_profit > 0 and not _profit_ok(entry, last, side, min_profit):
        return (False, "blocked_by_min_profit")
    return (True, "ok")

# =========================
# Internal impls (no auth)
# =========================
def _be_impl(client, *, symbol: str, offset_bps: int) -> Dict[str, Any]:
    _align_position_mode(client)
    side, abs_qty, entry = _fetch_position_side_qty_entry(client, symbol)
    ok, why = _gate_be_trail(client, symbol, side, entry)
    if not ok:
        return _err(why, skipped="be")
    flt = _get_filters(client, symbol)
    if side == "BUY":
        be_px = _quantize_price(symbol, entry * (1 + offset_bps / 10000.0), flt)
        opp = "SELL"
    else:
        be_px = _quantize_price(symbol, entry * (1 - offset_bps / 10000.0), flt)
        opp = "BUY"
    _cancel_open_conditional(client, symbol, kinds=("STOP", "TRAILING_STOP_MARKET"))
    order = client.futures_create_order(
        symbol=symbol, side=opp, type="STOP_MARKET",
        stopPrice=be_px, closePosition=True,
        workingType=os.getenv("BINANCE_WORKING_TYPE", "MARK_PRICE"),
        newClientOrderId=_build_client_order_id(symbol, opp, role="BE"),
    )
    return _ok(symbol=symbol, pos_side=side, qty=abs_qty, entry=entry, be_price=be_px, orderId=order.get("orderId"))

def _trail_impl(client, *, symbol: str, callbackRate: Optional[float], atr_mult: Optional[float]) -> Dict[str, Any]:
    _align_position_mode(client)
    side, abs_qty, entry = _fetch_position_side_qty_entry(client, symbol)
    last = _last_price(client, symbol)
    ok, why = _gate_be_trail(client, symbol, side, entry)
    if not ok:
        return _err(why, skipped="trail")

    cb_min = float(os.getenv("TRAIL_CALLBACK_MIN_PCT", "0.1"))
    cb_max = float(os.getenv("TRAIL_CALLBACK_MAX_PCT", "4.9"))
    cb = callbackRate
    if cb is None:
        try:
            if atr_mult:
                with suppress(Exception):
                    kl = client.futures_klines(symbol=symbol, interval="1m", limit=16)
                    trs = []
                    from math import fabs
                    for i in range(1, len(kl)):
                        h = float(kl[i][2]); l = float(kl[i][3]); pc = float(kl[i-1][4])
                        trs.append(max(h - l, fabs(h - pc), fabs(l - pc)))
                    atr = (sum(trs[-14:]) / 14.0) if len(trs) >= 14 else 0.0
                pct = (atr * float(atr_mult) / last * 100.0) if (last and atr) else 1.0
            else:
                pct = 1.0
        except Exception:
            pct = 1.0
        cb = max(cb_min, min(cb_max, float(pct)))
    else:
        cb = max(cb_min, min(cb_max, float(cb)))

    opp = "SELL" if side == "BUY" else "BUY"
    flt = _get_filters(client, symbol)
    _cancel_open_conditional(client, symbol, kinds=("STOP", "TRAILING_STOP_MARKET"))
    qty = _quantize_qty(symbol, abs_qty, flt)
    if qty <= 0:
        return _err("trail_qty_rounds_to_zero")
    order = client.futures_create_order(
        symbol=symbol, side=opp, type="TRAILING_STOP_MARKET",
        callbackRate=float(cb), quantity=qty, reduceOnly=True,
        newClientOrderId=_build_client_order_id(symbol, opp, role="TRAIL"),
        workingType=os.getenv("BINANCE_WORKING_TYPE", "MARK_PRICE"),
    )
    return _ok(symbol=symbol, pos_side=side, qty=qty, entry=entry, callbackRate=float(cb), orderId=order.get("orderId"))

def _tp_ladder_impl(client, *, symbol: str, pcts: List[float], splits: List[float]) -> Dict[str, Any]:
    _align_position_mode(client)
    side, abs_qty, entry = _fetch_position_side_qty_entry(client, symbol)
    last = _last_price(client, symbol)
    flt = _get_filters(client, symbol)
    opp = "SELL" if side == "BUY" else "BUY"

    # Cancel existing TPs
    for o in client.futures_get_open_orders(symbol=symbol.upper()) or []:
        typ = (o.get("type") or "").upper()
        if "TAKE_PROFIT" in typ:
            with suppress(Exception):
                client.futures_cancel_order(symbol=symbol.upper(), orderId=o["orderId"])

    placed = []
    for i, (pct, split) in enumerate(zip(pcts, splits), start=1):
        q_raw = abs_qty * float(split)
        q = _quantize_qty(symbol, q_raw, flt)
        if q <= 0:
            continue
        if side == "BUY":
            trig = _quantize_price(symbol, last * (1.0 + float(pct) / 100.0), flt)
        else:
            trig = _quantize_price(symbol, last * (1.0 - float(pct) / 100.0), flt)
        order = client.futures_create_order(
            symbol=symbol, side=opp, type="TAKE_PROFIT_MARKET",
            stopPrice=trig, quantity=q, reduceOnly=True, timeInForce="GTC",
            newClientOrderId=_build_client_order_id(symbol, opp, role=f"TP{i}"),
            workingType=os.getenv("BINANCE_WORKING_TYPE", "MARK_PRICE"),
        )
        placed.append({"i": i, "pct": float(pct), "split": float(split), "qty": q, "stop": trig, "orderId": order.get("orderId")})
    return _ok(symbol=symbol, side=side, qty=abs_qty, entry=entry, built=len(placed), orders=placed)

# === Close fraction impl (חולץ לשימוש גם ב-/close-percent) ===
def _close_impl(client, *, symbol: str, fraction: float) -> Dict[str, Any]:
    _align_position_mode(client)
    try:
        side, abs_qty, _ = _fetch_position_side_qty_entry(client, symbol)
    except HTTPException as he:
        if he.status_code in (404, 409):
            _ensure_guard(symbol, prefer_mode="native")
            return _err("no_open_position", skipped="close")
        return _err("http_error", status=he.status_code, detail=str(he.detail))
    except Exception as e:
        return _err("exception", detail=str(e))

    opp = "SELL" if side == "BUY" else "BUY"
    flt = _get_filters(client, symbol)
    qty = _quantize_qty(symbol, abs_qty * fraction, flt)
    if qty <= 0:
        _ensure_guard(symbol, prefer_mode="native")
        return _err("qty_to_close_zero")

    try:
        order = client.futures_create_order(
            symbol=symbol, side=opp, type="MARKET",
            quantity=qty, reduceOnly=True,
            newClientOrderId=_build_client_order_id(symbol, opp, role="CLOSE"),
        )
        out = _ok(symbol=symbol, fraction=fraction, qty_closed=qty, orderId=order.get("orderId"))
    except Exception as e:
        out = _err("exception", detail=str(e))
    _ensure_guard(symbol, prefer_mode="native")
    label = f"Close {int(round(fraction * 100))}%"
    _maybe_notify(symbol, label, out)
    return out

# =========================
# Anti-Replay wrapper
# =========================
def _ar_check(route: str, body: Any, *, ts: Optional[str], nonce: Optional[str], sig: Optional[str]) -> Optional[Dict[str, Any]]:
    ok, why = verify_request(
        ts_header=ts,
        nonce_header=nonce,
        signature_header=sig,
        route=route,
        body=body,
        require_signature=(os.getenv("ANTI_REPLAY_REQUIRE_SIGNATURE", "0").lower() in ("1","true","yes","on")),
    )
    if not ok:
        return _err("anti_replay_failed", detail=why, route=route)
    return None

# =========================
# Routes — הכול רך (200 תמיד)
# =========================
@router.post("/be", summary="Move SL to BE ± offset_bps (STOP_MARKET closePosition)")
def be(
    payload: Dict[str, Any] = Body(...),
    Authorization: Optional[str] = Header(None),
    x_timestamp: Optional[str] = Header(None, alias="X-Timestamp"),
    x_nonce: Optional[str] = Header(None, alias="X-Nonce"),
    x_signature: Optional[str] = Header(None, alias="X-Signature"),
):
    if not _auth_ok(Authorization):
        return _err("unauthorized")
    ar = _ar_check("/position-ops/be", payload, ts=x_timestamp, nonce=x_nonce, sig=x_signature)
    if ar:
        return ar

    symbol = (payload.get("symbol") or "").upper().strip()
    offset_bps = int(payload.get("offset_bps") or os.getenv("TP_BE_OFFSET_BPS") or 8)
    if not symbol:
        return _err("invalid_input", detail="symbol required")
    client, cerr = _get_client_soft()
    if not client:
        return _err(cerr or "binance_client_error")
    try:
        out = _be_impl(client, symbol=symbol, offset_bps=offset_bps)
    except HTTPException as he:
        out = _err("no_open_position", skipped="be") if he.status_code in (404, 409) else _err("http_error", status=he.status_code, detail=str(he.detail))
    except Exception as e:
        out = _err("exception", detail=str(e))
    _ensure_guard(symbol, prefer_mode="native")
    _maybe_notify(symbol, "BE", out)
    return out

@router.post("/trail", summary="Enable/refresh trailing SL (TRAILING_STOP_MARKET reduceOnly quantity)")
def trail(
    payload: Dict[str, Any] = Body(...),
    Authorization: Optional[str] = Header(None),
    x_timestamp: Optional[str] = Header(None, alias="X-Timestamp"),
    x_nonce: Optional[str] = Header(None, alias="X-Nonce"),
    x_signature: Optional[str] = Header(None, alias="X-Signature"),
):
    if not _auth_ok(Authorization):
        return _err("unauthorized")
    ar = _ar_check("/position-ops/trail", payload, ts=x_timestamp, nonce=x_nonce, sig=x_signature)
    if ar:
        return ar

    symbol = (payload.get("symbol") or "").upper().strip()
    cb = payload.get("callbackRate") or payload.get("callback_rate") or payload.get("callback_rate_pct")
    atr_mult = payload.get("atr_mult")
    if not symbol:
        return _err("invalid_input", detail="symbol required")
    client, cerr = _get_client_soft()
    if not client:
        return _err(cerr or "binance_client_error")
    try:
        out = _trail_impl(client, symbol=symbol, callbackRate=cb, atr_mult=atr_mult)
    except HTTPException as he:
        out = _err("no_open_position", skipped="trail") if he.status_code in (404, 409) else _err("http_error", status=he.status_code, detail=str(he.detail))
    except Exception as e:
        out = _err("exception", detail=str(e))
    _ensure_guard(symbol, prefer_mode="native")
    _maybe_notify(symbol, "Trail", out)
    return out

@router.post("/sl/move", summary="Move SL to a specific price (STOP_MARKET closePosition)")
def sl_move(
    payload: Dict[str, Any] = Body(...),
    Authorization: Optional[str] = Header(None),
    x_timestamp: Optional[str] = Header(None, alias="X-Timestamp"),
    x_nonce: Optional[str] = Header(None, alias="X-Nonce"),
    x_signature: Optional[str] = Header(None, alias="X-Signature"),
):
    if not _auth_ok(Authorization):
        return _err("unauthorized")
    ar = _ar_check("/position-ops/sl/move", payload, ts=x_timestamp, nonce=x_nonce, sig=x_signature)
    if ar:
        return ar

    symbol = (payload.get("symbol") or "").upper().strip()
    try:
        price = float(payload.get("price") or 0)
    except Exception:
        price = 0.0
    if not symbol or price <= 0:
        return _err("invalid_input", detail="symbol and positive price required")

    client, cerr = _get_client_soft()
    if not client:
        return _err(cerr or "binance_client_error")
    _align_position_mode(client)
    try:
        side, abs_qty, entry = _fetch_position_side_qty_entry(client, symbol)
    except HTTPException as he:
        if he.status_code in (404, 409):
            _ensure_guard(symbol, prefer_mode="native")
            return _err("no_open_position", skipped="sl_move")
        return _err("http_error", status=he.status_code, detail=str(he.detail))
    except Exception as e:
        return _err("exception", detail=str(e))

    flt = _get_filters(client, symbol)
    opp = "SELL" if side == "BUY" else "BUY"
    px = _quantize_price(symbol, price, flt)

    try:
        _cancel_open_conditional(client, symbol, kinds=("STOP", "TRAILING_STOP_MARKET"))
        order = client.futures_create_order(
            symbol=symbol, side=opp, type="STOP_MARKET",
            stopPrice=px, closePosition=True,
            newClientOrderId=_build_client_order_id(symbol, opp, role="SL"),
            workingType=os.getenv("BINANCE_WORKING_TYPE", "MARK_PRICE"),
        )
        res = _ok(symbol=symbol, pos_side=side, qty=abs_qty, entry=entry, sl_price=px, orderId=order.get("orderId"))
    except Exception as e:
        res = _err("exception", detail=str(e))
    _ensure_guard(symbol, prefer_mode="native")
    _maybe_notify(symbol, "SL Move", res)
    return res

@router.post("/tp/ladder", summary="Create/refresh TP ladder (TAKE_PROFIT_MARKET reduce-only partials)")
def tp_ladder(
    payload: Dict[str, Any] = Body(...),
    Authorization: Optional[str] = Header(None),
    x_timestamp: Optional[str] = Header(None, alias="X-Timestamp"),
    x_nonce: Optional[str] = Header(None, alias="X-Nonce"),
    x_signature: Optional[str] = Header(None, alias="X-Signature"),
):
    if not _auth_ok(Authorization):
        return _err("unauthorized")
    ar = _ar_check("/position-ops/tp/ladder", payload, ts=x_timestamp, nonce=x_nonce, sig=x_signature)
    if ar:
        return ar

    symbol = (payload.get("symbol") or "").upper().strip()
    try:
        pcts: List[float] = payload.get("pcts") or [float(x) for x in (os.getenv("LADDER_TP_DEFAULT_PCTS", "1.8,3.2,5.5").split(","))]
        splits: List[float] = payload.get("splits") or [float(x) for x in (os.getenv("LADDER_TP_DEFAULT_SPLITS", "0.4,0.35,0.25").split(","))]
    except Exception:
        return _err("invalid_input", detail="pcts/splits must be float lists")
    if not symbol:
        return _err("invalid_input", detail="symbol required")
    if not pcts or not splits or len(pcts) != len(splits):
        return _err("invalid_input", detail="pcts and splits must be same length")

    client, cerr = _get_client_soft()
    if not client:
        return _err(cerr or "binance_client_error")
    try:
        out = _tp_ladder_impl(client, symbol=symbol, pcts=pcts, splits=splits)
    except HTTPException as he:
        out = _err("no_open_position", skipped="tp_ladder", pcts=pcts, splits=splits) if he.status_code in (404, 409) else _err("http_error", status=he.status_code, detail=str(he.detail))
    except Exception as e:
        out = _err("exception", detail=str(e))
    _ensure_guard(symbol, prefer_mode="native")
    _maybe_notify(symbol, "TP Ladder", out)
    return out

@router.post("/tp/one", summary="Create/refresh a single native TP (TAKE_PROFIT_MARKET reduce-only)")
def tp_one(
    payload: Dict[str, Any] = Body(...),
    Authorization: Optional[str] = Header(None),
    x_timestamp: Optional[str] = Header(None, alias="X-Timestamp"),
    x_nonce: Optional[str] = Header(None, alias="X-Nonce"),
    x_signature: Optional[str] = Header(None, alias="X-Signature"),
):
    if not _auth_ok(Authorization):
        return _err("unauthorized")
    ar = _ar_check("/position-ops/tp/one", payload, ts=x_timestamp, nonce=x_nonce, sig=x_signature)
    if ar:
        return ar

    symbol = (payload.get("symbol") or "").upper().strip()
    pct = payload.get("pct")
    price = payload.get("price")
    if not symbol or (pct is None and price is None):
        return _err("invalid_input", detail="symbol and (pct or price) required")

    client, cerr = _get_client_soft()
    if not client:
        return _err(cerr or "binance_client_error")
    _align_position_mode(client)
    try:
        side, abs_qty, entry = _fetch_position_side_qty_entry(client, symbol)
    except HTTPException as he:
        if he.status_code in (404, 409):
            _ensure_guard(symbol, prefer_mode="native")
            return _err("no_open_position", skipped="tp_one")
        return _err("http_error", status=he.status_code, detail=str(he.detail))
    except Exception as e:
        return _err("exception", detail=str(e))

    last = _last_price(client, symbol)
    flt = _get_filters(client, symbol)
    opp = "SELL" if side == "BUY" else "BUY"

    # בטל TP קיימים
    for o in client.futures_get_open_orders(symbol=symbol.upper()) or []:
        typ = (o.get("type") or "").upper()
        if "TAKE_PROFIT" in typ:
            with suppress(Exception):
                client.futures_cancel_order(symbol=symbol.upper(), orderId=o["orderId"])

    if price is not None:
        try:
            trig = _quantize_price(symbol, float(price), flt)
        except Exception:
            return _err("invalid_input", detail="price must be numeric")
    else:
        try:
            pct = float(pct)
        except Exception:
            return _err("invalid_input", detail="pct must be numeric")
        trig = _quantize_price(symbol, (last * (1.0 + pct / 100.0)) if side == "BUY" else (last * (1.0 - pct / 100.0)), flt)

    qty = _quantize_qty(symbol, abs_qty, flt)
    if qty <= 0:
        _ensure_guard(symbol, prefer_mode="native")
        return _err("tp_qty_rounds_to_zero")

    try:
        order = client.futures_create_order(
            symbol=symbol, side=opp, type="TAKE_PROFIT_MARKET",
            stopPrice=trig, quantity=qty, reduceOnly=True, timeInForce="GTC",
            newClientOrderId=_build_client_order_id(symbol, opp, role="TP1"),
            workingType=os.getenv("BINANCE_WORKING_TYPE", "MARK_PRICE"),
        )
        res = _ok(symbol=symbol, side=side, qty=qty, entry=entry, stop=trig, orderId=order.get("orderId"))
    except Exception as e:
        res = _err("exception", detail=str(e))
    _ensure_guard(symbol, prefer_mode="native")
    _maybe_notify(symbol, "TP One", res)
    return res

@router.post("/tp/cancel", summary="Cancel all TP orders")
def tp_cancel(
    payload: Dict[str, Any] = Body(...),
    Authorization: Optional[str] = Header(None),
    x_timestamp: Optional[str] = Header(None, alias="X-Timestamp"),
    x_nonce: Optional[str] = Header(None, alias="X-Nonce"),
    x_signature: Optional[str] = Header(None, alias="X-Signature"),
):
    if not _auth_ok(Authorization):
        return _err("unauthorized")
    ar = _ar_check("/position-ops/tp/cancel", payload, ts=x_timestamp, nonce=x_nonce, sig=x_signature)
    if ar:
        return ar

    symbol = (payload.get("symbol") or "").upper().strip()
    if not symbol:
        return _err("invalid_input", detail="symbol required")
    client, cerr = _get_client_soft()
    if not client:
        return _err(cerr or "binance_client_error")
    _align_position_mode(client)
    n = 0
    try:
        for o in client.futures_get_open_orders(symbol=symbol.upper()) or []:
            if "TAKE_PROFIT" in (o.get("type") or "").upper():
                with suppress(Exception):
                    client.futures_cancel_order(symbol=symbol.upper(), orderId=o["orderId"])
                    n += 1
        out = _ok(symbol=symbol, cancelled=n)
    except Exception as e:
        out = _err("exception", detail=str(e))
    _ensure_guard(symbol, prefer_mode="native")
    _maybe_notify(symbol, "Cancel TPs", out)
    return out

@router.post("/close", summary="Close fraction of the position (reduce-only MARKET)")
def close_fraction(
    payload: Dict[str, Any] = Body(...),
    Authorization: Optional[str] = Header(None),
    x_timestamp: Optional[str] = Header(None, alias="X-Timestamp"),
    x_nonce: Optional[str] = Header(None, alias="X-Nonce"),
    x_signature: Optional[str] = Header(None, alias="X-Signature"),
):
    if not _auth_ok(Authorization):
        return _err("unauthorized")
    ar = _ar_check("/position-ops/close", payload, ts=x_timestamp, nonce=x_nonce, sig=x_signature)
    if ar:
        return ar

    symbol = (payload.get("symbol") or "").upper().strip()
    try:
        fraction = float(payload.get("fraction") or 1.0)
    except Exception:
        fraction = -1
    if not symbol:
        return _err("invalid_input", detail="symbol required")
    if fraction < 0:
        return _err("invalid_input", detail="fraction must be numeric between 0..1")
    fraction = max(0.0, min(1.0, fraction))

    client, cerr = _get_client_soft()
    if not client:
        return _err(cerr or "binance_client_error")

    return _close_impl(client, symbol=symbol, fraction=fraction)

@router.post("/manage-once", summary="One-shot smart manage: BE + TRAIL + TP ladder")
def manage_once(
    payload: Dict[str, Any] = Body(...),
    Authorization: Optional[str] = Header(None),
    x_timestamp: Optional[str] = Header(None, alias="X-Timestamp"),
    x_nonce: Optional[str] = Header(None, alias="X-Nonce"),
    x_signature: Optional[str] = Header(None, alias="X-Signature"),
):
    if not _auth_ok(Authorization):
        return _err("unauthorized")
    ar = _ar_check("/position-ops/manage-once", payload, ts=x_timestamp, nonce=x_nonce, sig=x_signature)
    if ar:
        return ar

    symbol = (payload.get("symbol") or "").upper().strip()
    do = payload.get("do") or ["be", "trail", "tp_ladder"]
    offset_bps = int(payload.get("offset_bps") or os.getenv("TP_BE_OFFSET_BPS") or 8)
    callbackRate = payload.get("callbackRate")
    pcts = payload.get("pcts")
    splits = payload.get("splits")
    atr_mult = payload.get("atr_mult") or os.getenv("SMART_MANAGE_TRAIL_ATR_MULT")
    if not symbol:
        return _err("invalid_input", detail="symbol required")

    client, cerr = _get_client_soft()
    if not client:
        return _err(cerr or "binance_client_error")
    _align_position_mode(client)

    out: Dict[str, Any] = {"symbol": symbol, "ok": True, "steps": {}}

    try:
        side, abs_qty, entry = _fetch_position_side_qty_entry(client, symbol)
    except HTTPException as he:
        if he.status_code in (404, 409):
            out["ok"] = False
            out["reason"] = "no_open_position"
            out["steps"] = {
                "be": {"ok": False, "skipped": "be"},
                "trail": {"ok": False, "skipped": "trail"},
                "tp_ladder": {"ok": False, "skipped": "tp_ladder"},
            }
            _ensure_guard(symbol, prefer_mode="native")
            return out
        out["ok"] = False
        out["reason"] = "http_error"
        out["detail"] = str(he.detail)
        _ensure_guard(symbol, prefer_mode="native")
        return out
    except Exception as e:
        _ensure_guard(symbol, prefer_mode="native")
        return _err("position_fetch_failed", detail=str(e))

    allow_be_trail, reason = _gate_be_trail(client, symbol, side, entry)

    try:
        if "be" in do and allow_be_trail:
            out["steps"]["be"] = _be_impl(client, symbol=symbol, offset_bps=offset_bps)
        elif "be" in do and not allow_be_trail:
            out["steps"]["be"] = _err(reason, skipped="be")
    except Exception as e:
        out["ok"] = False
        out["steps"]["be"] = _err("exception", detail=str(e))

    try:
        if "trail" in do and allow_be_trail:
            out["steps"]["trail"] = _trail_impl(client, symbol=symbol, callbackRate=callbackRate, atr_mult=atr_mult)
        elif "trail" in do and not allow_be_trail:
            out["steps"]["trail"] = _err(reason, skipped="trail")
    except Exception as e:
        out["ok"] = False
        out["steps"]["trail"] = _err("exception", detail=str(e))

    try:
        if "tp_ladder" in do:
            if pcts is None:
                pcts = [float(x) for x in (os.getenv("LADDER_TP_DEFAULT_PCTS", "1.8,3.2,5.5").split(","))]
            if splits is None:
                splits = [float(x) for x in (os.getenv("LADDER_TP_DEFAULT_SPLITS", "0.4,0.35,0.25").split(","))]
            out["steps"]["tp_ladder"] = _tp_ladder_impl(client, symbol=symbol, pcts=pcts, splits=splits)
    except Exception as e:
        out["ok"] = False
        out["steps"]["tp_ladder"] = _err("exception", detail=str(e))

    _ensure_guard(symbol, prefer_mode="native")

    try:
        success_any = any(isinstance(v, dict) and v.get("ok") for v in out.get("steps", {}).values())
        if success_any:
            _notify_ops(symbol, "Manage Once")
    except Exception:
        pass

    return out

# =========================
# Scheduler פנימי (אופציונלי) — נשאר רך
# =========================
_SCHED_TASK: Optional[asyncio.Task] = None
_SCHED_ACTIVE = False

def _sched_should_run() -> bool:
    return (os.getenv("AUTO_MOVE_ENABLE", "0").lower() in ("1", "true", "yes", "on"))

def _parse_csv_floats(val: Optional[str]) -> Optional[List[float]]:
    if not val:
        return None
    try:
        return [float(x.strip()) for x in str(val).split(",") if str(x).strip()]
    except Exception:
        return None

async def _auto_loop(symbols: List[str], every_sec: int, steps: List[str],
                     offset_bps: int, cb_rate: Optional[float], atr_mult: Optional[float],
                     pcts: Optional[List[float]], splits: Optional[List[float]]) -> None:
    global _SCHED_ACTIVE
    client, cerr = _get_client_soft()
    if not client:
        logger.warning("auto_loop.client_unavailable: %s", cerr)
        return
    _align_position_mode(client)
    while _SCHED_ACTIVE:
        started = time.time()
        for sym in symbols:
            try:
                infos = client.futures_position_information(symbol=sym) or []
                if not infos:
                    continue
                amt = float(infos[0].get("positionAmt") or 0.0)
                if abs(amt) < 1e-12:
                    continue
                body_steps: List[str] = steps
                side, abs_qty, entry = _fetch_position_side_qty_entry(client, sym)
                allow_be_trail, reason = _gate_be_trail(client, sym, side, entry)

                if "be" in body_steps:
                    if allow_be_trail:
                        _ = _be_impl(client, symbol=sym, offset_bps=offset_bps)
                    else:
                        logger.debug("auto be skipped %s: %s", sym, reason)
                if "trail" in body_steps:
                    if allow_be_trail:
                        _ = _trail_impl(client, symbol=sym, callbackRate=cb_rate, atr_mult=atr_mult)
                    else:
                        logger.debug("auto trail skipped %s: %s", sym, reason)
                if "tp_ladder" in body_steps:
                    ppcts = pcts or _parse_csv_floats(os.getenv("SMART_MANAGE_PCTS")) or [1.8, 3.2, 5.5]
                    psplits = splits or _parse_csv_floats(os.getenv("SMART_MANAGE_SPLITS")) or [0.4, 0.35, 0.25]
                    _ = _tp_ladder_impl(client, symbol=sym, pcts=ppcts, splits=psplits)

                _ensure_guard(sym, prefer_mode="native")
            except Exception as e:
                logger.warning("auto_loop.symbol_failed %s: %s", sym, e)
        elapsed = time.time() - started
        sleep_for = max(1.0, every_sec - elapsed)
        await asyncio.sleep(sleep_for)

@router.post("/auto/start", summary="Start periodic smart-manage loop (every N sec) for given symbols")
async def auto_start(
    payload: Dict[str, Any] = Body(...),
    Authorization: Optional[str] = Header(None),
    x_timestamp: Optional[str] = Header(None, alias="X-Timestamp"),
    x_nonce: Optional[str] = Header(None, alias="X-Nonce"),
    x_signature: Optional[str] = Header(None, alias="X-Signature"),
):
    if not _auth_ok(Authorization):
        return _err("unauthorized")
    ar = _ar_check("/position-ops/auto/start", payload, ts=x_timestamp, nonce=x_nonce, sig=x_signature)
    if ar:
        return ar

    if not _sched_should_run():
        return _err("auto_move_disabled")
    symbols = [str(x).upper() for x in (payload.get("symbols") or [])]
    if not symbols:
        wl = os.getenv("WATCHLIST", "") or ""
        symbols = [s.strip().upper() for s in wl.split(",") if s.strip()]
    if not symbols:
        return _err("invalid_input", detail="symbols required or WATCHLIST must be set")

    every_sec = int(payload.get("every_sec") or os.getenv("AUTO_MOVE_EVERY_SEC", "20"))
    steps = [s.strip().lower() for s in (payload.get("steps") or (os.getenv("AUTO_MOVE_STEPS", "be,trail").split(",")))]
    offset_bps = int(payload.get("offset_bps") or os.getenv("TP_BE_OFFSET_BPS", "8"))
    cb_rate = payload.get("callbackRate")
    atr_mult = payload.get("atr_mult") or (float(os.getenv("SMART_MANAGE_TRAIL_ATR_MULT", "0") or 0) or None)
    pcts = payload.get("pcts") or _parse_csv_floats(os.getenv("SMART_MANAGE_PCTS"))
    splits = payload.get("splits") or _parse_csv_floats(os.getenv("SMART_MANAGE_SPLITS"))

    global _SCHED_TASK, _SCHED_ACTIVE
    if _SCHED_ACTIVE and _SCHED_TASK and not _SCHED_TASK.done():
        return _ok(status="already_running")

    _SCHED_ACTIVE = True
    _SCHED_TASK = asyncio.create_task(
        _auto_loop(symbols, every_sec, steps, offset_bps, cb_rate, atr_mult, pcts, splits)
    )
    return _ok(status="started", symbols=symbols, every_sec=every_sec, steps=steps)

@router.post("/auto/stop", summary="Stop periodic smart-manage loop")
async def auto_stop(
    Authorization: Optional[str] = Header(None),
    x_timestamp: Optional[str] = Header(None, alias="X-Timestamp"),
    x_nonce: Optional[str] = Header(None, alias="X-Nonce"),
    x_signature: Optional[str] = Header(None, alias="X-Signature"),
):
    if not _auth_ok(Authorization):
        return _err("unauthorized")
    ar = _ar_check("/position-ops/auto/stop", body={}, ts=x_timestamp, nonce=x_nonce, sig=x_signature)
    if ar:
        return ar

    global _SCHED_TASK, _SCHED_ACTIVE
    _SCHED_ACTIVE = False
    if _SCHED_TASK:
        with suppress(Exception):
            _SCHED_TASK.cancel()
    return _ok(status="stopped")

# =========================
# Compatibility aliases (כפי שהאינטגרציה של הטלגרם מצפה)
# =========================

@router.post("/cancel-tps", summary="[ALIAS] Cancel all TP orders (alias of /tp/cancel)")
def cancel_tps_alias(
    payload: Dict[str, Any] = Body(...),
    Authorization: Optional[str] = Header(None),
    x_timestamp: Optional[str] = Header(None, alias="X-Timestamp"),
    x_nonce: Optional[str] = Header(None, alias="X-Nonce"),
    x_signature: Optional[str] = Header(None, alias="X-Signature"),
):
    # נשתמש בלוגיקת tp_cancel כדי לשמור על מקור אמת יחיד
    return tp_cancel(payload=payload, Authorization=Authorization,
                     x_timestamp=x_timestamp, x_nonce=x_nonce, x_signature=x_signature)

@router.post("/close-percent", summary="[ALIAS] Close by percent (maps pct→fraction and calls /close)")
def close_percent_alias(
    payload: Dict[str, Any] = Body(...),
    Authorization: Optional[str] = Header(None),
    x_timestamp: Optional[str] = Header(None, alias="X-Timestamp"),
    x_nonce: Optional[str] = Header(None, alias="X-Nonce"),
    x_signature: Optional[str] = Header(None, alias="X-Signature"),
):
    if not _auth_ok(Authorization):
        return _err("unauthorized")
    # בדיקת Anti-Replay למסלול האליאס
    ar = _ar_check("/position-ops/close-percent", payload, ts=x_timestamp, nonce=x_nonce, sig=x_signature)
    if ar:
        return ar

    symbol = (payload.get("symbol") or "").upper().strip()
    try:
        pct = float(payload.get("pct") if payload.get("pct") is not None else payload.get("percent"))
    except Exception:
        return _err("invalid_input", detail="pct (0..100) required")
    if not symbol:
        return _err("invalid_input", detail="symbol required")
    pct = max(0.0, min(100.0, pct))
    fraction = pct / 100.0

    client, cerr = _get_client_soft()
    if not client:
        return _err(cerr or "binance_client_error")

    return _close_impl(client, symbol=symbol, fraction=fraction)








