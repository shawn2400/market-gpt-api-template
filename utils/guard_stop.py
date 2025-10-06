# utils/guard_stop.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import logging
from contextlib import suppress
from typing import Dict, Any, Optional, List

from utils.binance_client import (
    get_all_orders, futures_create_order, futures_cancel_order, get_futures_client,
)
from utils.trade_execution_core import (
    _q_price, _q_qty, _effective_position_side, _close_side_for, _offset_bps,
    STOP_BAND_BPS, ORDER_ID_PREFIX,
)

log = logging.getLogger("algogpt.guard_stop")

def _position_snapshot(sym: str) -> Dict[str, Any]:
    """מצב פוזיציה מה־Futures. מחזיר side ('BUY'/'SELL'/None), qty>0, entry_price>0 אם קיימת."""
    cli = get_futures_client()
    info = cli.futures_position_information(symbol=sym.upper())
    if not info:
        return {"has_position": False}
    best = None
    for row in info:
        try:
            amt = float(row.get("positionAmt") or 0.0)
            if best is None or abs(amt) > abs(float(best.get("positionAmt") or 0.0)):
                best = row
        except Exception:
            continue
    if not best:
        return {"has_position": False}
    amt = float(best.get("positionAmt") or 0.0)
    if abs(amt) < 1e-12:
        return {"has_position": False}
    entry = float(best.get("entryPrice") or 0.0)
    side = "BUY" if amt > 0 else "SELL"
    return {"has_position": True, "side": side, "qty": abs(amt), "entry_price": entry}

def _has_open_stop(sym: str) -> bool:
    """בודק אם כבר יש STOP/TRAIL פתוח רלוונטי (NEW / PARTIALLY_FILLED)."""
    try:
        lst = get_all_orders(sym, limit=50) or []
        for o in lst:
            st  = (o.get("status") or "").upper()
            typ = (o.get("type") or "").upper()
            if st in ("NEW", "PARTIALLY_FILLED") and typ.startswith(("STOP", "TRAILING_STOP")):
                return True
    except Exception:
        pass
    return False

def _cancel_open_stops(sym: str) -> int:
    """מבטל כל STOP/TRAILING_STOP פתוחים (לפי צורך)."""
    cnt = 0
    try:
        lst = get_all_orders(sym, limit=50) or []
        for o in lst:
            st  = (o.get("status") or "").upper()
            typ = (o.get("type") or "").upper()
            if st in ("NEW","PARTIALLY_FILLED") and typ.startswith(("STOP", "TRAILING_STOP")):
                with suppress(Exception):
                    futures_cancel_order(sym, o["orderId"])
                    cnt += 1
    except Exception as e:
        log.warning("cancel_open_stops_failed(%s): %s", sym, e)
    return cnt

def ensure_protective_stop(symbol: str, *, prefer_mode: str = "quantities", be_offset_bps: float = 6.0) -> Dict[str, Any]:
    """
    מאבטח SL מיידי לפי הפוזיציה הקיימת.
    prefer_mode:
      - "quantities": מגדיר כמות לפי positionAmt בפועל.
      - "flat": אם לא מוצא פוזיציה/כמות – לא עושה כלום (שקט).
    be_offset_bps: מיקום SL סביב מחיר כניסה (BE±offset).
    """
    sym = symbol.upper().strip()
    snap = _position_snapshot(sym)
    if not snap.get("has_position"):
        return {"ok": True, "skipped": True, "reason": "no_position"}

    side: str = snap["side"]  # BUY/SELL של הכניסה
    qty: float = float(snap["qty"])
    entry_px: float = float(snap.get("entry_price") or 0.0)

    if qty <= 0:
        return {"ok": True, "skipped": True, "reason": "zero_qty"}

    # אם כבר יש STOP פתוח — לא נוגעים (מניעת כפילות).
    if _has_open_stop(sym):
        return {"ok": True, "skipped": True, "reason": "existing_stop"}

    close_side = _close_side_for(side)
    if entry_px and entry_px > 0:
        be_px = _offset_bps(entry_px, (+be_offset_bps if side=="BUY" else -be_offset_bps), +1)
    else:
        be_px = _offset_bps(1.0, (-STOP_BAND_BPS if side=="BUY" else +STOP_BAND_BPS), +1)

    stop_str, _ = _q_price(sym, float(be_px))
    qty_str, _  = _q_qty(sym, float(qty))

    args: Dict[str, Any] = dict(
        symbol=sym,
        side=close_side,
        type="STOP_MARKET",
        workingType="MARK_PRICE",
        stopPrice=stop_str,
        quantity=qty_str,
        reduceOnly=True,
        newClientOrderId=f"{(ORDER_ID_PREFIX or 'ALG').strip()}_SL_PROTECT_{sym}_{close_side}",
    )

    eff_ps = _effective_position_side("LONG" if side=="SELL" else "SHORT")
    if eff_ps != "BOTH":
        args["positionSide"] = eff_ps

    try:
        resp = futures_create_order(**args)
        return {"ok": True, "response": resp, "placed": True, "qty": float(qty), "stop": stop_str}
    except Exception as e:
        msg = str(e).lower()
        if "reduce only" in msg or "reduceonly" in msg or "-1106" in msg:
            args2 = dict(args); args2.pop("reduceOnly", None)
            with suppress(Exception):
                resp2 = futures_create_order(**args2)
                return {"ok": True, "response": resp2, "placed": True, "qty": float(qty), "stop": stop_str, "ro_fallback": True}
        log.warning("ensure_protective_stop.failed(%s): %s", sym, e)
        return {"ok": False, "error": str(e)}


