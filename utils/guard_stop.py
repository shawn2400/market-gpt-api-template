# utils/guard_stop.py
from __future__ import annotations

import os
import time
import math
from contextlib import suppress
from typing import Any, Dict, List, Tuple, Optional

# =========================
# Env flags (defaults are conservative)
# =========================
GUARD_ENSURE_SL           = (os.getenv("GUARD_ENSURE_SL", "1").lower() in ("1","true","yes","on"))
GUARD_SL_GRACE_SEC        = int(os.getenv("GUARD_SL_GRACE_SEC", "2"))
STRICT_MODE_SINGLE        = (os.getenv("STRICT_MODE_SINGLE","1").lower() in ("1","true","yes","on"))
USE_NATIVE_TP_SL          = (os.getenv("USE_NATIVE_TP_SL","0").lower() in ("1","true","yes","on"))
STOP_WORKING_TYPE         = (os.getenv("STOP_WORKING_TYPE") or os.getenv("BINANCE_WORKING_TYPE") or "MARK_PRICE")
HEALTH_TP_GRACE_SEC       = int(os.getenv("HEALTH_TP_GRACE_SEC","8"))
TP_BE_ONLY_AFTER_TP1      = (os.getenv("TP_BE_ONLY_AFTER_TP1","1").lower() in ("1","true","yes","on"))
SMART_MANAGE_AFTER_TP1    = (os.getenv("SMART_MANAGE_AFTER_TP1","1").lower() in ("1","true","yes","on"))
TRAIL_MIN_PROFIT_PCT      = float(os.getenv("TRAIL_MIN_PROFIT_PCT","0.7") or 0.0)
TP_BE_OFFSET_BPS          = int(os.getenv("TP_BE_OFFSET_BPS","8"))
ORDER_ROUND_TO_TICK       = (os.getenv("ORDER_ROUND_TO_TICK","1").lower() in ("1","true","yes","on"))
USE_EXCHANGE_FILTERS      = (os.getenv("USE_EXCHANGE_FILTERS","1").lower() in ("1","true","yes","on"))

# Behavior: quantities only (as per your config)
ENFORCE_QTY_BOUNDS        = (os.getenv("ENFORCE_QTY_BOUNDS","1").lower() in ("1","true","yes","on"))
ORD_ATOMIC_UPDATE         = (os.getenv("ORD_ATOMIC_UPDATE","1").lower() in ("1","true","yes","on"))

# =========================
# Client / helpers
# =========================
def _get_client():
    from binance.client import Client  # type: ignore
    api_key = (os.getenv("BINANCE_API_KEY") or "").strip()
    api_sec = (os.getenv("BINANCE_API_SECRET") or "").strip()
    if not api_key or not api_sec:
        raise RuntimeError("BINANCE keys missing")
    cli = Client(api_key, api_sec)
    # honor position mode override (oneway/hedge)
    with suppress(Exception):
        mode_override = (os.getenv("POSITION_MODE_OVERRIDE","") or "").strip().lower()
        if mode_override in ("hedge","dual","dual_side","dual_side_position","dualposition"):
            cli.futures_change_position_mode(dualSidePosition="true")
        elif mode_override in ("oneway","one_way","single","single_side","oneside"):
            cli.futures_change_position_mode(dualSidePosition="false")
    return cli

def _last_price(cli, symbol: str) -> float:
    p = cli.futures_symbol_ticker(symbol=symbol.upper())
    return float(p["price"])

def _tp1_filled(cli, symbol: str) -> bool:
    tags = [t.strip().upper() for t in (os.getenv("TP1_TAGS","TP1,tp1,tp_1,TAKE_PROFIT_1").split(","))]
    with suppress(Exception):
        orders = cli.futures_get_all_orders(symbol=symbol.upper(), limit=120) or []
        for o in orders:
            if (o.get("status") or "").upper() == "FILLED":
                typ = (o.get("type") or "").upper()
                cid = ((o.get("clientOrderId") or "") + " " + (o.get("origClientOrderId") or "")).upper()
                if "TAKE_PROFIT" in typ and ("TP1" in cid or any(t for t in tags if t and t in cid)):
                    return True
    return False

# =========================
# Quantization (use project utils if present)
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

def _quantize_price_local(symbol: str, price: float, flt: Dict[str, Any]) -> float:
    step = float(flt.get("price_tick", 0.0) or 0.0)
    return round(_round_step(price, step), 8) if (ORDER_ROUND_TO_TICK and step > 0) else round(price, 8)

