# routes/position_ops.py
from __future__ import annotations

import os
import time
import math
import hashlib
import logging
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Body, HTTPException
from contextlib import suppress

logger = logging.getLogger("algogpt.position_ops")

router = APIRouter(prefix="/position-ops", tags=["position-ops"])

# =========================
# External executors (optional, used for simple reduce-only close)
# =========================
_execute_live = None
with suppress(Exception):
    from utils.trade_executor import execute_trade_live  # type: ignore
    _execute_live = execute_trade_live

# =========================
# Binance client helpers
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
# clientOrderId (recommended format, UI-friendly)
# ALG_MAIN_<SYMBOL>_<SIDE>_<ROLE>_<TS>[_EXTRA]  (<=32 chars)
# =========================
def _coid_fit(s: str, limit: int = 32) -> str:
    if len(s) <= limit:
        return s
    h = hashlib.md5(s.encode("utf-8")).hexdigest()[:7]
    return f"{s[:limit-8]}_{h}"

def build_client_order_id(symbol: str, side: str, role: str = "ENTRY", extra: Optional[str] = None) -> str:
    prefix = (os.getenv("ORDER_ID_PREFIX") or "ALG_MAIN").strip() or "ALG_MAIN"
    sym = str(symbol).upper()
    sd = str(side).upper()
    role = str(role).upper()
    ts = int(time.time())
    base = f"{prefix}_{sym}_{sd}_{role}_{ts}"
    if extra:
        extra_s = "".join(ch for ch in str(extra).upper() if ch.isalnum() or ch == "_")
        base = f"{base}_{extra_s}"
    return _coid_fit(base, 32)

# =========================
# Core fetch & math
# =========================
def _fetch_position_side_qty_entry(client, symbol: str) -> Tuple[str, float, float]:
    """Returns (side, abs_qty, entry_price). side is BUY for long (>0), SELL for short (<0)."""
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

def _fetch_open_orders(client, symbol: str) -> List[Dict[str, Any]]:
    return client.futures_get_open_orders(symbol=symbol) or []

def _cancel_order_ids(client, symbol: str, order_ids: List[int | str]) -> None:
    for oid in order_ids:
        with suppress(Exception):
            client.futures_cancel_order(symbol=symbol, orderId=oid if isinstance(oid, int) else None, origClientOrderId=None if isinstance(oid, int) else oid)

def _cancel_all_tp(client, symbol: str) -> int:
    orders = _fetch_open_orders(client, symbol)
    to_cancel = []
    for o in orders:
        typ = (o.get("type") or "").upper()
        if "TAKE_PROFIT" in typ:
            to_cancel.append(o.get("orderId"))
    _cancel_order_ids(client, symbol, [oid for oid in to_cancel if oid is not None])
    return len(to_cancel)

def _cancel_all_sl(client, symbol: str) -> int:
    orders = _fetch_open_orders(client, symbol)
    to_cancel = []
    for o in orders:
        typ = (o.get("type") or "").upper()
        if "STOP" in typ and "TAKE_PROFIT" not in typ:
            to_cancel.append(o.get("orderId"))
    _cancel_order_ids(client, symbol, [oid for oid in to_cancel if oid is not None])
    return len(to_cancel)

def _price_to_bps(base: float, bps: int, direction: int) -> float:
    # direction: +1 = above, -1 = below
    return base * (1.0 + (bps / 10000.0) * direction)

# =========================
# ATR (simple)
# =========================
def _atr(client, symbol: str, interval: str = "1m", length: int = 14) -> Optional[float]:
    with suppress(Exception):
        kl = client.futures_klines(symbol=symbol, interval=interval, limit=length + 2)
        highs = [float(k[2]) for k in kl]
        lows = [float(k[3]) for k in kl]
        closes = [float(k[4]) for k in kl]
        trs: List[float] = []
        for i in range(1, len(kl)):
            h, l, pc = highs[i], lows[i], closes[i - 1]
            tr = max(h - l, abs(h - pc), abs(l - pc))
            trs.append(tr)
        if not trs:
            return None
        return sum(trs[-length:]) / min(len(trs), length)
    return None

