from __future__ import annotations

import os, time, math, re
from contextlib import suppress
from typing import Any, Dict, List, Tuple, Optional
from functools import lru_cache
import time as _t

# =========================
# Env / Flags
# =========================
GUARD_ENSURE_SL        = (os.getenv("GUARD_ENSURE_SL","1").lower() in ("1","true","yes","on"))
GUARD_SL_GRACE_SEC     = int(os.getenv("GUARD_SL_GRACE_SEC","2"))
STRICT_MODE_SINGLE     = (os.getenv("STRICT_MODE_SINGLE","1").lower() in ("1","true","yes","on"))
USE_NATIVE_TP_SL_FLAG  = (os.getenv("USE_NATIVE_TP_SL","0").lower() in ("1","true","yes","on"))
AUTO_TPSL_MODE         = (os.getenv("AUTO_TPSL_MODE","off").lower() in ("auto","on","1","true","yes"))
STOP_WORKING_TYPE      = (os.getenv("STOP_WORKING_TYPE") or os.getenv("BINANCE_WORKING_TYPE") or "MARK_PRICE")
TP_BE_ONLY_AFTER_TP1   = (os.getenv("TP_BE_ONLY_AFTER_TP1","1").lower() in ("1","true","yes","on"))
SMART_MANAGE_AFTER_TP1 = (os.getenv("SMART_MANAGE_AFTER_TP1","1").lower() in ("1","true","yes","on"))
TRAIL_MIN_PROFIT_PCT   = float(os.getenv("TRAIL_MIN_PROFIT_PCT","0.7") or 0.0)
TP_BE_OFFSET_BPS       = int(os.getenv("TP_BE_OFFSET_BPS","8"))
ORDER_ROUND_TO_TICK    = (os.getenv("ORDER_ROUND_TO_TICK","1").lower() in ("1","true","yes","on"))
USE_EXCHANGE_FILTERS   = (os.getenv("USE_EXCHANGE_FILTERS","1").lower() in ("1","true","yes","on"))
ENFORCE_QTY_BOUNDS     = (os.getenv("ENFORCE_QTY_BOUNDS","1").lower() in ("1","true","yes","on"))
ORD_ATOMIC_UPDATE      = (os.getenv("ORD_ATOMIC_UPDATE","1").lower() in ("1","true","yes","on"))

FILTERS_CACHE_TTL_SEC  = int(os.getenv("FILTERS_CACHE_TTL_SEC","900"))

# זיהוי מצב דו-צדדי לפי override (פשוט ומהיר)
_MODE_OVERRIDE = (os.getenv("POSITION_MODE_OVERRIDE","") or os.getenv("HEDGE_MODE","")).strip().lower()
_DUAL_SIDE_ENABLED = _MODE_OVERRIDE in ("hedge","dual","dual_side","dual_side_position","dualposition","1","true","yes","on")

def _effective_position_side(entry_side: str) -> str:
    if not _DUAL_SIDE_ENABLED:
        return "BOTH"
    return "LONG" if (entry_side or "").upper() == "BUY" else "SHORT"

# =========================
# Binance client & helpers
# =========================
def _get_client():
    from binance.client import Client  # type: ignore
    api_key = (os.getenv("BINANCE_API_KEY") or "").strip()
    api_sec = (os.getenv("BINANCE_API_SECRET") or "").strip()
    if not api_key or not api_sec:
        raise RuntimeError("BINANCE keys missing")
    cli = Client(api_key, api_sec)
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
# Quantize
# =========================
def _fallback_filters():
    return {"price_tick": float(os.getenv("DEFAULT_PRICE_TICK","0.01")),
            "qty_step":   float(os.getenv("DEFAULT_QTY_STEP","0.001"))}

# TTL cache לפילטרים (ללא תלות ב-LRU בלבד)
_filters_cache: Dict[str, Tuple[float, Dict[str,Any]]] = {}

def _round_step(v: float, step: float) -> float:
    if step <= 0: return v
    return math.floor(v/step + 1e-12) * step

def _qprice(symbol: str, price: float, flt: Dict[str,Any]) -> float:
    step = float(flt.get("price_tick") or 0.0)
    return round(_round_step(price, step), 8) if (ORDER_ROUND_TO_TICK and step>0) else round(price, 8)

def _qqty(symbol: str, qty: float, flt: Dict[str,Any]) -> float:
    step = float(flt.get("qty_step") or 0.0)
    return round(_round_step(qty, step), 8) if (ORDER_ROUND_TO_TICK and step>0) else round(qty, 8)

