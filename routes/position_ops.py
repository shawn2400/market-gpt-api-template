# routes/position_ops.py
from __future__ import annotations

import os
import time
import math
import logging
import asyncio
from typing import Any, Dict, List, Optional, Tuple
from contextlib import suppress

from fastapi import APIRouter, Body, HTTPException, Header

logger = logging.getLogger("algogpt.position_ops")
router = APIRouter(prefix="/position-ops", tags=["position-ops"])

# Guard (אופציונלי, שקט אם חסר)
GUARD_ENSURE_AFTER_OPS = (os.getenv("GUARD_ENSURE_AFTER_OPS", "1").lower() in ("1", "true", "yes", "on"))
with suppress(Exception):
    from utils.guard_stop import ensure_protective_stop  # type: ignore

def _ensure_guard(symbol: str, *, prefer_mode: str = "native") -> None:
    if not GUARD_ENSURE_AFTER_OPS:
        return
    with suppress(Exception):
        ensure_protective_stop(symbol, prefer_mode=prefer_mode)  # type: ignore

# =========================
# Helpers: auth (Bearer)
# =========================
API_BEARER_TOKEN = (os.getenv("API_BEARER_TOKEN") or os.getenv("API_TOKEN") or "").strip()

def _require_bearer(auth_header: Optional[str]) -> None:
    if not API_BEARER_TOKEN:
        return
    if not auth_header or not auth_header.startswith("Bearer ") or auth_header.split(" ", 1)[1].strip() != API_BEARER_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

# =========================
# Order IDs
# =========================
def _coid_fit(s: str, limit: int = 32) -> str:
    return s if len(s) <= limit else s[: limit - 8] + "_" + str(abs(hash(s)))[:7]

def _build_client_order_id(symbol: str, side: str, role: str = "ENTRY") -> str:
    prefix = (os.getenv("ORDER_ID_PREFIX") or "ALG").strip() or "ALG"
    sym = str(symbol).upper()
    side = str(side).upper()
    role = str(role).upper()
    ts = int(time.time())
    return _coid_fit(f"{prefix}_{sym}_{side}_{role}_{ts}", 32)

with suppress(Exception):
    from utils.order_ids import build_client_order_id  # type: ignore
    _build_client_order_id = build_client_order_id  # override if exists

# =========================
# Quantize
# =========================
def _fallback_filters():
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

def _get_filters(client, symbol: str) -> Dict[str, Any]:
    try:
        ex = client.futures_exchange_info() or {}
        for s in ex.get("symbols", []):
            if str(s.get("symbol", "")).upper() == symbol.upper():
                price_tick = None
                qty_step = None
                for f in s.get("filters", []):
                    ft = f.get("filterType")
                    if ft == "PRICE_FILTER":
                        price_tick = float(f.get("tickSize") or 0.0)
                    if ft == "LOT_SIZE":
                        qty_step = float(f.get("stepSize") or 0.0)
                out = {"price_tick": price_tick or 0.0, "qty_step": qty_step or 0.0}
                return out if (out["price_tick"] or out["qty_step"]) else _fallback_filters()
    except Exception:
        pass
    return _fallback_filters()

with suppress(Exception):
    from utils.quantize import get_filters as _gf, quantize_price as _qp, quantize_qty as _qq  # type: ignore
    def _get_filters(client, symbol: str) -> Dict[str, Any]:  # type: ignore
        return _gf(client, symbol)
    def _quantize_price(symbol: str, price: float, flt: Dict[str, Any]) -> float:  # type: ignore
        return _qp(symbol, price, flt)
    def _quantize_qty(symbol: str, qty: float, flt: Dict[str, Any]) -> float:  # type: ignore
        return _qq(symbol, qty, flt)

# =========================
# Binance client
# =========================
def _get_client():
    try:
        from binance.client import Client  # type: ignore
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"binance import failed: {e}")
    api_key = os.getenv("BINANCE_API_KEY", "").strip()
    api_sec = os.getenv("BINANCE_API_SECRET", "").strip()
    if not api_key or not api_sec:
        raise HTTPException(status_code=500, detail="BINANCE keys missing")
    return Client(api_key, api_sec)

def _align_position_mode(client) -> None:
    mode_override = (os.getenv("POSITION_MODE_OVERRIDE", "") or "").strip().lower()
    with suppress(Exception):
        if mode_override in ("hedge", "dual", "dual_side", "dual_side_position", "dualposition"):
            client.futures_change_position_mode(dualSidePosition="true")
        elif mode_override in ("oneway", "one_way", "single", "single_side", "oneside"):
            client.futures_change_position_mode(dualSidePosition="false")

