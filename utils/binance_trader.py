# -*- coding: utf-8 -*-
# utils/binance_trade.py
from __future__ import annotations
import os, time, math, re
from typing import Any, Dict, Optional, List, Tuple
from contextlib import suppress

__all__ = ["plan_trade", "execute_trade", "execute_order", "unrealized"]

# ── ENV helpers ───────────────────────────────────────────────────────────────
def _env_list_floats(name: str, default_csv: str) -> List[float]:
    raw = os.getenv(name, default_csv)
    out: List[float] = []
    for p in str(raw).split(","):
        p = p.strip()
        if not p:
            continue
        try:
            out.append(float(p))
        except Exception:
            pass
    return out

def _env_bool(name: str, default: str = "0") -> bool:
    return (os.getenv(name, default) or "").strip().lower() in ("1", "true", "yes", "on")

# defaults
DEFAULT_SL_BPS   = _env_list_floats("DEFAULT_SL_BPS",   "80")            # 0.8%
DEFAULT_TP_BPS   = _env_list_floats("DEFAULT_TP_BPS",   "60,120,200")    # 0.6/1.2/2.0%
DEFAULT_TP_SPLIT = _env_list_floats("DEFAULT_TP_SPLITS","0.34,0.33,0.33")

ORDER_ID_PREFIX   = os.getenv("ORDER_ID_PREFIX","ALG") or "ALG"
WORKING_TYPE      = os.getenv("BINANCE_WORKING_TYPE","MARK_PRICE")
POSITION_OVERRIDE = (os.getenv("POSITION_MODE_OVERRIDE","") or "").lower()

RETRY_MAX         = int(os.getenv("RETRY_MAX","3") or 3)
RETRY_BASE_MS     = int(os.getenv("RETRY_BASE_MS","500") or 500)

# ── COID helpers ──────────────────────────────────────────────────────────────
_COID_SAFE = re.compile(r"[^A-Z0-9_]+")

def _sanitize_coid(x: str) -> str:
    return _COID_SAFE.sub("", (x or "").upper())[:36] or "COID"

def _coid(kind: str, symbol: str) -> str:
    base = (ORDER_ID_PREFIX or "ALG").upper()
    return _sanitize_coid(f"{base}-{kind}-{symbol}-{int(time.time()*1000)}")

# ── Side & maths ──────────────────────────────────────────────────────────────
def _side_dir(side: str) -> int:
    s = (side or "").upper()
    if s in ("BUY","LONG"):   return +1
    if s in ("SELL","SHORT"): return -1
    return 0

def _bn_floor(value: float, step: float) -> float:
    if step <= 0:
        return value
    return math.floor(value / step) * step

def _bn_round_price(p: float, tick: float) -> float:
    if tick <= 0:
        return p
    q = round(p / tick)
    return float(q * tick)

# ── Binance client ────────────────────────────────────────────────────────────
def _client():
    api_key = os.getenv("BINANCE_API_KEY","").strip()
    api_sec = os.getenv("BINANCE_API_SECRET","").strip()
    if not (api_key and api_sec):
        return None
    with suppress(Exception):
        from binance.client import Client  # type: ignore
        c = Client(api_key, api_sec)
        if POSITION_OVERRIDE:
            with suppress(Exception):
                if POSITION_OVERRIDE in ("hedge","dual","dual_side","dual_side_position","dualposition"):
                    c.futures_change_position_mode(dualSidePosition="true")
                elif POSITION_OVERRIDE in ("oneway","one_way","single","single_side","oneside"):
                    c.futures_change_position_mode(dualSidePosition="false")
        return c
    return None

def _exchange_info(client, symbol: str) -> Tuple[float, float]:
    """return (tickSize, stepSize)"""
    tick, step = 0.1, 0.001
    try:
        info = client.futures_exchange_info()
        for s in info.get("symbols", []):
            if s.get("symbol") == symbol:
                for f in s.get("filters", []):
                    if f.get("filterType") == "PRICE_FILTER":
                        tick = float(f.get("tickSize", tick))
                    elif f.get("filterType") == "LOT_SIZE":
                        step = float(f.get("stepSize", step))
                break
    except Exception:
        pass
    return tick, step