def _get_filters_uncached(cli, symbol: str) -> Dict[str,Any]:
    ex = cli.futures_exchange_info() or {}
    for s in ex.get("symbols", []):
        if (s.get("symbol") or "").upper() == symbol.upper():
            price_tick = qty_step = 0.0
            for f in s.get("filters", []):
                t = f.get("filterType")
                if t=="PRICE_FILTER": price_tick = float(f.get("tickSize") or 0.0)
                if t=="LOT_SIZE":     qty_step  = float(f.get("stepSize") or 0.0)
            return {"price_tick": price_tick, "qty_step": qty_step} or _fallback_filters()
    return _fallback_filters()

def _get_filters(cli, symbol: str) -> Dict[str,Any]:
    if not USE_EXCHANGE_FILTERS:
        return _fallback_filters()
    now = _t.time()
    k = symbol.upper()
    ts, cached = _filters_cache.get(k, (0.0, {}))
    if cached and (now - ts) < FILTERS_CACHE_TTL_SEC:
        return cached
    with suppress(Exception):
        data = _get_filters_uncached(cli, symbol)
        _filters_cache[k] = (now, data)
        return data
    return _fallback_filters()

with suppress(Exception):
    from utils.quantize import get_filters as _gf, quantize_price as _qp, quantize_qty as _qq  # type: ignore
    def _get_filters(cli, symbol: str) -> Dict[str,Any]:  # type: ignore
        return _gf(cli, symbol)
    def _qprice(symbol: str, price: float, flt: Dict[str,Any]) -> float:  # type: ignore
        return _qp(symbol, price, flt)
    def _qqty(symbol: str, qty: float, flt: Dict[str,Any]) -> float:  # type: ignore
        return _qq(symbol, qty, flt)

# =========================
# Order IDs (מרוכז עם fallback)
# =========================
try:
    from utils.order_ids import build_client_order_id as _builder  # type: ignore
except Exception:
    _SAFE = re.compile(r'[^A-Za-z0-9._:/-]')
    def _sanitize(s: str, maxlen: int = 36) -> str:
        return _SAFE.sub("_", str(s))[:maxlen]
    def _coid_fit(s: str, maxlen: int = 36) -> str:
        s = _sanitize(s, maxlen*4)
        if len(s) <= maxlen: return s
        import hashlib as _hh
        h = _hh.md5(s.encode("utf-8")).hexdigest()[:6]
        return f"{s[:maxlen-(len(h)+1)]}_{h}"
    def _builder(symbol: str, side: str, role: str) -> str:
        pref = (os.getenv("ORDER_ID_PREFIX") or "ALG").strip() or "ALG"
        role = str(role or "").replace("@","_")
        ts = int(time.time()*1000)
        return _coid_fit(f"{pref}-{symbol}-{side}-{role}-{ts}", 36)

def _build_client_order_id(symbol: str, side: str, role: str) -> str:
    return _builder(symbol, side, str(role or "").replace("@","_"))

# =========================
# Position & open orders
# =========================
def _pos(cli, symbol: str) -> Tuple[str, float, float]:
    infos = cli.futures_position_information(symbol=symbol) or []
    if not infos: raise RuntimeError("No position info")
    amt = float(infos[0].get("positionAmt") or 0.0)
    ep  = float(infos[0].get("entryPrice") or 0.0)
    if abs(amt) < 1e-12: raise RuntimeError("No open position")
    return ("BUY" if amt>0 else "SELL"), abs(amt), ep

def _active_orders(cli, symbol: str) -> List[Dict[str,Any]]:
    return cli.futures_get_open_orders(symbol=symbol.upper()) or []

def _split_native_vs_qty(orders: List[Dict[str,Any]]) -> Tuple[List[Dict[str,Any]], List[Dict[str,Any]]]:
    native, qty = [], []
    for o in orders:
        typ = (o.get("type") or "").upper()
        if "STOP" in typ or "TAKE_PROFIT" in typ:
            if str(o.get("closePosition","")).lower() == "true":
                native.append(o)
            elif o.get("reduceOnly") is True or o.get("origQty") or o.get("quantity"):
                qty.append(o)
            else:
                native.append(o)
    return native, qty

def _sum_stop_qty(orders: List[Dict[str,Any]]) -> float:
    total = 0.0
    for o in orders:
        total += float(o.get("origQty") or o.get("quantity") or 0.0)
    return total

def _best_stop_px(side: str, stops: List[Dict[str,Any]]) -> Optional[float]:
    prices = []
    for o in stops:
        with suppress(Exception):
            prices.append(float(o.get("stopPrice") or o.get("price") or 0.0))
    if not prices: return None
    return (max(prices) if side=="BUY" else min(prices))