# =========================
# Close helpers (reduce-only market by fraction)
# =========================
async def _close_position(symbol: str, side: str, fraction: float, leverage: Optional[int] = None, position_side: str = "BOTH") -> Dict[str, Any]:
    if not _execute_live:
        # Fallback: place market reduce-only via Binance (quantity fraction)
        client = _get_client()
        _align_position_mode(client)
        pos_side, abs_qty, _ = _fetch_position_side_qty_entry(client, symbol)
        if pos_side != side.upper():
            # already in opposite? just return ok
            return {"ok": True, "note": "position side differs; nothing to close"}
        qty_to_close = abs_qty * max(0.0, min(1.0, float(fraction)))
        if qty_to_close <= 0:
            return {"ok": False, "error": "qty_to_close_zero"}
        opp_side = "SELL" if pos_side == "BUY" else "BUY"
        order = client.futures_create_order(
            symbol=symbol,
            side=opp_side,
            type="MARKET",
            quantity=qty_to_close,
            reduceOnly="true",
            newClientOrderId=build_client_order_id(symbol, opp_side, role="CLOSE"),
        )
        return {"ok": True, "exchange": "binance_futures", "order": order, "qty_closed": qty_to_close}

    # Preferred path: trade executor
    try:
        res = await _execute_live(
            symbol=symbol,
            side=("SELL" if side.upper() == "BUY" else "BUY"),
            budget=None,
            leverage=leverage or 0,
            dry_run=False,
            quantity=None,
            entry=None,
            tp_targets=None,
            sl_targets=None,
            tp_splits=None,
            sl_splits=None,
            confirm_first=False,
            telegram_chat_id=int(os.getenv("TELEGRAM_CHAT_ID") or 0),
            position_side=(position_side or "BOTH").upper(),
            reduce_only=True,
            fraction=fraction,
        )
        return res
    except Exception as e:
        logger.exception("close_position failed")
        return {"ok": False, "error": "close_failed", "detail": str(e)}

# =========================
# BE: move SL to breakeven ± offset_bps
# =========================
@router.post("/be", summary="Move SL to BE ± offset_bps (cancel existing SL, create new STOP_MARKET reduce-only)")
async def be(payload: Dict[str, Any] = Body(...)):
    symbol = (payload.get("symbol") or "").upper()
    offset_bps = int(payload.get("offset_bps") or os.getenv("TP_BE_OFFSET_BPS") or 8)
    force = bool(payload.get("force") or False)  # not used here, provided for API compatibility
    if not symbol:
        raise HTTPException(status_code=422, detail="symbol required")

    client = _get_client()
    _align_position_mode(client)
    side, abs_qty, entry = _fetch_position_side_qty_entry(client, symbol)

    # Cancel existing SL orders
    _cancel_all_sl(client, symbol)

    # Compute BE price
    if side == "BUY":
        be_price = _price_to_bps(entry, offset_bps, +1)  # a bit above entry
        opp_side = "SELL"
    else:
        be_price = _price_to_bps(entry, offset_bps, -1)  # a bit below entry
        opp_side = "BUY"

    order = client.futures_create_order(
        symbol=symbol,
        side=opp_side,
        type="STOP_MARKET",
        stopPrice=be_price,
        closePosition=True,
        reduceOnly="true",
        workingType=os.getenv("BINANCE_WORKING_TYPE", "MARK_PRICE"),
        newClientOrderId=build_client_order_id(symbol, opp_side, role="BE"),
    )
    return {"ok": True, "symbol": symbol, "side": side, "qty": abs_qty, "entry": entry, "be_price": be_price, "order": order}

# =========================
# Trail: create/update TRAILING_STOP_MARKET
# Either pass callback_rate (0.1–4.9), or atr_mult to compute callback from ATR
# =========================
@router.post("/trail", summary="Enable/refresh trailing SL (TRAILING_STOP_MARKET). You can pass callback_rate or atr_mult.")
async def trail(payload: Dict[str, Any] = Body(...)):
    symbol = (payload.get("symbol") or "").upper()
    atr_mult = payload.get("atr_mult")
    callback_rate = payload.get("callback_rate")
    interval = payload.get("interval") or "1m"
    if not symbol:
        raise HTTPException(status_code=422, detail="symbol required")

    client = _get_client()
    _align_position_mode(client)
    side, abs_qty, entry = _fetch_position_side_qty_entry(client, symbol)
    last = float(client.futures_symbol_ticker(symbol=symbol)["price"])

    # Cancel SLs (not TP)
    _cancel_all_sl(client, symbol)

    # Derive callbackRate
    if callback_rate is None:
        atr_val = _atr(client, symbol, interval=interval) or 0.0
        if atr_val <= 0 or not atr_mult:
            # Fallback fixed: 0.8% for top10, 1.2% others (like env defaults)
            callback_rate = float(os.getenv("TRAIL_CALLBACK_MIN_PCT", "0.1"))
            try:
                # clamp between min/max
                cb_min = float(os.getenv("TRAIL_CALLBACK_MIN_PCT", "0.1"))
                cb_max = float(os.getenv("TRAIL_CALLBACK_MAX_PCT", "4.9"))
                callback_rate = max(cb_min, min(cb_max, float(os.getenv("TRAIL_CALLBACK_MIN_PCT", "0.1"))))
            except Exception:
                callback_rate = 0.8
        else:
            # percent of price based on ATR*mult
            pct = (atr_val * float(atr_mult)) / last * 100.0
            cb_min = float(os.getenv("TRAIL_CALLBACK_MIN_PCT", "0.1"))
            cb_max = float(os.getenv("TRAIL_CALLBACK_MAX_PCT", "4.9"))
            callback_rate = max(cb_min, min(cb_max, pct))

    opp_side = "SELL" if side == "BUY" else "BUY"
    order = client.futures_create_order(
        symbol=symbol,
        side=opp_side,
        type="TRAILING_STOP_MARKET",
        callbackRate=float(callback_rate),
        activationPrice=None,
        reduceOnly="true",
        newClientOrderId=build_client_order_id(symbol, opp_side, role="TRAIL"),
        workingType=os.getenv("BINANCE_WORKING_TYPE", "MARK_PRICE"),
    )
    return {"ok": True, "symbol": symbol, "side": side, "qty": abs_qty, "entry": entry, "callback_rate": float(callback_rate), "order": order}

