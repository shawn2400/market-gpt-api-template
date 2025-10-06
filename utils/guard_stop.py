# utils/guard_stop.py
from __future__ import annotations

import os
import time
import math
from typing import Any, Dict, List, Optional, Tuple
from contextlib import suppress

try:
    from binance.client import Client  # type: ignore
except Exception:
    Client = None  # type: ignore

# קונפיג
ORDER_ID_PREFIX = (os.getenv("ORDER_ID_PREFIX") or "ALG").strip() or "ALG"
BINANCE_WORKING_TYPE = os.getenv("BINANCE_WORKING_TYPE", "MARK_PRICE")
DEFAULT_TICK = float(os.getenv("DEFAULT_PRICE_TICK", "0.01"))
DEFAULT_QTY_STEP = float(os.getenv("DEFAULT_QTY_STEP", "0.001"))

GUARD_ENABLE = os.getenv("GUARD_ENABLE", "1").lower() in ("1","true","yes","on")
GUARD_ENSURE_AFTER_OPS = os.getenv("GUARD_ENSURE_AFTER_OPS", "1").lower() in ("1","true","yes","on")
GUARD_VERIFY_SLEEP_SEC = float(os.getenv("GUARD_VERIFY_SLEEP_SEC", "0.15"))
GUARD_VERIFY_TRIES = int(os.getenv("GUARD_VERIFY_TRIES", "6"))

BE_OFFSET_BPS = float(os.getenv("TP_BE_OFFSET_BPS", "8"))
TRAIL_ATR_MULT = float(os.getenv("SMART_MANAGE_TRAIL_ATR_MULT", "1.5") or "0")
TP1_TAGS = [t.strip().upper() for t in (os.getenv("TP1_TAGS", "TP1,tp1,tp_1,TAKE_PROFIT_1").split(","))]

# כימות (נשתמש ב-quantize אם זמין)
with suppress(Exception):
    from utils.quantize import get_filters as _gf, quantize_price as _qp, quantize_qty as _qq  # type: ignore

def _client() -> Client:
    if Client is None:
        raise RuntimeError("binance client not available")
    api_key = os.getenv("BINANCE_API_KEY", "").strip()
    api_sec = os.getenv("BINANCE_API_SECRET", "").strip()
    if not api_key or not api_sec:
        raise RuntimeError("BINANCE keys missing")
    return Client(api_key, api_sec)

def _align_position_mode(client) -> None:
    mode = (os.getenv("POSITION_MODE_OVERRIDE","") or "").strip().lower()
    with suppress(Exception):
        if mode in ("hedge","dual","dual_side","dual_side_position","dualposition"):
            client.futures_change_position_mode(dualSidePosition="true")
        elif mode in ("oneway","one_way","single","single_side","oneside"):
            client.futures_change_position_mode(dualSidePosition="false")

def _filters(client, symbol: str) -> Dict[str, Any]:
    if "_gf" in globals():
        with suppress(Exception):
            return _gf(client, symbol)
    try:
        ex = client.futures_exchange_info() or {}
        for s in ex.get("symbols", []):
            if str(s.get("symbol","")).upper() == symbol.upper():
                tick = 0.0; step = 0.0
                for f in s.get("filters", []):
                    if f.get("filterType") == "PRICE_FILTER":
                        tick = float(f.get("tickSize") or 0.0)
                    if f.get("filterType") == "LOT_SIZE":
                        step = float(f.get("stepSize") or 0.0)
                return {"price_tick": tick or DEFAULT_TICK, "qty_step": step or DEFAULT_QTY_STEP}
    except Exception:
        pass
    return {"price_tick": DEFAULT_TICK, "qty_step": DEFAULT_QTY_STEP}

def _q_price(symbol: str, price: float, flt: Dict[str, Any]) -> float:
    if "_qp" in globals():
        with suppress(Exception):
            return _qp(symbol, price, flt)
    tick = float(flt.get("price_tick") or DEFAULT_TICK)
    if tick <= 0: return round(price, 8)
    steps = math.floor(price / tick + 1e-12)
    return round(max(tick, steps * tick), 8)

def _q_qty(symbol: str, qty: float, flt: Dict[str, Any]) -> float:
    if "_qq" in globals():
        with suppress(Exception):
            return _qq(symbol, qty, flt)
    step = float(flt.get("qty_step") or DEFAULT_QTY_STEP)
    if step <= 0: return round(qty, 8)
    steps = math.floor(qty / step + 1e-12)
    return round(max(step, steps * step), 8)