def _quantize_qty_local(symbol: str, qty: float, flt: Dict[str, Any]) -> float:
    step = float(flt.get("qty_step", 0.0) or 0.0)
    return round(_round_step(qty, step), 8) if (ORDER_ROUND_TO_TICK and step > 0) else round(qty, 8)

def _get_filters(cli, symbol: str) -> Dict[str, Any]:
    if not USE_EXCHANGE_FILTERS:
        return _fallback_filters()
    with suppress(Exception):
        ex = cli.futures_exchange_info() or {}
        for s in ex.get("symbols", []):
            if str(s.get("symbol","")).upper() == symbol.upper():
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
    return _fallback_filters()

# If project-level utils exist, prefer them
with suppress(Exception):
    from utils.quantize import get_filters as _gf, quantize_price as _qp, quantize_qty as _qq  # type: ignore
    def _get_filters(cli, symbol: str) -> Dict[str, Any]:  # type: ignore
        return _gf(cli, symbol)
    def _quantize_price_local(symbol: str, price: float, flt: Dict[str, Any]) -> float:  # type: ignore
        return _qp(symbol, price, flt)
    def _quantize_qty_local(symbol: str, qty: float, flt: Dict[str, Any]) -> float:  # type: ignore
        return _qq(symbol, qty, flt)

# =========================
# Order IDs (use project builder if exists)
# =========================
def _coid_fit(s: str, limit: int = 32) -> str:
    return s if len(s) <= limit else s[: limit - 8] + "_" + str(abs(hash(s)))[:7]

def _build_client_order_id(symbol: str, side: str, role: str = "SL") -> str:
    prefix = (os.getenv("ORDER_ID_PREFIX") or "ALG").strip() or "ALG"
    sym = str(symbol).upper()
    side = str(side).upper()
    role = str(role).upper()
    ts = int(time.time())
    return _coid_fit(f"{prefix}_{sym}_{side}_{role}_{ts}", 32)

with suppress(Exception):
    from utils.order_ids import build_client_order_id as _builder  # type: ignore
    def _build_client_order_id(symbol: str, side: str, role: str = "SL") -> str:  # type: ignore
        return _builder(symbol, side, role)

# =========================
# Core
# =========================
def _position_side_qty_entry(cli, symbol: str) -> Tuple[str, float, float]:
    infos = cli.futures_position_information(symbol=symbol) or []
    if not infos:
        raise RuntimeError("No position information")
    pos = infos[0]
    qty = float(pos.get("positionAmt") or 0.0)
    ep  = float(pos.get("entryPrice") or 0.0)
    if abs(qty) < 1e-12:
        raise RuntimeError("No open position")
    side = "BUY" if qty > 0 else "SELL"
    return side, abs(qty), ep

def _collect_active_stops(cli, symbol: str, opp_side: str) -> List[Dict[str, Any]]:
    active = []
    for o in (cli.futures_get_open_orders(symbol=symbol.upper()) or []):
        typ = (o.get("type") or "").upper()
        st  = (o.get("status") or "").upper()
        sd  = (o.get("side") or "").upper()
        if st == "NEW" and sd == opp_side and ("STOP" in typ):
            active.append(o)
    return active

def _sum_stop_qty(active_stops: List[Dict[str,Any]]) -> float:
    total = 0.0
    for o in active_stops:
        q = float(o.get("origQty") or o.get("quantity") or 0.0)
        total += q
    return total

def _best_stop_price_for(side: str, stops: List[Dict[str,Any]]) -> Optional[float]:
    # For long (pos BUY), we use SELL stops; want the HIGHEST (tightest) stop.
    # For short (pos SELL), we use BUY stops; want the LOWEST (tightest) stop.
    if not stops:
        return None
    prices = []
    for o in stops:
        with suppress(Exception):
            prices.append(float(o.get("stopPrice") or o.get("price") or 0.0))
    if not prices:
        return None
    return max(prices) if side == "BUY" else min(prices)

def _profit_ok(entry: float, last: float, side: str, min_pct: float) -> bool:
    if min_pct <= 0 or entry <= 0 or last <= 0:
        return True
    move = (last - entry) / entry * 100.0 if side == "BUY" else (entry - last) / entry * 100.0
    return move >= min_pct