def _last_price(client, symbol: str) -> float:
    with suppress(Exception):
        t = client.futures_symbol_ticker(symbol=symbol)
        return float(t.get("price") or 0.0)
    return 0.0

# ── PNL/ROE snapshot (fixes “PNL תמיד 0”) ─────────────────────────────────────
def unrealized(symbol: str) -> Dict[str, Any]:
    """
    Pulls USDT-M position info and computes live PnL% and ROE%.
    Returns {"ok":True, ...} or {"ok":False,"error":...}
    """
    c = _client()
    if c is None:
        return {"ok": False, "error": "binance_keys_missing"}
    try:
        rows = c.futures_position_information(symbol=symbol)
    except Exception as e:
        return {"ok": False, "error": f"{e}"}
    if not rows:
        return {"ok": True, "empty": True}

    p = rows[0]
    entry = float(p.get("entryPrice") or 0.0)
    qty   = float(p.get("positionAmt") or 0.0)
    mark  = float(p.get("markPrice") or 0.0)
    lev   = float(p.get("leverage") or 0.0) or 1.0
    side  = "BUY" if qty > 0 else ("SELL" if qty < 0 else "FLAT")

    d = _side_dir(side)
    pnl_pct = ((mark - entry) / entry * d * 100.0) if entry > 0 else 0.0
    roe_pct = pnl_pct * lev

    return {
        "ok": True,
        "symbol": symbol,
        "side": side,
        "entry": entry,
        "mark": mark,
        "qty": qty,
        "pnl_pct": pnl_pct,
        "roe_pct": roe_pct,
        "leverage": lev,
    }

# ── Planning (SL/TP) ─────────────────────────────────────────────────────────
def _build_sl_tp(entry: float, side: str) -> tuple[dict, List[dict]]:
    d = _side_dir(side)
    if not d or not entry:
        return ({}, [])
    sl_bps = DEFAULT_SL_BPS[0] if DEFAULT_SL_BPS else 80.0
    sl_px  = entry * (1 - d*(sl_bps / 10000.0))
    sl = {"stopPrice": float(sl_px)}
    tps: List[dict] = []
    splits = DEFAULT_TP_SPLIT if DEFAULT_TP_SPLIT else [1.0]
    for i, bps in enumerate(DEFAULT_TP_BPS or [120.0], start=1):
        px = entry * (1 + d*(bps / 10000.0))
        leg = {"stopPrice": float(px)}
        if i-1 < len(splits):
            leg["split"] = float(splits[i-1])
        tps.append(leg)
    return sl, tps

def plan_trade(
    symbol: str,
    side: str,
    leverage: int,
    budget_usd: float,
    order_type: str = "MARKET",
    entry_price: Optional[float] = None,
    **kwargs
) -> Dict[str, Any]:
    symbol = (symbol or "").upper()
    side   = (side or "").upper()
    order_type = (order_type or "MARKET").upper()
    price = float(entry_price or 0.0)
    if price <= 0.0:
        with suppress(Exception):
            import requests  # type: ignore
            base = os.getenv("INTERNAL_BASE", os.getenv("PUBLIC_HOST", "http://127.0.0.1:10000"))
            r = requests.get(f"{base}/price/{symbol}", timeout=2.5)
            if r.ok:
                price = float(r.json().get("price") or 0.0)
    sl, tps = _build_sl_tp(float(price or 0.0), side)
    return {
        "symbol": symbol,
        "side": side,
        "leverage": int(leverage),
        "order_type": order_type,
        "entry_price": price,
        "sl": sl,
        "tp": tps,
        "budget_usd": float(budget_usd),
        "eta":   {"entry_sec": 5, "tp1_sec": 300, "tp2_sec": 900, "tp3_sec": 1800},
        "probs": {"overall": 0.62, "tp1": 0.70, "tp2": 0.50, "tp3": 0.30},
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "trade_kind": "Futures",
    }

# ── Low-level place/cancel helpers ────────────────────────────────────────────
def _ensure_leverage(client, symbol: str, lev: int) -> Dict[str, Any]:
    try:
        client.futures_change_leverage(symbol=symbol, leverage=int(lev))
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": f"{e}"}