# =========================
# Move SL to a specific price
# =========================
@router.post("/sl/move", summary="Move SL to a specific price (STOP_MARKET closePosition)")
async def sl_move(payload: Dict[str, Any] = Body(...)):
    symbol = (payload.get("symbol") or "").upper()
    price = payload.get("price")
    if not symbol or price is None:
        raise HTTPException(status_code=422, detail="symbol, price required")
    price = float(price)

    client = _get_client()
    _align_position_mode(client)
    side, abs_qty, entry = _fetch_position_side_qty_entry(client, symbol)

    _cancel_all_sl(client, symbol)

    opp_side = "SELL" if side == "BUY" else "BUY"
    order = client.futures_create_order(
        symbol=symbol,
        side=opp_side,
        type="STOP_MARKET",
        stopPrice=price,
        closePosition=True,
        reduceOnly="true",
        newClientOrderId=build_client_order_id(symbol, opp_side, role="SL"),
        workingType=os.getenv("BINANCE_WORKING_TYPE", "MARK_PRICE"),
    )
    return {"ok": True, "symbol": symbol, "side": side, "qty": abs_qty, "entry": entry, "sl_price": price, "order": order}

# =========================
# TP Ladder create/refresh
# pcts: [1.8,3.2,5.5]  splits: [0.40,0.35,0.25]
# =========================
@router.post("/tp/ladder", summary="Create/refresh TP ladder as TAKE_PROFIT_MARKET reduce-only")
async def tp_ladder(payload: Dict[str, Any] = Body(...)):
    symbol = (payload.get("symbol") or "").upper()
    pcts: List[float] = payload.get("pcts") or [float(x) for x in (os.getenv("LADDER_TP_DEFAULT_PCTS", "1.8,3.2,5.5").split(","))]
    splits: List[float] = payload.get("splits") or [float(x) for x in (os.getenv("LADDER_TP_DEFAULT_SPLITS", "0.4,0.35,0.25").split(","))]
    if not symbol:
        raise HTTPException(status_code=422, detail="symbol required")
    if not pcts or not splits or len(pcts) != len(splits):
        raise HTTPException(status_code=422, detail="pcts and splits must be same length")

    client = _get_client()
    _align_position_mode(client)
    side, abs_qty, entry = _fetch_position_side_qty_entry(client, symbol)

    # Cancel existing TP orders
    _cancel_all_tp(client, symbol)

    opp_side = "SELL" if side == "BUY" else "BUY"
    total = 0.0
    placed = []
    for i, (pct, split) in enumerate(zip(pcts, splits), start=1):
        q = abs_qty * float(split)
        if q <= 0:
            continue
        if side == "BUY":
            trig = entry * (1.0 + float(pct) / 100.0)
        else:
            trig = entry * (1.0 - float(pct) / 100.0)

        order = client.futures_create_order(
            symbol=symbol,
            side=opp_side,
            type="TAKE_PROFIT_MARKET",
            stopPrice=trig,
            reduceOnly="true",
            timeInForce="GTC",
            newClientOrderId=build_client_order_id(symbol, opp_side, role=f"TP{i}"),
            workingType=os.getenv("BINANCE_WORKING_TYPE", "MARK_PRICE"),
            quantity=q,
        )
        placed.append({"i": i, "pct": float(pct), "split": float(split), "qty": q, "stop": trig, "orderId": order.get("orderId")})
        total += q
    return {"ok": True, "symbol": symbol, "side": side, "qty": abs_qty, "entry": entry, "qty_scheduled": total, "placed": placed}

