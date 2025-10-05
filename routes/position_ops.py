# routes/position_ops.py
from __future__ import annotations

import os
import time
import math
import hashlib
import logging
from typing import Any, Dict, List, Optional, Tuple
from contextlib import suppress

from fastapi import APIRouter, Body, HTTPException

logger = logging.getLogger("algogpt.position_ops")
router = APIRouter(prefix="/position-ops", tags=["position-ops"])

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
# clientOrderId (<=32 chars)
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
# Exchange filters & rounding
# =========================
_FILTERS: Dict[str, Dict[str, float]] = {}

def _filters(symbol: str) -> Dict[str, float]:
    s = symbol.upper()
    if s in _FILTERS:
        return _FILTERS[s]
    cli = _get_client()
    info = cli.futures_exchange_info()
    tick = float(os.getenv("DEFAULT_PRICE_TICK", "0.01"))
    step = float(os.getenv("DEFAULT_QTY_STEP", "0.001"))
    for sym in info.get("symbols", []):
        if sym.get("symbol") == s:
            for f in sym.get("filters", []):
                if f.get("filterType") == "PRICE_FILTER":
                    tick = float(f.get("tickSize", tick))
                elif f.get("filterType") == "LOT_SIZE":
                    step = float(f.get("stepSize", step))
            break
    _FILTERS[s] = {"tick": tick, "step": step}
    return _FILTERS[s]

def _round_price(symbol: str, px: float) -> float:
    tick = _filters(symbol)["tick"]
    return math.floor(float(px) / tick) * tick

def _round_qty(symbol: str, qty: float) -> float:
    step = _filters(symbol)["step"]
    q = math.floor(float(qty) / step) * step
    return float(f"{q:.12f}")

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
# BE: STOP_MARKET closePosition (בלי reduceOnly/quantity)
# =========================
@router.post("/be", summary="Move SL to BE ± offset_bps (STOP_MARKET closePosition)")
def be(payload: Dict[str, Any] = Body(...)):
    symbol = (payload.get("symbol") or "").upper()
    offset_bps = int(payload.get("offset_bps") or os.getenv("TP_BE_OFFSET_BPS") or 8)
    if not symbol:
        raise HTTPException(status_code=422, detail="symbol required")

    client = _get_client()
    _align_position_mode(client)
    side, abs_qty, entry = _fetch_position_side_qty_entry(client, symbol)

    # מחשב מחיר BE מעוגל
    if side == "BUY":
        be_px = _round_price(symbol, entry * (1 + offset_bps/10000.0))
        opp = "SELL"
    else:
        be_px = _round_price(symbol, entry * (1 - offset_bps/10000.0))
        opp = "BUY"

    # מבטל SL/Trail ישנים
    _cancel_open_conditional(client, symbol, kinds=("STOP", "TRAILING_STOP_MARKET"))

    order = client.futures_create_order(
        symbol=symbol,
        side=opp,
        type="STOP_MARKET",
        stopPrice=be_px,
        closePosition=True,               # ❗ אין reduceOnly/quantity
        workingType=os.getenv("BINANCE_WORKING_TYPE", "MARK_PRICE"),
        newClientOrderId=build_client_order_id(symbol, opp, role="BE"),
    )
    return {"ok": True, "symbol": symbol, "pos_side": side, "qty": abs_qty, "entry": entry, "be_price": be_px, "orderId": order.get("orderId")}