def _profit_ok(entry: float, last: float, side: str, min_pct: float) -> bool:
    if min_pct<=0 or entry<=0 or last<=0: return True
    move = (last-entry)/entry*100.0 if side=="BUY" else (entry-last)/entry*100.0
    return move >= min_pct

# ATR(14,1m)
def _atr_1m(cli, symbol: str, lookback: int = 16) -> float:
    with suppress(Exception):
        kl = cli.futures_klines(symbol=symbol, interval="1m", limit=lookback)
        if not kl or len(kl)<2: return 0.0
        trs=[]
        from math import fabs
        for i in range(1,len(kl)):
            h=float(kl[i][2]); l=float(kl[i][3]); pc=float(kl[i-1][4])
            trs.append(max(h-l, fabs(h-pc), fabs(l-pc)))
        if len(trs)>=14: return sum(trs[-14:])/14.0
    return 0.0

# =========================
# Placers / cancels for both modes
# =========================
def _place_stop_quantities(cli, symbol: str, side: str, qty: float, stop_px: float, position_side: Optional[str]) -> Dict[str,Any]:
    payload = dict(
        symbol=symbol, side=side, type="STOP_MARKET",
        stopPrice=stop_px, quantity=qty, reduceOnly=True,
        workingType=STOP_WORKING_TYPE, timeInForce="GTC",
        newClientOrderId=_build_client_order_id(symbol, side, "SL_ALGOGPT"),
    )
    if position_side:
        payload["positionSide"] = position_side
    return cli.futures_create_order(**payload)

def _place_stop_native(cli, symbol: str, side: str, stop_px: float, position_side: Optional[str]) -> Dict[str,Any]:
    payload = dict(
        symbol=symbol, side=side, type="STOP_MARKET",
        stopPrice=stop_px, closePosition=True,
        workingType=STOP_WORKING_TYPE, timeInForce="GTC",
        newClientOrderId=_build_client_order_id(symbol, side, "SL_ALGOGPT"),
    )
    if position_side:
        payload["positionSide"] = position_side
    return cli.futures_create_order(**payload)

def _cancel_stops(cli, symbol: str, keep_order_id: Optional[int], kinds=("STOP","TAKE_PROFIT","TRAILING_STOP")) -> int:
    n=0
    for o in _active_orders(cli, symbol):
        typ=(o.get("type") or "").upper()
        if any(k in typ for k in kinds):
            if keep_order_id is None or o.get("orderId")!=keep_order_id:
                with suppress(Exception):
                    cli.futures_cancel_order(symbol=symbol.upper(), orderId=o["orderId"]); n+=1
    return n

# =========================
# Decide target price (Emergency / BE+ / ATR)
# =========================
def _target_sl_price(cli, symbol: str, side: str, entry: float, last: float, tp1_ok: bool,
                     current_sl_px: Optional[float], flt: Dict[str,Any]) -> Tuple[float, str]:
    reason="emergency"
    tgt: Optional[float]=None

    # Emergency (no cover)
    if entry>0:
        if side=="BUY":
            tgt = entry * (1.0 - max(0, 10-TP_BE_OFFSET_BPS)/10000.0)
        else:
            tgt = entry * (1.0 + max(0, 10-TP_BE_OFFSET_BPS)/10000.0)
    elif last>0:
        band = float(os.getenv("STOP_BAND_BPS","12") or 12)/10000.0
        tgt = last*(1.0-band) if side=="BUY" else last*(1.0+band)

    # BE+
    if tp1_ok or not TP_BE_ONLY_AFTER_TP1:
        if entry>0:
            be = entry*(1.0 + (TP_BE_OFFSET_BPS/10000.0)) if side=="BUY" else entry*(1.0 - (TP_BE_OFFSET_BPS/10000.0))
            if side=="BUY": tgt = max(tgt or -1e9, be)
            else:           tgt = min(tgt or  1e18, be)
            reason="be_plus"

    # ATR trail (with min profit)
    if last>0 and _profit_ok(entry,last,side,TRAIL_MIN_PROFIT_PCT):
        atr_mult = float(os.getenv("SMART_MANAGE_TRAIL_ATR_MULT","1.5") or 1.5)
        atr = _atr_1m(cli, symbol)
        if atr>0:
            if side=="BUY":
                atr_sl = last - atr*atr_mult
                if (tp1_ok or not TP_BE_ONLY_AFTER_TP1) and entry>0:
                    atr_sl = max(atr_sl, entry*(1.0 + TP_BE_OFFSET_BPS/10000.0))
                tgt = max(tgt or -1e9, atr_sl)
            else:
                atr_sl = last + atr*atr_mult
                if (tp1_ok or not TP_BE_ONLY_AFTER_TP1) and entry>0:
                    atr_sl = min(atr_sl, entry*(1.0 - TP_BE_OFFSET_BPS/10000.0))
                tgt = min(tgt or 1e18, atr_sl)
            reason = "atr_trail"

    if tgt is None:
        tgt = entry if entry>0 else last
    tgt = _qprice(symbol, float(tgt), flt)

    # monotonic tightening
    if current_sl_px is not None:
        if side=="BUY" and tgt<current_sl_px:  tgt=current_sl_px; reason="monotonic_guard"
        if side=="SELL" and tgt>current_sl_px: tgt=current_sl_px; reason="monotonic_guard"
    return tgt, reason