# =========================
# Position & price helpers
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

def _last_price(symbol: str) -> float:
    cli = _get_client()
    p = cli.futures_symbol_ticker(symbol=symbol.upper())
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
        last = _last_price(symbol)
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
        return {"ok": False, "reason": why, "skipped": "be"}

    flt = _get_filters(client, symbol)
    if side == "BUY":
        be_px = _quantize_price(symbol, entry * (1 + offset_bps / 10000.0), flt)
        opp = "SELL"
    else:
        be_px = _quantize_price(symbol, entry * (1 - offset_bps / 10000.0), flt)
        opp = "BUY"

    _cancel_open_conditional(client, symbol, kinds=("STOP", "TRAILING_STOP_MARKET"))
    order = client.futures_create_order(
        symbol=symbol,
        side=opp,
        type="STOP_MARKET",
        stopPrice=be_px,
        closePosition=True,
        workingType=os.getenv("BINANCE_WORKING_TYPE", "MARK_PRICE"),
        newClientOrderId=_build_client_order_id(symbol, opp, role="BE"),
    )
    out = {
        "ok": True,
        "symbol": symbol,
        "pos_side": side,
        "qty": abs_qty,
        "entry": entry,
        "be_price": be_px,
        "orderId": order.get("orderId"),
    }
    return out

def _trail_impl(client, *, symbol: str, callbackRate: Optional[float], atr_mult: Optional[float]) -> Dict[str, Any]:
    _align_position_mode(client)
    side, abs_qty, entry = _fetch_position_side_qty_entry(client, symbol)
    last = _last_price(symbol)
    ok, why = _gate_be_trail(client, symbol, side, entry)
    if not ok:
        return {"ok": False, "reason": why, "skipped": "trail"}

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
        return {"ok": False, "error": "trail qty rounds to zero"}

    order = client.futures_create_order(
        symbol=symbol,
        side=opp,
        type="TRAILING_STOP_MARKET",
        callbackRate=float(cb),
        quantity=qty,
        reduceOnly=True,
        newClientOrderId=_build_client_order_id(symbol, opp, role="TRAIL"),
        workingType=os.getenv("BINANCE_WORKING_TYPE", "MARK_PRICE"),
    )
    out = {
        "ok": True,
        "symbol": symbol,
        "pos_side": side,
        "qty": qty,
        "entry": entry,
        "callbackRate": float(cb),
        "orderId": order.get("orderId"),
    }
    return out

def _tp_ladder_impl(client, *, symbol: str, pcts: List[float], splits: List[float]) -> Dict[str, Any]:
    _align_position_mode(client)
    side, abs_qty, entry = _fetch_position_side_qty_entry(client, symbol)
    last = _last_price(symbol)
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
            symbol=symbol,
            side=opp,
            type="TAKE_PROFIT_MARKET",
            stopPrice=trig,
            quantity=q,
            reduceOnly=True,
            timeInForce="GTC",
            newClientOrderId=_build_client_order_id(symbol, opp, role=f"TP{i}"),
            workingType=os.getenv("BINANCE_WORKING_TYPE", "MARK_PRICE"),
        )
        placed.append({"i": i, "pct": float(pct), "split": float(split), "qty": q, "stop": trig, "orderId": order.get("orderId")})

    result = {
        "ok": True,
        "symbol": symbol,
        "side": side,
        "qty": abs_qty,
        "entry": entry,
        "built": len(placed),
        "orders": placed,
    }
    return result

# =========================
# BE (route)
# =========================
@router.post("/be", summary="Move SL to BE ± offset_bps (STOP_MARKET closePosition)")
def be(payload: Dict[str, Any] = Body(...), Authorization: Optional[str] = Header(None)):
    _require_bearer(Authorization)
    symbol = (payload.get("symbol") or "").upper()
    offset_bps = int(payload.get("offset_bps") or os.getenv("TP_BE_OFFSET_BPS") or 8)
    if not symbol:
        raise HTTPException(status_code=422, detail="symbol required")

    client = _get_client()
    out = _be_impl(client, symbol=symbol, offset_bps=offset_bps)
    _ensure_guard(symbol, prefer_mode="native")
    return out