# =========================
# ATR helper (simple TR(14) over 1m)
# =========================
def _atr_1m(cli, symbol: str, lookback: int = 16) -> float:
    with suppress(Exception):
        kl = cli.futures_klines(symbol=symbol, interval="1m", limit=lookback)
        if not kl or len(kl) < 2:
            return 0.0
        trs = []
        from math import fabs
        for i in range(1, len(kl)):
            h = float(kl[i][2]); l = float(kl[i][3]); pc = float(kl[i-1][4])
            trs.append(max(h-l, fabs(h-pc), fabs(l-pc)))
        if len(trs) >= 14:
            return sum(trs[-14:]) / 14.0
    return 0.0

# =========================
# Atomic update for a single STOP (reduce-only, quantities)
# =========================
def _place_new_stop_quantities(cli, symbol: str, opp_side: str, qty: float, stop_px: float) -> Dict[str, Any]:
    return cli.futures_create_order(
        symbol=symbol,
        side=opp_side,
        type="STOP_MARKET",
        stopPrice=stop_px,
        quantity=qty,
        reduceOnly=True,
        workingType=STOP_WORKING_TYPE,
        timeInForce="GTC",
        newClientOrderId=_build_client_order_id(symbol, opp_side, role="SL@ALGOGPT"),
    )

def _cancel_other_stops(cli, symbol: str, keep_order_id: Optional[int]) -> int:
    n = 0
    for o in (cli.futures_get_open_orders(symbol=symbol.upper()) or []):
        typ = (o.get("type") or "").upper()
        oid = o.get("orderId")
        if "STOP" in typ and (keep_order_id is None or oid != keep_order_id):
            with suppress(Exception):
                cli.futures_cancel_order(symbol=symbol.upper(), orderId=oid)
                n += 1
    return n