def _place_market(client, symbol: str, side: str, qty: float, position_side: str = "", reduce_only: bool = False) -> Dict[str, Any]:
    kw = dict(symbol=symbol, side=side, type="MARKET", quantity=float(qty), newClientOrderId=_coid("MKT", symbol))
    if position_side:
        kw["positionSide"] = position_side
    if reduce_only:
        kw["reduceOnly"] = True
    for attempt in range(RETRY_MAX):
        try:
            return {"ok": True, "order": client.futures_create_order(**kw)}
        except Exception as e:
            s = str(e).lower()
            # 4061 positionSide mismatch → retry variants
            if "code=-4061" in s or "position side does not match" in s:
                with suppress(Exception):
                    kw2 = dict(kw); kw2.pop("positionSide", None)
                    return {"ok": True, "order": client.futures_create_order(**kw2), "retry": "no_positionSide"}
                with suppress(Exception):
                    kw3 = dict(kw)
                    kw3["positionSide"] = "LONG" if side.upper()=="BUY" else "SHORT"
                    return {"ok": True, "order": client.futures_create_order(**kw3), "retry": "derived_positionSide"}
            # 429/418/-1003 backoff
            if any(code in s for code in ("429", "418", "1003")) and attempt < RETRY_MAX-1:
                time.sleep((RETRY_BASE_MS/1000.0) * (attempt+1))
                continue
            return {"ok": False, "error": f"{e}"}
    return {"ok": False, "error": "place_market_exhausted"}

def _place_stop_market(client, symbol: str, side: str, stop_price: float, reduce_only: bool=True) -> Dict[str, Any]:
    opp_side = "SELL" if side.upper()=="BUY" else "BUY"
    kw = dict(
        symbol=symbol, side=opp_side, type="STOP_MARKET",
        stopPrice=float(stop_price), workingType=WORKING_TYPE,
        reduceOnly=bool(reduce_only), newClientOrderId=_coid("SL", symbol)
    )
    try:
        return {"ok": True, "order": client.futures_create_order(**kw)}
    except Exception as e:
        return {"ok": False, "error": f"{e}"}

def _place_tp_market(client, symbol: str, side: str, stop_price: float, qty: float) -> Dict[str, Any]:
    opp_side = "SELL" if side.upper()=="BUY" else "BUY"
    kw = dict(
        symbol=symbol, side=opp_side, type="TAKE_PROFIT_MARKET",
        stopPrice=float(stop_price), workingType=WORKING_TYPE,
        reduceOnly=True, quantity=float(qty), newClientOrderId=_coid("TP", symbol)
    )
    try:
        return {"ok": True, "order": client.futures_create_order(**kw)}
    except Exception as e:
        return {"ok": False, "error": f"{e}"}

