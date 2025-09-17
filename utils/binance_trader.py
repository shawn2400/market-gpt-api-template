# utils/binance_trade.py
from __future__ import annotations
import os, time, hmac, hashlib
from typing import Any, Dict, List, Optional, Tuple

import httpx

try:
    from utils.binance_client import get_price as _get_price_util, futures_exchange_info_safe
except Exception:
    _get_price_util = None
    futures_exchange_info_safe = None

BINANCE_FAPI = os.getenv("BINANCE_FAPI_BASE", "https://fapi.binance.com")

def _api_keys() -> Tuple[str, str]:
    k = os.getenv("BINANCE_API_KEY", "").strip()
    s = os.getenv("BINANCE_API_SECRET", "").strip()
    if not k or not s:
        raise RuntimeError("BINANCE_API_KEY / BINANCE_API_SECRET missing")
    return k, s

def _sign(params: Dict[str, Any], secret: str) -> str:
    q = "&".join(f"{k}={params[k]}" for k in sorted(params.keys()))
    return hmac.new(secret.encode(), q.encode(), hashlib.sha256).hexdigest()

async def _request(method: str, path: str, params: Dict[str, Any] | None = None, signed: bool = True, timeout: float = 10.0) -> Any:
    params = dict(params or {})
    headers: Dict[str, str] = {}
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

# -------- exchange filters --------
_symbol_filters_cache: Dict[str, Dict[str, float]] = {}

async def _load_exchange_info() -> Dict[str, Any]:
    if callable(futures_exchange_info_safe):
        try:
            info = futures_exchange_info_safe(force_refresh=False)
            if info:
                return info
        except Exception:
            pass
    return await _request("GET", "/fapi/v1/exchangeInfo", signed=False)

def _parse_filters(sym_info: Dict[str, Any]) -> Dict[str, float]:
    out = {"stepSize": 0.001, "minQty": 0.0, "tickSize": 0.01}
    for f in sym_info.get("filters", []):
        if f.get("filterType") == "LOT_SIZE":
            out["stepSize"] = float(f.get("stepSize", out["stepSize"]))
            out["minQty"]   = float(f.get("minQty",   out["minQty"]))
        if f.get("filterType") == "PRICE_FILTER":
            out["tickSize"] = float(f.get("tickSize", out["tickSize"]))
    return out

async def get_symbol_filters(symbol: str) -> Dict[str, float]:
    s = symbol.upper()
    if s in _symbol_filters_cache:
        return _symbol_filters_cache[s]
    info = await _load_exchange_info()
    for sym in info.get("symbols", []):
        if sym.get("symbol") == s:
            f = _parse_filters(sym)
            _symbol_filters_cache[s] = f
            return f
    f = {"stepSize": 0.001, "minQty": 0.0, "tickSize": 0.01}
    _symbol_filters_cache[s] = f
    return f

def _round_step_down(x: float, step: float) -> float:
    if step <= 0: return x
    return (int((x + 1e-12) / step)) * step

def round_qty(qty: float, step: float, min_qty: float) -> float:
    q = _round_step_down(qty, step)
    return q if q >= min_qty else 0.0

def round_price(price: float, tick: float) -> float:
    return _round_step_down(price, tick)

# -------- low-level orders --------
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

# -------- defaults (ENV) --------
def _env_bps_csv(var: str, default: str) -> List[float]:
    raw = (os.getenv(var, default) or "").strip()
    out: List[float] = []
    for p in raw.split(","):
        p = p.strip()
        if not p: continue
        out.append(float(p))
    return out

def _env_floats_csv(var: str, default: str) -> List[float]:
    return _env_bps_csv(var, default)

def _default_tp_bps() -> List[float]:
    # ברירת מחדל: 60/120/200 bps => 0.6%, 1.2%, 2.0%
    return _env_bps_csv("DEFAULT_TP_BPS", "60,120,200")

def _default_tp_splits() -> List[float]:
    # ברירת מחדל: 0.34/0.33/0.33
    return _env_floats_csv("DEFAULT_TP_SPLITS", "0.34,0.33,0.33")

def _default_sl_bps() -> float:
    # ברירת מחדל: 80bps = 0.8%
    return float(os.getenv("DEFAULT_SL_BPS", "80"))

# -------- plan & execute --------
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
        raise ValueError("leverage must be between 1 and 125")
    if budget_usd <= 0:
        raise ValueError("budget_usd must be > 0")
    side_up = side.upper()
    if side_up not in ("BUY", "SELL"):
        raise ValueError("side must be BUY or SELL")

    price = await get_price(symbol)
    filters = await get_symbol_filters(symbol)
    step, tick, min_qty = float(filters["stepSize"]), float(filters["tickSize"]), float(filters["minQty"])

    notional = budget_usd * leverage
    qty_raw = notional / price
    qty = round_qty(qty_raw, step, min_qty)
    if qty <= 0:
        raise ValueError("calculated qty is zero; increase budget or leverage")

    # ---- build TP/SL (defaults if missing) ----
    dir_sign = 1 if side_up == "BUY" else -1

    if not tp_targets:
        bps_list = _default_tp_bps()
        if dir_sign > 0:
            tp_targets = [price * (1.0 + bps/10000.0) for bps in bps_list]
        else:
            tp_targets = [price * (1.0 - bps/10000.0) for bps in bps_list]
    if not tp_splits:
        tp_splits = _default_tp_splits()

    # normalize splits
    splits_sum = sum(tp_splits) if tp_splits else 0.0
    if splits_sum > 1.0 + 1e-9:
        raise ValueError("sum(tp_splits) must be <= 1")

    # SL default
    if not sl_price or sl_price <= 0:
        sl_bps = _default_sl_bps()
        if dir_sign > 0:
            sl_price = price * (1.0 - sl_bps/10000.0)
        else:
            sl_price = price * (1.0 + sl_bps/10000.0)

    # round & allocate
    tp_legs: List[Dict[str, float]] = []
    rem = qty
    for t, w in zip(tp_targets, tp_splits):
        q_leg = round_qty(qty * float(w), step, 0.0)
        rem -= q_leg
        tp_legs.append({"stopPrice": round_price(float(t), tick), "qty": q_leg})
    if rem > 0 and tp_legs:
        tp_legs[-1]["qty"] = round_qty(tp_legs[-1]["qty"] + rem, step, 0.0)

    sl_leg = {"stopPrice": round_price(float(sl_price), tick), "qty": qty}

    plan = {
        "symbol": symbol.upper(),
        "side": side_up,
        "leverage": leverage,
        "entry_price": price,
        "qty_raw": qty_raw,
        "qty": qty,
        "tp": tp_legs,
        "sl": sl_leg,
    }

    if dry_run:
        return {"ok": True, "executed": False, "plan": plan}

    # ---- LIVE ----
    await set_leverage(symbol, leverage)
    entry = await place_market_order(symbol, side_up, qty, reduce_only=False)

    placed_tp: List[Any] = []
    for leg in tp_legs:
        if leg["qty"] > 0:
            placed_tp.append(await place_tp_market(symbol, side_up, leg["qty"], leg["stopPrice"]))

    placed_sl = None
    if sl_leg["qty"] > 0:
        placed_sl = await place_sl_market(symbol, side_up, sl_leg["qty"], sl_leg["stopPrice"])

    return {"ok": True, "executed": True, "entry": entry, "tp_orders": placed_tp, "sl_order": placed_sl, "plan": plan}







































