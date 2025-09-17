# utils/binance_trade.py
from __future__ import annotations
import os, time, hmac, hashlib
from typing import Any, Dict, List, Optional, Tuple

import httpx

# מנסים לנצל את ה־utils הקיימים אצלך כשאפשר (מחיר, אקס’אינפו)
try:
    from utils.binance_client import get_price as _get_price_util, futures_exchange_info_safe
except Exception:
    _get_price_util = None
    futures_exchange_info_safe = None  # נשתמש ב-/fapi/v1/exchangeInfo אם אין

BINANCE_FAPI = os.getenv("BINANCE_FAPI_BASE", "https://fapi.binance.com")

def _api_keys() -> Tuple[str, str]:
    k = os.getenv("BINANCE_API_KEY", "").strip()
    s = os.getenv("BINANCE_API_SECRET", "").strip()
    if not k or not s:
        raise RuntimeError("BINANCE_API_KEY / BINANCE_API_SECRET missing")
    return k, s

def _sign(params: Dict[str, Any], secret: str) -> str:
    # סדר הפרמטרים כ־querystring
    q = "&".join(f"{k}={params[k]}" for k in sorted(params.keys()))
    return hmac.new(secret.encode(), q.encode(), hashlib.sha256).hexdigest()

async def _request(
    method: str,
    path: str,
    params: Dict[str, Any] | None = None,
    signed: bool = True,
    timeout: float = 10.0,
) -> Any:
    params = dict(params or {})
    headers = {}
    if signed:
        key, sec = _api_keys()
        params["timestamp"] = int(time.time() * 1000)
        params.setdefault("recvWindow", 5000)
        params["signature"] = _sign(params, sec)
        headers["X-MBX-APIKEY"] = key

    url = f"{BINANCE_FAPI}{path}"
    async with httpx.AsyncClient(timeout=timeout) as cli:
        if method.upper() == "GET":
            r = await cli.get(url, params=params, headers=headers)
        elif method.upper() == "POST":
            r = await cli.post(url, params=params, headers=headers)
        elif method.upper() == "DELETE":
            r = await cli.delete(url, params=params, headers=headers)
        else:
            raise RuntimeError(f"unsupported method {method}")
    r.raise_for_status()
    return r.json()

async def get_price(symbol: str) -> float:
    if callable(_get_price_util):
        try:
            p = _get_price_util(symbol)
            if p and p > 0:
                return float(p)
        except Exception:
            pass
    data = await _request("GET", "/fapi/v1/ticker/price", {"symbol": symbol}, signed=False)
    return float(data["price"])

# ------- exchange info / filters -------
_symbol_filters_cache: Dict[str, Dict[str, Any]] = {}

async def _load_exchange_info() -> Dict[str, Any]:
    if callable(futures_exchange_info_safe):
        try:
            info = futures_exchange_info_safe(force_refresh=False)
            if info:
                return info
        except Exception:
            pass
    return await _request("GET", "/fapi/v1/exchangeInfo", signed=False)

def _parse_filters(sym_info: Dict[str, Any]) -> Dict[str, Any]:
    out = {"stepSize": 0.001, "minQty": 0.0, "tickSize": 0.01}
    for f in sym_info.get("filters", []):
        if f.get("filterType") == "LOT_SIZE":
            out["stepSize"] = float(f.get("stepSize", out["stepSize"]))
            out["minQty"] = float(f.get("minQty", out["minQty"]))
        if f.get("filterType") == "PRICE_FILTER":
            out["tickSize"] = float(f.get("tickSize", out["tickSize"]))
    return out

async def get_symbol_filters(symbol: str) -> Dict[str, Any]:
    s = symbol.upper()
    if s in _symbol_filters_cache:
        return _symbol_filters_cache[s]
    info = await _load_exchange_info()
    for sym in info.get("symbols", []):
        if sym.get("symbol") == s:
            f = _parse_filters(sym)
            _symbol_filters_cache[s] = f
            return f
    # fallback
    f = {"stepSize": 0.001, "minQty": 0.0, "tickSize": 0.01}
    _symbol_filters_cache[s] = f
    return f

def _round_step(x: float, step: float) -> float:
    if step <= 0:
        return x
    return (int(x / step + 1e-12)) * step

def round_qty(symbol: str, qty: float, step: float) -> float:
    q = _round_step(qty, step)
    # נזהר שלא ליפול ל-0 בגלל עיגול
    return max(q, 0.0)