def _build_coid(symbol: str, side: str, role: str, extra: Optional[str] = None) -> str:
    base = f"{ORDER_ID_PREFIX}_{symbol.upper()}_{side.upper()}_{role.upper()}_{int(time.time())}"
    if extra: base += f"_{extra}"
    if len(base) <= 32:
        return base
    return base[:24] + "_" + str(abs(hash(base)))[:7]

def _get_active_orders(client, symbol: str) -> Tuple[List[Dict[str, Any]], Optional[str], float, float, float]:
    sym = symbol.upper()
    orders = client.futures_get_open_orders(symbol=sym) or []
    infos = client.futures_position_information(symbol=sym) or []
    if not infos:
        return orders, None, 0.0, 0.0, 0.0
    pos = infos[0]
    qty = float(pos.get("positionAmt") or 0.0)
    entry = float(pos.get("entryPrice") or 0.0)
    side = "BUY" if qty > 0 else ("SELL" if qty < 0 else None)

    mark = 0.0
    with suppress(Exception):
        mp = client.futures_mark_price(symbol=sym) or {}
        mark = float(mp.get("markPrice") or 0.0)
    return orders, side, abs(qty), entry, mark

def _tp1_was_hit(client, symbol: str) -> bool:
    try:
        arr = client.futures_get_all_orders(symbol=symbol.upper(), limit=120) or []
        for o in arr:
            st = (o.get("status") or "").upper()
            typ = (o.get("type") or "").upper()
            cid = ((o.get("clientOrderId") or "") + " " + (o.get("origClientOrderId") or "")).upper()
            if st == "FILLED" and "TAKE_PROFIT" in typ:
                if "TP1" in cid or any(t for t in TP1_TAGS if t and t in cid):
                    return True
    except Exception:
        pass
    return False

def _atr_now(client, symbol: str, interval: str = "1m", period: int = 14) -> float:
    with suppress(Exception):
        kl = client.futures_klines(symbol=symbol.upper(), interval=interval, limit=period + 2) or []
        if len(kl) < period + 1:
            return 0.0
        trs: List[float] = []
        for i in range(1, len(kl)):
            h = float(kl[i][2]); l = float(kl[i][3]); pc = float(kl[i-1][4])
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        if len(trs) < period:
            return 0.0
        return sum(trs[-period:]) / float(period)
    return 0.0

def _verify_working(client, symbol: str, new_id: int) -> bool:
    tries = GUARD_VERIFY_TRIES
    while tries > 0:
        with suppress(Exception):
            od = client.futures_get_order(symbol=symbol.upper(), orderId=new_id) or {}
            st = (od.get("status") or "").upper()
            if st in ("NEW","PARTIALLY_FILLED"):
                return True
        time.sleep(GUARD_VERIFY_SLEEP_SEC)
        tries -= 1
    return False

def _cancel_old_stops(client, symbol: str, keep_order_id: int) -> int:
    n = 0
    for o in client.futures_get_open_orders(symbol=symbol.upper()) or []:
        if int(o.get("orderId") or 0) == int(keep_order_id):
            continue
        typ = (o.get("type") or "").upper()
        if "STOP" in typ:
            with suppress(Exception):
                client.futures_cancel_order(symbol=symbol.upper(), orderId=o["orderId"])
                n += 1
    return n

def _place_or_replace_stop_atomic(
    client,
    symbol: str,
    *,
    side_close: str,
    stop_price: float,
    qty: float,
    mode_native: bool,
    position_side: str,
) -> Dict[str, Any]:
    sym = symbol.upper()
    flt = _filters(client, sym)
    px = _q_price(sym, stop_price, flt)

    if mode_native:
        new = client.futures_create_order(
            symbol=sym,
            side=side_close,
            type="STOP_MARKET",
            stopPrice=px,
            closePosition=True,
            workingType=BINANCE_WORKING_TYPE,
            newClientOrderId=_build_coid(sym, side_close, "SL", "ALGOGPT"),
        )
    else:
        q = _q_qty(sym, qty, flt)
        if q <= 0:
            raise RuntimeError("guard_stop: qty rounds to zero")
        new = client.futures_create_order(
            symbol=sym,
            side=side_close,
            type="STOP_MARKET",
            stopPrice=px,
            quantity=q,
            reduceOnly=True,
            workingType=BINANCE_WORKING_TYPE,
            newClientOrderId=_build_coid(sym, side_close, "SL", "ALGOGPT"),
            positionSide=position_side,
        )

    new_id = int(new.get("orderId") or 0)
    ok = _verify_working(client, sym, new_id)
    if not ok:
        return {"ok": False, "placed": new, "verified": False, "cancelled_old": 0}
    cancelled = _cancel_old_stops(client, sym, keep_order_id=new_id)
    return {"ok": True, "placed": new, "verified": True, "cancelled_old": cancelled}