# =========================
# Mode decision (auto-safe)
# =========================
def _decide_mode(cli, symbol: str) -> str:
    """returns 'native' or 'quantities'."""
    if not AUTO_TPSL_MODE:
        return "native" if USE_NATIVE_TP_SL_FLAG else "quantities"
    nat, qty = _split_native_vs_qty(_active_orders(cli, symbol))
    if nat and not qty: return "native"
    if qty and not nat: return "quantities"
    if STRICT_MODE_SINGLE and nat and qty:
        return "native" if USE_NATIVE_TP_SL_FLAG else "quantities"
    return "native" if USE_NATIVE_TP_SL_FLAG else "quantities"

# =========================
# PUBLIC
# =========================
def ensure_protective_stop(symbol: str, prefer_mode: Optional[str] = None) -> Dict[str,Any]:
    """
    Ensures an always-on protective SL.
    """
    if not GUARD_ENSURE_SL:
        return {"ok": False, "symbol": symbol, "reason":"guard_disabled"}

    cli = _get_client()
    symbol = symbol.upper()
    try:
        side, abs_qty, entry = _pos(cli, symbol)
    except Exception as e:
        return {"ok": False, "symbol": symbol, "reason":"no_position", "error": str(e)}

    opp = "SELL" if side=="BUY" else "BUY"
    pos_side = _effective_position_side(side)  # positionSide עבור פקודת סגירה
    last = 0.0
    with suppress(Exception): last = _last_price(cli, symbol)
    flt = _get_filters(cli, symbol)

    mode = prefer_mode or _decide_mode(cli, symbol)  # 'native' | 'quantities'
    orders = _active_orders(cli, symbol)
    nat, qty = _split_native_vs_qty(orders)
    mode_orders = nat if mode=="native" else qty
    current_sl_px = _best_stop_px(side, mode_orders)

    tp1_ok = _tp1_filled(cli, symbol) if (SMART_MANAGE_AFTER_TP1 or TP_BE_ONLY_AFTER_TP1) else True
    target_px, reason = _target_sl_price(cli, symbol, side, entry, last, tp1_ok, current_sl_px, flt)

    qty_cover = _qqty(symbol, abs_qty, flt)
    if qty_cover <= 0: return {"ok": False, "symbol": symbol, "reason":"qty_rounds_zero"}

    if current_sl_px is not None:
        tick = float(flt.get("price_tick") or 0.0)
        if tick and abs(target_px - current_sl_px) < (1.0 * tick):
            return {"ok": True, "symbol": symbol, "mode": mode, "actions":[{"skip":"already_protected","current_sl": current_sl_px}]}

    if mode=="native":
        new_ord = _place_stop_native(cli, symbol, opp, target_px, pos_side)
    else:
        new_ord = _place_stop_quantities(cli, symbol, opp, qty_cover, target_px, pos_side)

    time.sleep(min(0.8, float(os.getenv("ORD_VERIFY_TIMEOUT_MS","800"))/1000.0))
    after = _active_orders(cli, symbol)
    found = any(o.get("orderId")==new_ord.get("orderId") and (o.get("status") or "").upper()=="NEW" for o in after)
    if not found:
        return {"ok": False, "symbol": symbol, "mode": mode, "actions":[{"verify_failed": True}]}

    cancelled = _cancel_stops(cli, symbol, keep_order_id=new_ord.get("orderId"))
    return {
        "ok": True, "symbol": symbol, "mode": mode,
        "actions": [
            {"placed_new_stop": {"orderId": new_ord.get("orderId"), "stopPrice": target_px, "qty": (qty_cover if mode=='quantities' else None), "reason": reason, "positionSide": pos_side}},
            {"cancelled_old_stops": cancelled},
        ]
    }