@router.post("/tp/cancel", summary="Cancel all TP orders for the position")
async def tp_cancel(payload: Dict[str, Any] = Body(...)):
    symbol = (payload.get("symbol") or "").upper()
    if not symbol:
        raise HTTPException(status_code=422, detail="symbol required")
    client = _get_client()
    _align_position_mode(client)
    n = _cancel_all_tp(client, symbol)
    return {"ok": True, "symbol": symbol, "cancelled": n}

# =========================
# Partial / Full close
# =========================
@router.post("/close", summary="Close fraction of the position (reduce-only market)")
async def close_fraction(payload: Dict[str, Any] = Body(...)):
    symbol = (payload.get("symbol") or "").upper()
    fraction = float(payload.get("fraction") or 1.0)
    fraction = max(0.0, min(1.0, fraction))
    if not symbol:
        raise HTTPException(status_code=422, detail="symbol required")
    client = _get_client()
    _align_position_mode(client)
    side, _, _ = _fetch_position_side_qty_entry(client, symbol)
    res = await _close_position(symbol, side, fraction=fraction, leverage=None, position_side="BOTH")
    return {"ok": bool(res.get("ok")), "result": res}

# =========================
# Reverse (close-all + open opposite with same qty)
# =========================
@router.post("/reverse", summary="Reverse position: close-all, then open opposite with qty (MARKET)")
async def reverse(payload: Dict[str, Any] = Body(...)):
    symbol = (payload.get("symbol") or "").upper()
    if not symbol:
        raise HTTPException(status_code=422, detail="symbol required")
    client = _get_client()
    _align_position_mode(client)
    side, abs_qty, _ = _fetch_position_side_qty_entry(client, symbol)

    # close all
    close_res = await _close_position(symbol, side, fraction=1.0, leverage=None, position_side="BOTH")
    if not bool(close_res.get("ok")):
        return {"ok": False, "step": "close", "result": close_res}

    opp_side = "SELL" if side == "BUY" else "BUY"
    order = client.futures_create_order(
        symbol=symbol,
        side=opp_side,
        type="MARKET",
        quantity=abs_qty,
        reduceOnly="false",
        newClientOrderId=build_client_order_id(symbol, opp_side, role="ENTRY"),
    )
    return {"ok": True, "close": close_res, "open": order}

# =========================
# Manage-once (run: be + trail + tp ladder)
# =========================
@router.post("/manage-once", summary="One-shot smart manage: BE + TRAIL + TP ladder")
async def manage_once(payload: Dict[str, Any] = Body(...)):
    symbol = (payload.get("symbol") or "").upper()
    do = payload.get("do") or ["be", "trail", "tp_ladder"]
    offset_bps = int(payload.get("offset_bps") or os.getenv("TP_BE_OFFSET_BPS") or 8)
    atr_mult = payload.get("atr_mult", 1.5)
    pcts = payload.get("pcts")
    splits = payload.get("splits")
    if not symbol:
        raise HTTPException(status_code=422, detail="symbol required")

    res: Dict[str, Any] = {"symbol": symbol, "ok": True, "steps": {}}

    if "be" in do:
        try:
            r = await be({"symbol": symbol, "offset_bps": offset_bps, "force": True})
            res["steps"]["be"] = r
            res["ok"] = res["ok"] and bool(r.get("ok"))
        except Exception as e:
            res["steps"]["be"] = {"ok": False, "error": str(e)}
            res["ok"] = False

    if "trail" in do:
        try:
            r = await trail({"symbol": symbol, "atr_mult": atr_mult})
            res["steps"]["trail"] = r
            res["ok"] = res["ok"] and bool(r.get("ok"))
        except Exception as e:
            res["steps"]["trail"] = {"ok": False, "error": str(e)}
            res["ok"] = False

    if "tp_ladder" in do:
        try:
            body = {"symbol": symbol}
            if pcts is not None: body["pcts"] = pcts
            if splits is not None: body["splits"] = splits
            r = await tp_ladder(body)
            res["steps"]["tp_ladder"] = r
            res["ok"] = res["ok"] and bool(r.get("ok"))
        except Exception as e:
            res["steps"]["tp_ladder"] = {"ok": False, "error": str(e)}
            res["ok"] = False

    return res