# =========================
# PUBLIC: ensure_protective_stop
# =========================
def ensure_protective_stop(symbol: str, prefer_mode: str = "quantities") -> Dict[str, Any]:
    """
    Ensures there's ALWAYS a protective STOP on 100% of the remaining position.
    - Quantities mode (reduceOnly) only (as per your env): USE_NATIVE_TP_SL=0
    - After TP1: move to BE+ buffer (monotonic tightening)
    - Optional trailing using ATR with min profit gate
    - Atomic update: place→verify→cancel (no window without SL)
    Returns diagnostic dict with actions taken.
    """
    out: Dict[str, Any] = {"ok": True, "symbol": symbol, "actions": []}
    if not GUARD_ENSURE_SL:
        out["ok"] = False
        out["reason"] = "guard_disabled"
        return out

    cli = _get_client()
    symbol = symbol.upper()

    # Get position
    try:
        side, abs_qty, entry = _position_side_qty_entry(cli, symbol)
    except Exception as e:
        return {"ok": False, "symbol": symbol, "reason": "no_position", "error": str(e)}

    opp = "SELL" if side == "BUY" else "BUY"
    last = 0.0
    with suppress(Exception):
        last = _last_price(cli, symbol)

    flt = _get_filters(cli, symbol)

    # Check existing stops
    active_stops = _collect_active_stops(cli, symbol, opp)
    covered = _sum_stop_qty(active_stops)
    current_sl_px = _best_stop_price_for(side, active_stops)

    # Decide target stop (priority: Emergency -> BE+ (if TP1 or allowed) -> ATR trail if min profit)
    target_px: Optional[float] = None
    reason: str = "emergency"

    # 1) Emergency if nothing covers 100% within grace
    has_full_cover = (covered + 1e-12) >= abs_qty * 0.999
    if not has_full_cover:
        # Emergency stop at BE+ buffer if possible, else slightly worse than entry to guarantee coverage
        if entry > 0:
            if side == "BUY":
                target_px = entry * (1.0 - max(0, 10 - TP_BE_OFFSET_BPS)/10000.0)  # small cushion below entry
            else:
                target_px = entry * (1.0 + max(0, 10 - TP_BE_OFFSET_BPS)/10000.0)
        else:
            # Fallback to last with a small band
            if last > 0:
                band = float(os.getenv("STOP_BAND_BPS","12") or 12) / 10000.0
                target_px = last * (1.0 - band) if side == "BUY" else last * (1.0 + band)
        reason = "emergency_no_full_cover"

    # 2) BE+ after TP1 (monotonic) — only if enabled
    tp1_ok = _tp1_filled(cli, symbol) if (SMART_MANAGE_AFTER_TP1 or TP_BE_ONLY_AFTER_TP1) else True
    if tp1_ok or not TP_BE_ONLY_AFTER_TP1:
        if entry > 0:
            be_px = entry * (1.0 + TP_BE_OFFSET_BPS/10000.0) if side == "BUY" else entry * (1.0 - TP_BE_OFFSET_BPS/10000.0)
            if target_px is None:
                target_px = be_px
                reason = "be_plus"
            else:
                # tighten monotonically
                if side == "BUY":
                    target_px = max(target_px, be_px)
                else:
                    target_px = min(target_px, be_px)

    # 3) ATR trail if min profit achieved
    if last > 0 and _profit_ok(entry, last, side, TRAIL_MIN_PROFIT_PCT):
        atr_mult = float(os.getenv("SMART_MANAGE_TRAIL_ATR_MULT","1.5") or 1.5)
        atr = _atr_1m(cli, symbol, lookback=16)
        if atr > 0:
            if side == "BUY":
                atr_sl = last - atr * atr_mult
                # never below BE+ if TP1 achieved
                if tp1_ok and entry > 0:
                    be_px = entry * (1.0 + TP_BE_OFFSET_BPS/10000.0)
                    atr_sl = max(atr_sl, be_px)
                target_px = max(target_px or -1e9, atr_sl)
            else:
                atr_sl = last + atr * atr_mult
                if tp1_ok and entry > 0:
                    be_px = entry * (1.0 - TP_BE_OFFSET_BPS/10000.0)
                    atr_sl = min(atr_sl, be_px)
                target_px = min(target_px or 1e18, atr_sl)
            reason = "atr_trail"

    # Quantize target
    if target_px is None:
        # Fallback to entry or small band if all else failed
        if entry > 0:
            target_px = entry
        elif last > 0:
            band = float(os.getenv("STOP_BAND_BPS","12") or 12) / 10000.0
            target_px = last * (1.0 - band) if side == "BUY" else last * (1.0 + band)
        else:
            return {"ok": False, "symbol": symbol, "reason": "no_target_px"}
    target_px = _quantize_price_local(symbol, float(target_px), flt)

    # Enforce monotonic tightening against current SL
    if current_sl_px is not None:
        if side == "BUY" and target_px < current_sl_px:
            target_px = current_sl_px
            reason = "monotonic_guard"
        if side == "SELL" and target_px > current_sl_px:
            target_px = current_sl_px
            reason = "monotonic_guard"

    # Quantity — we always cover 100% remaining
    qty = _quantize_qty_local(symbol, abs_qty, flt)
    if qty <= 0:
        return {"ok": False, "symbol": symbol, "reason": "qty_rounds_zero"}

    # If we already have full cover and SL price is tight enough, honor grace window (avoid flapping)
    if has_full_cover and current_sl_px is not None:
        # allow minor difference threshold (one tick)
        tick = float(flt.get("price_tick") or 0.0)
        if tick and abs(target_px - current_sl_px) < (1.5 * tick):
            return {"ok": True, "symbol": symbol, "actions": [{"skip":"already_protected","current_sl": current_sl_px}]}

    # ========== Atomic Update ==========
    # 1) Place NEW stop (quantities, reduceOnly)
    new_ord = _place_new_stop_quantities(cli, symbol, opp, qty, target_px)
    out["actions"].append({"placed_new_stop": {"orderId": new_ord.get("orderId"), "stopPrice": target_px, "qty": qty, "reason": reason}})

    # 2) Verify WORKING (short wait + fetch)
    time.sleep(min(0.8, float(os.getenv("ORD_VERIFY_TIMEOUT_MS","800"))/1000.0))
    open_after = cli.futures_get_open_orders(symbol=symbol.upper()) or []
    new_order_id = new_ord.get("orderId")
    found = any(o.get("orderId") == new_order_id and (o.get("status") or "").upper() == "NEW" for o in open_after)
    if not found:
        # If not found, do not cancel others to avoid gap; just report
        out["ok"] = False
        out["actions"].append({"verify_failed": True})
        return out

    # 3) Cancel older stops (minimal)
    cancelled = _cancel_other_stops(cli, symbol, keep_order_id=new_order_id)
    out["actions"].append({"cancelled_old_stops": cancelled})

    # Done
    return out