# =========================
# Trail (route)
# =========================
@router.post("/trail", summary="Enable/refresh trailing SL (TRAILING_STOP_MARKET reduceOnly quantity)")
def trail(payload: Dict[str, Any] = Body(...), Authorization: Optional[str] = Header(None)):
    _require_bearer(Authorization)
    symbol = (payload.get("symbol") or "").upper()
    cb = payload.get("callbackRate") or payload.get("callback_rate") or payload.get("callback_rate_pct")
    atr_mult = payload.get("atr_mult")
    if not symbol:
        raise HTTPException(status_code=422, detail="symbol required")

    client = _get_client()
    out = _trail_impl(client, symbol=symbol, callbackRate=cb, atr_mult=atr_mult)
    _ensure_guard(symbol, prefer_mode="native")
    return out

# =========================
# SL לפי מחיר
# =========================
@router.post("/sl/move", summary="Move SL to a specific price (STOP_MARKET closePosition)")
def sl_move(payload: Dict[str, Any] = Body(...), Authorization: Optional[str] = Header(None)):
    _require_bearer(Authorization)
    symbol = (payload.get("symbol") or "").upper()
    price = float(payload.get("price") or 0)
    if not symbol or price <= 0:
        raise HTTPException(status_code=422, detail="symbol, price required")

    client = _get_client()
    _align_position_mode(client)
    side, abs_qty, entry = _fetch_position_side_qty_entry(client, symbol)
    flt = _get_filters(client, symbol)

    opp = "SELL" if side == "BUY" else "BUY"
    px = _quantize_price(symbol, price, flt)

    _cancel_open_conditional(client, symbol, kinds=("STOP", "TRAILING_STOP_MARKET"))
    order = client.futures_create_order(
        symbol=symbol,
        side=opp,
        type="STOP_MARKET",
        stopPrice=px,
        closePosition=True,
        newClientOrderId=_build_client_order_id(symbol, opp, role="SL"),
        workingType=os.getenv("BINANCE_WORKING_TYPE", "MARK_PRICE"),
    )
    res = {"ok": True, "symbol": symbol, "pos_side": side, "qty": abs_qty, "entry": entry, "sl_price": px, "orderId": order.get("orderId")}
    _ensure_guard(symbol, prefer_mode="native")
    return res

# =========================
# TP Ladder (route)
# =========================
@router.post("/tp/ladder", summary="Create/refresh TP ladder (TAKE_PROFIT_MARKET reduce-only partials)")
def tp_ladder(payload: Dict[str, Any] = Body(...), Authorization: Optional[str] = Header(None)):
    _require_bearer(Authorization)
    symbol = (payload.get("symbol") or "").upper()
    pcts: List[float] = payload.get("pcts") or [float(x) for x in (os.getenv("LADDER_TP_DEFAULT_PCTS", "1.8,3.2,5.5").split(","))]
    splits: List[float] = payload.get("splits") or [float(x) for x in (os.getenv("LADDER_TP_DEFAULT_SPLITS", "0.4,0.35,0.25").split(","))]
    if not symbol:
        raise HTTPException(status_code=422, detail="symbol required")
    if not pcts or not splits or len(pcts) != len(splits):
        raise HTTPException(status_code=422, detail="pcts and splits must be same length")

    client = _get_client()
    out = _tp_ladder_impl(client, symbol=symbol, pcts=pcts, splits=splits)
    _ensure_guard(symbol, prefer_mode="native")
    return out