def ensure_protective_stop(
    symbol: str,
    *,
    prefer_mode: str = "native",   # "native" | "quantities"
    be_buffer_bps: Optional[float] = None,
    atr_mult: Optional[float] = None,
) -> Dict[str, Any]:
    if not GUARD_ENABLE:
        return {"ok": True, "skipped": True, "reason": "GUARD_ENABLE=0"}

    cli = _client()
    _align_position_mode(cli)

    orders, pos_side, qty_abs, entry, mark = _get_active_orders(cli, symbol)
    if not pos_side or not (qty_abs and qty_abs > 0) or not (entry and entry > 0):
        return {"ok": False, "reason": "no_open_position"}

    side_close = "SELL" if pos_side == "BUY" else "BUY"
    be_bps = float(BE_OFFSET_BPS if be_buffer_bps is None else be_buffer_bps)

    prev_sl = None
    for o in orders:
        typ = (o.get("type") or "").upper()
        if "STOP" not in typ:
            continue
        sp = float(o.get("stopPrice") or o.get("price") or 0.0)
        if sp <= 0:
            continue
        if prev_sl is None:
            prev_sl = sp
        else:
            if pos_side == "BUY":
                prev_sl = max(prev_sl, sp)
            else:
                prev_sl = min(prev_sl, sp)

    tp1_hit = _tp1_was_hit(cli, symbol)

    atr_mult_eff = float(TRAIL_ATR_MULT if atr_mult is None else atr_mult) or 0.0
    atr_val = _atr_now(cli, symbol) if atr_mult_eff > 0 else 0.0
    trail_sl = None
    if atr_val and mark:
        if pos_side == "BUY":
            trail_sl = mark - atr_mult_eff * atr_val
        else:
            trail_sl = mark + atr_mult_eff * atr_val

    if tp1_hit:
        if pos_side == "BUY":
            be_px = entry * (1.0 + be_bps/10000.0)
            candidate = be_px
            if trail_sl: candidate = max(candidate, trail_sl)
            if prev_sl is not None: candidate = max(candidate, prev_sl)
        else:
            be_px = entry * (1.0 - be_bps/10000.0)
            candidate = be_px
            if trail_sl: candidate = min(candidate, trail_sl)
            if prev_sl is not None: candidate = min(candidate, prev_sl)
    else:
        candidate = trail_sl if trail_sl else (prev_sl if prev_sl is not None else (entry * (0.985 if pos_side == "BUY" else 1.015)))
        if prev_sl is not None:
            if pos_side == "BUY": candidate = max(candidate, prev_sl)
            else:                 candidate = min(candidate, prev_sl)

    mode_native = (prefer_mode.lower() == "native")

    if prev_sl is None:
        emergency_target = candidate
        placed = _place_or_replace_stop_atomic(
            cli, symbol,
            side_close=side_close,
            stop_price=emergency_target,
            qty=qty_abs,
            mode_native=mode_native,
            position_side="LONG" if pos_side == "BUY" else "SHORT",
        )
        return {"ok": bool(placed.get("ok")), "emergency_set": True, "detail": placed}

    eps = max(1e-8, 1e-6 * entry)
    if abs(candidate - prev_sl) <= eps:
        return {"ok": True, "skipped": True, "reason": "no_material_change", "prev_sl": prev_sl}

    placed = _place_or_replace_stop_atomic(
        cli, symbol,
        side_close=side_close,
        stop_price=candidate,
        qty=qty_abs,
        mode_native=mode_native,
        position_side="LONG" if pos_side == "BUY" else "SHORT",
    )
    return {
        "ok": bool(placed.get("ok")),
        "tp1_hit": tp1_hit,
        "entry": entry,
        "mark": mark,
        "prev_sl": prev_sl,
        "target_sl": candidate,
        "detail": placed,
    }