def round_price(symbol: str, price: float, tick: float) -> float:
    p = _round_step(price, tick)
    return max(p, 0.0)

# ------- leverage / orders -------
async def set_leverage(symbol: str, leverage: int) -> Any:
    return await _request("POST", "/fapi/v1/leverage", {"symbol": symbol.upper(), "leverage": leverage})

async def place_market_order(symbol: str, side: str, qty: float, reduce_only: bool = False) -> Any:
    params = {
        "symbol": symbol.upper(),
        "side": side.upper(),
        "type": "MARKET",
        "quantity": qty,
        "reduceOnly": "true" if reduce_only else "false",
    }
    return await _request("POST", "/fapi/v1/order", params)

async def place_tp_market(symbol: str, side: str, qty: float, stop_price: float) -> Any:
    # TAKE_PROFIT_MARKET לסגירה (reduceOnly)
    params = {
        "symbol": symbol.upper(),
        "side": "SELL" if side.upper() == "BUY" else "BUY",
        "type": "TAKE_PROFIT_MARKET",
        "stopPrice": stop_price,
        "closePosition": "false",
        "reduceOnly": "true",
        "quantity": qty,
    }
    return await _request("POST", "/fapi/v1/order", params)

async def place_sl_market(symbol: str, side: str, qty: float, stop_price: float) -> Any:
    params = {
        "symbol": symbol.upper(),
        "side": "SELL" if side.upper() == "BUY" else "BUY",
        "type": "STOP_MARKET",
        "stopPrice": stop_price,
        "closePosition": "false",
        "reduceOnly": "true",
        "quantity": qty,
    }
    return await _request("POST", "/fapi/v1/order", params)

# ------- plan & execute -------
async def plan_and_execute(
    *,
    symbol: str,
    side: str,
    leverage: int,
    budget_usd: float,
    tp_targets: Optional[List[float]] = None,
    tp_splits: Optional[List[float]] = None,
    sl_price: Optional[float] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    if leverage < 1 or leverage > 125:
        raise ValueError("leverage out of range")
    if budget_usd <= 0:
        raise ValueError("budget_usd must be > 0")
    side_up = side.upper()
    if side_up not in ("BUY", "SELL"):
        raise ValueError("side must be BUY/SELL")

    price = await get_price(symbol)
    filters = await get_symbol_filters(symbol)
    step, tick = float(filters["stepSize"]), float(filters["tickSize"])

    notional = budget_usd * leverage
    qty_raw = notional / price
    qty = round_qty(symbol, qty_raw, step)
    if qty <= 0:
        raise ValueError("calculated qty is zero; increase budget")

    plan = {
        "symbol": symbol.upper(),
        "side": side_up,
        "leverage": leverage,
        "price": price,
        "qty_raw": qty_raw,
        "qty": qty,
        "tp": [],
        "sl": None,
    }

    # build TP
    if tp_targets and tp_splits and len(tp_targets) == len(tp_splits):
        rem = qty
        for t, w in zip(tp_targets, tp_splits):
            q = round_qty(symbol, qty * float(w), step)
            rem -= q
            plan["tp"].append({"stopPrice": round_price(symbol, float(t), tick), "qty": q})
        if rem > 0 and plan["tp"]:
            plan["tp"][-1]["qty"] = round_qty(symbol, plan["tp"][-1]["qty"] + rem, step)

    # SL
    if sl_price and sl_price > 0:
        plan["sl"] = {"stopPrice": round_price(symbol, float(sl_price), tick), "qty": qty}

    if dry_run:
        return {"ok": True, "executed": False, "plan": plan}

    # LIVE EXECUTION
    await set_leverage(symbol, leverage)
    entry = await place_market_order(symbol, side_up, qty, reduce_only=False)

    placed_tp: List[Any] = []
    for leg in plan["tp"]:
        if leg["qty"] > 0:
            placed_tp.append(await place_tp_market(symbol, side_up, leg["qty"], leg["stopPrice"]))

    placed_sl = None
    if plan["sl"] and plan["sl"]["qty"] > 0:
        placed_sl = await place_sl_market(symbol, side_up, plan["sl"]["qty"], plan["sl"]["stopPrice"])

    return {
        "ok": True,
        "executed": True,
        "entry": entry,
        "tp_orders": placed_tp,
        "sl_order": placed_sl,
        "plan": plan,
    }






