# =========================
# TP יחיד
# =========================
@router.post("/tp/one", summary="Create/refresh a single native TP (TAKE_PROFIT_MARKET reduce-only)")
def tp_one(payload: Dict[str, Any] = Body(...), Authorization: Optional[str] = Header(None)):
    _require_bearer(Authorization)
    symbol = (payload.get("symbol") or "").upper()
    pct = payload.get("pct")
    price = payload.get("price")
    if not symbol or (pct is None and price is None):
        raise HTTPException(status_code=422, detail="symbol and (pct or price) required")

    client = _get_client()
    _align_position_mode(client)
    side, abs_qty, entry = _fetch_position_side_qty_entry(client, symbol)
    last = _last_price(symbol)
    flt = _get_filters(client, symbol)
    opp = "SELL" if side == "BUY" else "BUY"

    for o in client.futures_get_open_orders(symbol=symbol.upper()) or []:
        typ = (o.get("type") or "").upper()
        if "TAKE_PROFIT" in typ:
            with suppress(Exception):
                client.futures_cancel_order(symbol=symbol.upper(), orderId=o["orderId"])

    if price is not None:
        trig = _quantize_price(symbol, float(price), flt)
    else:
        pct = float(pct)
        trig = _quantize_price(symbol, (last * (1.0 + pct / 100.0)) if side == "BUY" else (last * (1.0 - pct / 100.0)), flt)

    qty = _quantize_qty(symbol, abs_qty, flt)
    if qty <= 0:
        raise HTTPException(status_code=409, detail="tp qty rounds to zero")

    order = client.futures_create_order(
        symbol=symbol,
        side=opp,
        type="TAKE_PROFIT_MARKET",
        stopPrice=trig,
        quantity=qty,
        reduceOnly=True,
        timeInForce="GTC",
        newClientOrderId=_build_client_order_id(symbol, opp, role="TP1"),
        workingType=os.getenv("BINANCE_WORKING_TYPE", "MARK_PRICE"),
    )
    res = {"ok": True, "symbol": symbol, "side": side, "qty": qty, "entry": entry, "stop": trig, "orderId": order.get("orderId")}
    _ensure_guard(symbol, prefer_mode="native")
    return res

# =========================
# ביטול כל ה-TP
# =========================
@router.post("/tp/cancel", summary="Cancel all TP orders")
def tp_cancel(payload: Dict[str, Any] = Body(...), Authorization: Optional[str] = Header(None)):
    _require_bearer(Authorization)
    symbol = (payload.get("symbol") or "").upper()
    if not symbol:
        raise HTTPException(status_code=422, detail="symbol required")
    client = _get_client()
    _align_position_mode(client)
    n = 0
    for o in client.futures_get_open_orders(symbol=symbol.upper()) or []:
        if "TAKE_PROFIT" in (o.get("type") or "").upper():
            with suppress(Exception):
                client.futures_cancel_order(symbol=symbol.upper(), orderId=o["orderId"])
                n += 1
    _ensure_guard(symbol, prefer_mode="native")
    return {"ok": True, "symbol": symbol, "cancelled": n}

# =========================
# Close fraction
# =========================
@router.post("/close", summary="Close fraction of the position (reduce-only MARKET)")
def close_fraction(payload: Dict[str, Any] = Body(...), Authorization: Optional[str] = Header(None)):
    _require_bearer(Authorization)
    symbol = (payload.get("symbol") or "").upper()
    fraction = float(payload.get("fraction") or 1.0)
    fraction = max(0.0, min(1.0, fraction))
    if not symbol:
        raise HTTPException(status_code=422, detail="symbol required")

    client = _get_client()
    _align_position_mode(client)
    side, abs_qty, _ = _fetch_position_side_qty_entry(client, symbol)
    opp = "SELL" if side == "BUY" else "BUY"

    flt = _get_filters(client, symbol)
    qty = _quantize_qty(symbol, abs_qty * fraction, flt)
    if qty <= 0:
        return {"ok": False, "error": "qty_to_close_zero"}

    order = client.futures_create_order(
        symbol=symbol,
        side=opp,
        type="MARKET",
        quantity=qty,
        reduceOnly=True,
        newClientOrderId=_build_client_order_id(symbol, opp, role="CLOSE"),
    )
    _ensure_guard(symbol, prefer_mode="native")
    return {"ok": True, "symbol": symbol, "fraction": fraction, "qty_closed": qty, "orderId": order.get("orderId")}