# =========================
# Trail: TRAILING_STOP_MARKET closePosition (בלי reduceOnly/quantity)
# =========================
@router.post("/trail", summary="Enable/refresh trailing SL (TRAILING_STOP_MARKET closePosition)")
def trail(payload: Dict[str, Any] = Body(...)):
    symbol = (payload.get("symbol") or "").upper()
    cb = payload.get("callbackRate") or payload.get("callback_rate") or payload.get("callback_rate_pct")
    atr_mult = payload.get("atr_mult")
    if not symbol:
        raise HTTPException(status_code=422, detail="symbol required")

    cb_min = float(os.getenv("TRAIL_CALLBACK_MIN_PCT", "0.1"))
    cb_max = float(os.getenv("TRAIL_CALLBACK_MAX_PCT", "4.9"))

    client = _get_client()
    _align_position_mode(client)
    side, abs_qty, entry = _fetch_position_side_qty_entry(client, symbol)
    last = _last_price(symbol)

    if cb is None:
        # חישוב גס אם לא נמסר: 1.0% או לפי ATR*mult אם נדרש (פשטות)
        try:
            if atr_mult:
                # פשט: הופך ATR*mult לאחוז מהמחיר – למנוע חריגות נצמד ל-min/max
                from math import fabs
                # ATR מהיר (14/1m) – אופציונלי; אם אין, נ fallback
                with suppress(Exception):
                    kl = client.futures_klines(symbol=symbol, interval="1m", limit=16)
                    trs = []
                    for i in range(1, len(kl)):
                        h = float(kl[i][2]); l = float(kl[i][3]); pc = float(kl[i-1][4])
                        trs.append(max(h-l, fabs(h-pc), fabs(l-pc)))
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

    # מבטל SL/Trail ישנים
    _cancel_open_conditional(client, symbol, kinds=("STOP", "TRAILING_STOP_MARKET"))

    order = client.futures_create_order(
        symbol=symbol,
        side=opp,
        type="TRAILING_STOP_MARKET",
        callbackRate=float(cb),
        closePosition=True,               # ❗ אין reduceOnly/quantity
        newClientOrderId=build_client_order_id(symbol, opp, role="TRAIL"),
        workingType=os.getenv("BINANCE_WORKING_TYPE", "MARK_PRICE"),
    )
    return {"ok": True, "symbol": symbol, "pos_side": side, "qty": abs_qty, "entry": entry, "callbackRate": float(cb), "orderId": order.get("orderId")}

# =========================
# SL למיקום ספציפי (STOP_MARKET closePosition)
# =========================
@router.post("/sl/move", summary="Move SL to a specific price (STOP_MARKET closePosition)")
def sl_move(payload: Dict[str, Any] = Body(...)):
    symbol = (payload.get("symbol") or "").upper()
    price = float(payload.get("price") or 0)
    if not symbol or price <= 0:
        raise HTTPException(status_code=422, detail="symbol, price required")

    client = _get_client()
    _align_position_mode(client)
    side, abs_qty, entry = _fetch_position_side_qty_entry(client, symbol)
    opp = "SELL" if side == "BUY" else "BUY"
    px = _round_price(symbol, price)

    _cancel_open_conditional(client, symbol, kinds=("STOP", "TRAILING_STOP_MARKET"))

    order = client.futures_create_order(
        symbol=symbol,
        side=opp,
        type="STOP_MARKET",
        stopPrice=px,
        closePosition=True,               # ❗ אין reduceOnly/quantity
        newClientOrderId=build_client_order_id(symbol, opp, role="SL"),
        workingType=os.getenv("BINANCE_WORKING_TYPE", "MARK_PRICE"),
    )
    return {"ok": True, "symbol": symbol, "pos_side": side, "qty": abs_qty, "entry": entry, "sl_price": px, "orderId": order.get("orderId")}

# =========================
# TP Ladder – partial reduce-only, עם עיגול כמות/מחיר
# =========================
@router.post("/tp/ladder", summary="Create/refresh TP ladder (TAKE_PROFIT_MARKET reduce-only partials)")
def tp_ladder(payload: Dict[str, Any] = Body(...)):
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
    last = _last_price(symbol)

    opp = "SELL" if side == "BUY" else "BUY"

    # מנקה רק TP קיימים לפני בנייה
    for o in client.futures_get_open_orders(symbol=symbol.upper()) or []:
        typ = (o.get("type") or "").upper()
        if "TAKE_PROFIT" in typ:
            with suppress(Exception):
                client.futures_cancel_order(symbol=symbol.upper(), orderId=o["orderId"])

    placed = []
    for i, (pct, split) in enumerate(zip(pcts, splits), start=1):
        q_raw = abs_qty * float(split)
        q = _round_qty(symbol, q_raw)
        if q <= 0:
            continue

        # יעד לפי המחיר הנוכחי (אפשר לשנות ל-entry אם מעדיף)
        if side == "BUY":
            trig = _round_price(symbol, last * (1.0 + float(pct)/100.0))
        else:
            trig = _round_price(symbol, last * (1.0 - float(pct)/100.0))

        order = client.futures_create_order(
            symbol=symbol,
            side=opp,
            type="TAKE_PROFIT_MARKET",
            stopPrice=trig,
            quantity=q,                    # ❗ partial qty (מעוגל)
            reduceOnly=True,
            timeInForce="GTC",
            newClientOrderId=build_client_order_id(symbol, opp, role=f"TP{i}"),
            workingType=os.getenv("BINANCE_WORKING_TYPE", "MARK_PRICE"),
        )
        placed.append({"i": i, "pct": float(pct), "split": float(split), "qty": q, "stop": trig, "orderId": order.get("orderId")})

    return {"ok": True, "symbol": symbol, "side": side, "qty": abs_qty, "entry": entry, "built": len(placed), "orders": placed}