# ── Public API ────────────────────────────────────────────────────────────────
def execute_trade(
    symbol: str,
    side: str,
    leverage: int,
    budget_usd: float,
    *,
    dry_run: bool = True,
    confirm_first: bool = True,  # kept for signature compatibility
    order_type: str = "MARKET",
    entry_price: Optional[float] = None,
    position_side: Optional[str] = None,
    qty: Optional[float] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Compatible entry-point for routes.executor / routes.trade.
    Tries real executors if present, else executes via python-binance;
    if keys missing → returns a plan (dry-run style).
    """
    # 1) delegate if internal executors exist
    with suppress(Exception):
        from utils.trade_executor import execute_trade_live as _x  # type: ignore
        return _x(symbol=symbol, side=side, leverage=leverage, budget=budget_usd,
                  dry_run=dry_run, entry=entry_price, quantity=qty, position_side=position_side, **kwargs)
    with suppress(Exception):
        from utils.trade_executor import execute_trade as _y  # type: ignore
        return _y(symbol=symbol, side=side, leverage=leverage, budget_usd=budget_usd,
                  dry_run=dry_run, order_type=order_type, entry_price=entry_price, quantity=qty, position_side=position_side, **kwargs)

    # 2) live shim
    client = _client()
    if client is None:
        plan = plan_trade(symbol, side, leverage, budget_usd, order_type, entry_price, **kwargs)
        return {"ok": True, "skipped": True, "reason": "binance_keys_missing", "result": plan}

    symbol = (symbol or "").upper()
    side   = (side or "").upper()
    d = _side_dir(side)
    if d == 0:
        return {"ok": False, "error": "bad_side"}

    price = float(entry_price or 0.0) or _last_price(client, symbol)
    if price <= 0.0:
        plan = plan_trade(symbol, side, leverage, budget_usd, order_type, entry_price, **kwargs)
        return {"ok": True, "skipped": True, "reason": "no_price", "result": plan}

    tick, step = _exchange_info(client, symbol)
    qty_calc = qty if (qty and qty > 0) else ((float(budget_usd) * int(leverage)) / price)
    qty_final = max(_bn_floor(float(qty_calc), float(step)), float(step))

    if dry_run:
        plan = plan_trade(symbol, side, leverage, budget_usd, order_type, price, **kwargs)
        plan["quantity"] = qty_final
        return {"ok": True, "result": dict(plan, dry_run=True)}

    # leverage
    lev_res = _ensure_leverage(client, symbol, int(leverage))
    if not lev_res.get("ok"):
        return {"ok": False, "error": "leverage_change_failed", "detail": lev_res}

    # entry MARKET
    ps = (position_side or ("LONG" if side=="BUY" else "SHORT")).upper()
    mkt = _place_market(client, symbol, side, qty_final, position_side=ps, reduce_only=False)
    if not mkt.get("ok"):
        return {"ok": False, "error": "entry_failed", "detail": mkt}

    # compute SL/TP
    sl_leg, tp_legs = _build_sl_tp(price, side)
    sl_px = _bn_round_price(float(sl_leg.get("stopPrice") or 0.0), tick) if sl_leg else 0.0

    # TP quantities by splits
    splits = [float(leg.get("split", 0.0)) for leg in tp_legs]
    if not splits or abs(sum(splits) - 1.0) > 1e-3:
        sm = sum(s for s in splits if s > 0) or 1.0
        splits = [s / sm for s in (splits if sm else [1.0])]
    tp_qtys = [max(_bn_floor(qty_final * s, step), 0.0) for s in splits]
    over = max(0.0, sum(tp_qtys) - qty_final)
    if over > 0:
        for i in range(len(tp_qtys)-1, -1, -1):
            if tp_qtys[i] >= over:
                tp_qtys[i] = max(0.0, tp_qtys[i] - over)
                break

    placed_tp, placed_sl = [], None
    # SL
    if sl_px > 0:
        r = _place_stop_market(client, symbol, side, sl_px, reduce_only=True)
        if r.get("ok"):
            placed_sl = r.get("order")
    # TP legs
    for i, leg in enumerate(tp_legs):
        px = _bn_round_price(float(leg.get("stopPrice") or 0.0), tick)
        q  = float(tp_qtys[i] if i < len(tp_qtys) else 0.0)
        if px > 0 and q > 0:
            pr = _place_tp_market(client, symbol, side, px, q)
            if pr.get("ok"):
                placed_tp.append(pr.get("order"))

    return {
        "ok": True,
        "exchange": "binance_futures",
        "entry": mkt.get("order"),
        "sl": placed_sl,
        "tp": placed_tp,
        "quantity": qty_final,
        "price_ref": price,
        "tick": tick, "step": step,
        "workingType": WORKING_TYPE,
    }

async def execute_order(*args, **kwargs) -> Dict[str, Any]:
    """
    Legacy compatibility: execute an order via python-binance if keys exist.
    """
    client = _client()
    if client is None:
        return {"ok": True, "skipped": True, "reason": "binance_keys_missing"}
    try:
        from asyncio import to_thread
    except Exception:
        to_thread = None
    try:
        if to_thread:
            res = await to_thread(lambda: client.futures_create_order(**kwargs))
        else:
            res = client.futures_create_order(**kwargs)
        return {"ok": True, "order": res}
    except Exception as e:
        s = str(e).lower()
        if any(code in s for code in ("429", "418", "1003")):
            return {"ok": False, "error": "rate_limited_or_banned", "detail": f"{e}"}
        return {"ok": False, "error": f"{e}"}







