# =========================
# One-shot manage (BE + Trail + TP ladder)
# =========================
@router.post("/manage-once", summary="One-shot smart manage: BE + TRAIL + TP ladder")
def manage_once(payload: Dict[str, Any] = Body(...), Authorization: Optional[str] = Header(None)):
    _require_bearer(Authorization)
    symbol = (payload.get("symbol") or "").upper()
    do = payload.get("do") or ["be", "trail", "tp_ladder"]
    offset_bps = int(payload.get("offset_bps") or os.getenv("TP_BE_OFFSET_BPS") or 8)
    callbackRate = payload.get("callbackRate")
    pcts = payload.get("pcts")
    splits = payload.get("splits")
    atr_mult = payload.get("atr_mult") or os.getenv("SMART_MANAGE_TRAIL_ATR_MULT")
    if not symbol:
        raise HTTPException(status_code=422, detail="symbol required")

    out: Dict[str, Any] = {"symbol": symbol, "ok": True, "steps": {}}

    client = _get_client()
    _align_position_mode(client)
    side, abs_qty, entry = _fetch_position_side_qty_entry(client, symbol)
    allow_be_trail, reason = _gate_be_trail(client, symbol, side, entry)

    try:
        if "be" in do and allow_be_trail:
            out["steps"]["be"] = _be_impl(client, symbol=symbol, offset_bps=offset_bps)
        elif "be" in do and not allow_be_trail:
            out["steps"]["be"] = {"ok": False, "reason": reason, "skipped": "be"}
    except Exception as e:
        out["ok"] = False
        out["steps"]["be"] = {"ok": False, "error": str(e)}

    try:
        if "trail" in do and allow_be_trail:
            out["steps"]["trail"] = _trail_impl(client, symbol=symbol, callbackRate=callbackRate, atr_mult=atr_mult)
        elif "trail" in do and not allow_be_trail:
            out["steps"]["trail"] = {"ok": False, "reason": reason, "skipped": "trail"}
    except Exception as e:
        out["ok"] = False
        out["steps"]["trail"] = {"ok": False, "error": str(e)}

    try:
        if "tp_ladder" in do:
            # default pcts/splits if not provided
            if pcts is None:
                pcts = [float(x) for x in (os.getenv("LADDER_TP_DEFAULT_PCTS", "1.8,3.2,5.5").split(","))]
            if splits is None:
                splits = [float(x) for x in (os.getenv("LADDER_TP_DEFAULT_SPLITS", "0.4,0.35,0.25").split(","))]
            out["steps"]["tp_ladder"] = _tp_ladder_impl(client, symbol=symbol, pcts=pcts, splits=splits)
    except Exception as e:
        out["ok"] = False
        out["steps"]["tp_ladder"] = {"ok": False, "error": str(e)}

    _ensure_guard(symbol, prefer_mode="native")
    return out

# =========================
# Scheduler פנימי (אופציונלי)
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
    client = _get_client()
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
async def auto_start(payload: Dict[str, Any] = Body(...), Authorization: Optional[str] = Header(None)):
    _require_bearer(Authorization)
    global _SCHED_TASK, _SCHED_ACTIVE
    if not _sched_should_run():
        return {"ok": False, "error": "AUTO_MOVE_ENABLE is off"}
    symbols = [str(x).upper() for x in (payload.get("symbols") or [])]
    if not symbols:
        wl = os.getenv("WATCHLIST", "") or ""
        symbols = [s.strip().upper() for s in wl.split(",") if s.strip()]
    if not symbols:
        raise HTTPException(status_code=422, detail="symbols required or WATCHLIST must be set")

    every_sec = int(payload.get("every_sec") or os.getenv("AUTO_MOVE_EVERY_SEC", "20"))
    steps = [s.strip().lower() for s in (payload.get("steps") or (os.getenv("AUTO_MOVE_STEPS", "be,trail").split(",")))]
    offset_bps = int(payload.get("offset_bps") or os.getenv("TP_BE_OFFSET_BPS", "8"))
    cb_rate = payload.get("callbackRate")
    atr_mult = payload.get("atr_mult") or (float(os.getenv("SMART_MANAGE_TRAIL_ATR_MULT", "0") or 0) or None)
    pcts = payload.get("pcts") or _parse_csv_floats(os.getenv("SMART_MANAGE_PCTS"))
    splits = payload.get("splits") or _parse_csv_floats(os.getenv("SMART_MANAGE_SPLITS"))

    if _SCHED_ACTIVE and _SCHED_TASK and not _SCHED_TASK.done():
        return {"ok": True, "status": "already_running"}

    _SCHED_ACTIVE = True
    _SCHED_TASK = asyncio.create_task(
        _auto_loop(symbols, every_sec, steps, offset_bps, cb_rate, atr_mult, pcts, splits)
    )
    return {"ok": True, "status": "started", "symbols": symbols, "every_sec": every_sec, "steps": steps}

@router.post("/auto/stop", summary="Stop periodic smart-manage loop")
async def auto_stop(Authorization: Optional[str] = Header(None)):
    _require_bearer(Authorization)
    global _SCHED_TASK, _SCHED_ACTIVE
    _SCHED_ACTIVE = False
    if _SCHED_TASK:
        with suppress(Exception):
            _SCHED_TASK.cancel()
    return {"ok": True, "status": "stopped"}