# =========================
# ביטול כל ה-TP
# =========================
@router.post("/tp/cancel", summary="Cancel all TP orders")
def tp_cancel(payload: Dict[str, Any] = Body(...)):
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
    return {"ok": True, "symbol": symbol, "cancelled": n}

# =========================
# Close fraction – reduce-only market (אופציונלי)
# =========================
@router.post("/close", summary="Close fraction of the position (reduce-only MARKET)")
def close_fraction(payload: Dict[str, Any] = Body(...)):
    symbol = (payload.get("symbol") or "").upper()
    fraction = float(payload.get("fraction") or 1.0)
    fraction = max(0.0, min(1.0, fraction))
    if not symbol:
        raise HTTPException(status_code=422, detail="symbol required")

    client = _get_client()
    _align_position_mode(client)
    side, abs_qty, _ = _fetch_position_side_qty_entry(client, symbol)
    opp = "SELL" if side == "BUY" else "BUY"
    qty = _round_qty(symbol, abs_qty * fraction)
    if qty <= 0:
        return {"ok": False, "error": "qty_to_close_zero"}

    order = client.futures_create_order(
        symbol=symbol,
        side=opp,
        type="MARKET",
        quantity=qty,
        reduceOnly=True,
        newClientOrderId=build_client_order_id(symbol, opp, role="CLOSE"),
    )
    return {"ok": True, "symbol": symbol, "fraction": fraction, "qty_closed": qty, "orderId": order.get("orderId")}

# =========================
# ניהול חד-פעמי
# =========================
@router.post("/manage-once", summary="One-shot smart manage: BE + TRAIL + TP ladder")
def manage_once(payload: Dict[str, Any] = Body(...)):
    symbol = (payload.get("symbol") or "").upper()
    do = payload.get("do") or ["be", "trail", "tp_ladder"]
    offset_bps = int(payload.get("offset_bps") or os.getenv("TP_BE_OFFSET_BPS") or 8)
    callbackRate = payload.get("callbackRate")
    pcts = payload.get("pcts")
    splits = payload.get("splits")
    if not symbol:
        raise HTTPException(status_code=422, detail="symbol required")

    out: Dict[str, Any] = {"symbol": symbol, "ok": True, "steps": {}}

    try:
        if "be" in do:
            out["steps"]["be"] = be({"symbol": symbol, "offset_bps": offset_bps})
    except Exception as e:
        out["ok"] = False
        out["steps"]["be"] = {"ok": False, "error": str(e)}

    try:
        if "trail" in do:
            body = {"symbol": symbol}
            if callbackRate is not None:
                body["callbackRate"] = callbackRate
            out["steps"]["trail"] = trail(body)
    except Exception as e:
        out["ok"] = False
        out["steps"]["trail"] = {"ok": False, "error": str(e)}

    try:
        if "tp_ladder" in do:
            body = {"symbol": symbol}
            if pcts is not None: body["pcts"] = pcts
            if splits is not None: body["splits"] = splits
            out["steps"]["tp_ladder"] = tp_ladder(body)
    except Exception as e:
        out["ok"] = False
        out["steps"]["tp_ladder"] = {"ok": False, "error": str(e)}

    return out



