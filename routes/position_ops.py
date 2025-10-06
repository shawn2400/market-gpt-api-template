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

# אחיד: בנאי COID אחד לכל האפליקציה
with suppress(Exception):
    from utils.order_ids import build_client_order_id  # type: ignore

# כימות מדויק ל-price/qty לפי exchangeInfo (מונע -1111)
with suppress(Exception):
    from utils.quantize import get_filters, quantize_price, quantize_qty  # type: ignore

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
# TP/BE gating helpers
# =========================
def _tp1_filled(client, symbol: str) -> bool:
    """
    מזהה האם TP1 מולא בעבר הקרוב.
    חיפוש לפי clientOrderId שכולל TP1 / תגיות מהסביבה, ומצב FILLED.
    """
    tags = [t.strip().upper() for t in (os.getenv("TP1_TAGS","TP1,tp1,tp_1,TAKE_PROFIT_1").split(","))]
    try:
        orders = client.futures_get_all_orders(symbol=symbol.upper(), limit=100) or []
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
    """
    קובע אם לאפשר BE/Trail לפי:
    - SMART_MANAGE_AFTER_TP1=1 => דרוש TP1 מלא.
    - TRAIL_MIN_PROFIT_PCT=x => דרוש רווח מינימלי באחוזים מן הכניסה.
    """
    want_tp1 = (os.getenv("SMART_MANAGE_AFTER_TP1","0").lower() in ("1","true","yes","on"))
    min_profit = float(os.getenv("TRAIL_MIN_PROFIT_PCT","0") or 0)
    last = 0.0
    with suppress(Exception):
        last = _last_price(symbol)

    if want_tp1 and not _tp1_filled(client, symbol):
        return (False, "blocked_by_tp1_not_filled")
    if min_profit > 0 and not _profit_ok(entry, last, side, min_profit):
        return (False, "blocked_by_min_profit")
    return (True, "ok")

# =========================
# BE: STOP_MARKET closePosition (נשאר כמו שהוא, עובד טוב)
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

    # Gating (TP1 / min profit)
    ok, why = _gate_be_trail(client, symbol, side, entry)
    if not ok:
        return {"ok": False, "reason": why, "skipped": "be"}

    # מחיר BE מעוגל
    flt = get_filters(client, symbol)
    if side == "BUY":
        be_px = quantize_price(symbol, entry * (1 + offset_bps/10000.0), flt)
        opp = "SELL"
    else:
        be_px = quantize_price(symbol, entry * (1 - offset_bps/10000.0), flt)
        opp = "BUY"

    # מבטל SL/Trail ישנים
    _cancel_open_conditional(client, symbol, kinds=("STOP", "TRAILING_STOP_MARKET"))

    order = client.futures_create_order(
        symbol=symbol,
        side=opp,
        type="STOP_MARKET",
        stopPrice=be_px,
        closePosition=True,               # נשאר closePosition – זה עובד יציב ל-BE
        workingType=os.getenv("BINANCE_WORKING_TYPE", "MARK_PRICE"),
        newClientOrderId=build_client_order_id(symbol, opp, role="BE"),
    )
    return {"ok": True, "symbol": symbol, "pos_side": side, "qty": abs_qty, "entry": entry, "be_price": be_px, "orderId": order.get("orderId")}

# =========================
# Trail: TRAILING_STOP_MARKET עם quantity+reduceOnly (מתקן -4136)
# =========================
@router.post("/trail", summary="Enable/refresh trailing SL (TRAILING_STOP_MARKET reduceOnly quantity)")
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
    flt = get_filters(client, symbol)

    # Gating (TP1 / min profit)
    ok, why = _gate_be_trail(client, symbol, side, entry)
    if not ok:
        return {"ok": False, "reason": why, "skipped": "trail"}

    if cb is None:
        # חישוב גס אם לא נמסר
        try:
            if atr_mult:
                from math import fabs
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

    # כמות מלאה של הפוזיציה (מעוגל ל-step) – reduceOnly
    qty = quantize_qty(symbol, abs_qty, flt)
    if qty <= 0:
        raise HTTPException(status_code=409, detail="trail qty rounds to zero")

    order = client.futures_create_order(
        symbol=symbol,
        side=opp,
        type="TRAILING_STOP_MARKET",
        callbackRate=float(cb),
        quantity=qty,
        reduceOnly=True,
        newClientOrderId=build_client_order_id(symbol, opp, role="TRAIL"),
        workingType=os.getenv("BINANCE_WORKING_TYPE", "MARK_PRICE"),
    )
    return {"ok": True, "symbol": symbol, "pos_side": side, "qty": qty, "entry": entry, "callbackRate": float(cb), "orderId": order.get("orderId")}

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
    flt = get_filters(client, symbol)

    opp = "SELL" if side == "BUY" else "BUY"
    px = quantize_price(symbol, price, flt)

    _cancel_open_conditional(client, symbol, kinds=("STOP", "TRAILING_STOP_MARKET"))

    order = client.futures_create_order(
        symbol=symbol,
        side=opp,
        type="STOP_MARKET",
        stopPrice=px,
        closePosition=True,               # ל-SL ידני/BE זה יציב
        newClientOrderId=build_client_order_id(symbol, opp, role="SL"),
        workingType=os.getenv("BINANCE_WORKING_TYPE", "MARK_PRICE"),
    )
    return {"ok": True, "symbol": symbol, "pos_side": side, "qty": abs_qty, "entry": entry, "sl_price": px, "orderId": order.get("orderId")}

# =========================
# TP Ladder – partial reduce-only, עם כימות Decimal
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
    flt = get_filters(client, symbol)

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
        q = quantize_qty(symbol, q_raw, flt)
        if q <= 0:
            continue

        if side == "BUY":
            trig = quantize_price(symbol, last * (1.0 + float(pct)/100.0), flt)
        else:
            trig = quantize_price(symbol, last * (1.0 - float(pct)/100.0), flt)

        order = client.futures_create_order(
            symbol=symbol,
            side=opp,
            type="TAKE_PROFIT_MARKET",
            stopPrice=trig,
            quantity=q,
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

    flt = get_filters(client, symbol)
    qty = quantize_qty(symbol, abs_qty * fraction, flt)
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
    atr_mult = payload.get("atr_mult") or os.getenv("SMART_MANAGE_TRAIL_ATR_MULT")
    if not symbol:
        raise HTTPException(status_code=422, detail="symbol required")

    out: Dict[str, Any] = {"symbol": symbol, "ok": True, "steps": {}}

    client = _get_client()
    _align_position_mode(client)
    side, abs_qty, entry = _fetch_position_side_qty_entry(client, symbol)

    # Gating once for BE/TRAIL
    allow_be_trail, reason = _gate_be_trail(client, symbol, side, entry)

    try:
        if "be" in do and allow_be_trail:
            out["steps"]["be"] = be({"symbol": symbol, "offset_bps": offset_bps})
        elif "be" in do and not allow_be_trail:
            out["steps"]["be"] = {"ok": False, "reason": reason, "skipped": "be"}
    except Exception as e:
        out["ok"] = False
        out["steps"]["be"] = {"ok": False, "error": str(e)}

    try:
        if "trail" in do and allow_be_trail:
            body = {"symbol": symbol}
            if callbackRate is not None:
                body["callbackRate"] = callbackRate
            if atr_mult is not None:
                body["atr_mult"] = atr_mult
            out["steps"]["trail"] = trail(body)
        elif "trail" in do and not allow_be_trail:
            out["steps"]["trail"] = {"ok": False, "reason": reason, "skipped": "trail"}
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




