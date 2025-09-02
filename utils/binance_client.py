# utils/binance_client.py
from __future__ import annotations

import os
import hmac
import time
import threading
import logging
import random
from typing import Any, Dict, Optional, List
from hashlib import sha256
from decimal import Decimal, ROUND_DOWN, ROUND_UP, InvalidOperation
from collections import deque

import httpx

logger = logging.getLogger("algogpt.binance.client")

# ──────────────────────────────────────────────────────────────────────────────
# ENV / Config
# ──────────────────────────────────────────────────────────────────────────────

def _clean_env(s: Optional[str]) -> str:
    return (s or "").strip().strip('"').replace("\r", "").replace("\n", "").replace("\t", "")

API_KEY     = _clean_env(os.getenv("BINANCE_API_KEY"))
API_SECRET  = _clean_env(os.getenv("BINANCE_API_SECRET"))
BASE        = (os.getenv("BINANCE_FUTURES_HTTP_BASE") or "https://fapi.binance.com").rstrip("/")
RECV_WINDOW = int(os.getenv("BINANCE_RECV_WINDOW", "20000"))
HTTP_TIMEOUT_SEC = float(os.getenv("BINANCE_HTTP_TIMEOUT", "8.0"))

# ברירות מחדל לפילטרים
DEFAULT_QTY_STEP_STR   = os.getenv("DEFAULT_QTY_STEP",  "0.001")
DEFAULT_PRICE_TICK_STR = os.getenv("DEFAULT_PRICE_TICK","0.1")
DEFAULT_MIN_NOTIONAL   = float(os.getenv("MIN_NOTIONAL_USDT", "5"))

# Working type / price protect
WORKING_TYPE  = (os.getenv("BINANCE_WORKING_TYPE") or "MARK_PRICE").strip().upper()
PRICE_PROTECT = str(os.getenv("BINANCE_PRICE_PROTECT", "false")).lower() in ("1", "true", "yes", "on")

# Leaky-bucket להזמנות
ORDERS_QPS_BUCKET       = int(os.getenv("ORDERS_QPS_BUCKET", "8"))
ORDERS_BUCKET_WINDOW_SEC = float(os.getenv("ORDERS_BUCKET_WINDOW_SEC", "10"))
ORDER_BACKOFF_BASE_MS    = float(os.getenv("ORDER_BACKOFF_BASE_MS", "80"))
ORDER_BACKOFF_MAX_MS     = float(os.getenv("ORDER_BACKOFF_MAX_MS", "1200"))

_HEADERS = {
    "X-MBX-APIKEY": API_KEY,
    "Accept": "application/json",
    "Accept-Encoding": "gzip",
    "User-Agent": "AlgoGPT/2 binance-client",
}
_CLIENT = httpx.Client(
    timeout=httpx.Timeout(HTTP_TIMEOUT_SEC),
    headers=_HEADERS,
    limits=httpx.Limits(max_keepalive_connections=32, max_connections=64),
    http2=False,
)

def _ts_ms() -> int:
    return int(time.time() * 1000)

def _sign(qs: str) -> str:
    return hmac.new(API_SECRET.encode(), qs.encode(), sha256).hexdigest()

# ─── Leaky Bucket (Thread-safe) ───────────────────────────────────────────────
_orders_lock = threading.Lock()
_orders_times: deque = deque()  # timestamps (float)

def _is_order_endpoint(method: str, path: str) -> bool:
    m = method.upper()
    p = path.strip()
    if p == "/fapi/v1/order" and m in ("POST", "DELETE", "GET"):
        return True
    if p == "/fapi/v1/allOpenOrders" and m == "DELETE":
        return True
    if p in ("/fapi/v1/leverage",):
        return True
    return False

def _orders_rate_limit_guard(method: str, path: str):
    if not _is_order_endpoint(method, path):
        return
    now = time.time()
    window = ORDERS_BUCKET_WINDOW_SEC
    cap = max(1, ORDERS_QPS_BUCKET)

    with _orders_lock:
        # ניקוי חלון
        while _orders_times and (now - _orders_times[0] > window):
            _orders_times.popleft()

        # אם מלא — השהייה קצרה (דלי נוזל)
        while len(_orders_times) >= cap:
            sleep_for = min(0.25, ( _orders_times[0] + window - now ))
            time.sleep(max(0.02, sleep_for))
            now = time.time()
            while _orders_times and (now - _orders_times[0] > window):
                _orders_times.popleft()

        # סימון הזמנה נוכחית
        _orders_times.append(now)

def _request(
    method: str,
    path: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    signed: bool = False,
    timeout: Optional[float] = None,
) -> httpx.Response:
    url = f"{BASE}{path}"
    params = dict(params or {})

    if signed:
        params.setdefault("timestamp", _ts_ms())
        params.setdefault("recvWindow", RECV_WINDOW)
        items = [f"{k}={params[k]}" for k in params.keys()]
        params["signature"] = _sign("&".join(items))

    # Rate-limit להזמנות
    _orders_rate_limit_guard(method, path)

    # בקשה
    r = _CLIENT.request(method.upper(), url, params=params, timeout=timeout or HTTP_TIMEOUT_SEC)

    if r.status_code == 200:
        return r

    # Backoff + jitter לפי קוד
    if r.status_code in (418, 429, 500, 502, 503, 504):
        ra = r.headers.get("Retry-After")
        if ra:
            try:
                time.sleep(min(10.0, float(ra)))
            except Exception:
                time.sleep(1.0)
        else:
            base = ORDER_BACKOFF_BASE_MS / 1000.0
            mx   = ORDER_BACKOFF_MAX_MS  / 1000.0
            time.sleep(min(mx, base + random.random() * base))

    try:
        data = r.json()
    except Exception:
        r.raise_for_status()
        return r

    raise RuntimeError(f"Binance error {data.get('code')}: {data.get('msg')}")

# ──────────────────────────────────────────────────────────────────────────────
# Public: Ping / Price
# ──────────────────────────────────────────────────────────────────────────────

def fapi_ping(tries: int = 3, per_try_timeout: float = 3.0) -> bool:
    for i in range(max(1, tries)):
        try:
            r = _CLIENT.get(f"{BASE}/fapi/v1/ping", timeout=per_try_timeout)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(min(2.0, 0.4 * (2 ** i)))
    try:
        r = _CLIENT.get(f"{BASE}/fapi/v1/time", timeout=per_try_timeout)
        return (r.status_code == 200) and ("serverTime" in r.text)
    except Exception:
        return False

def futures_mark_price(symbol: str) -> Optional[float]:
    s = (symbol or "").strip().upper()
    last_err: Optional[Exception] = None
    try:
        j = _request("GET", "/fapi/v1/premiumIndex", params={"symbol": s}).json()
        px = float(j.get("markPrice") or 0)
        if px > 0:
            return px
    except Exception as e:
        last_err = e

    try:
        j2 = _request("GET", "/fapi/v1/ticker/price", params={"symbol": s}).json()
        px2 = float(j2.get("price") or 0)
        if px2 > 0:
            return px2
    except Exception as e2:
        last_err = e2

    try:
        from utils.ws_fallback import get_price, is_price_fresh
        px3 = get_price(s)
        if px3 and is_price_fresh(s, max_age_sec=30):
            return float(px3)
    except Exception:
        pass

    logger.warning({"event": "mark_price_unavailable", "symbol": s, "error": str(last_err) if last_err else None})
    return None

# ──────────────────────────────────────────────────────────────────────────────
# exchangeInfo (Cache) + filters
# ──────────────────────────────────────────────────────────────────────────────

_EX_INFO_CACHE: Dict[str, Any] = {"ts": 0.0, "data": None}
_EX_INFO_LOCK = threading.Lock()

def _fetch_exchange_info_full() -> dict:
    return _request("GET", "/fapi/v1/exchangeInfo").json()

def futures_exchange_info_safe(force_refresh: bool = False) -> dict:
    import time as _t
    now = _t.time()
    ttl = int(os.getenv("EXCHANGE_INFO_TTL_SEC", "900"))
    with _EX_INFO_LOCK:
        if (not force_refresh) and _EX_INFO_CACHE.get("data") and (now - _EX_INFO_CACHE["ts"] < ttl):
            return _EX_INFO_CACHE["data"]
        data = _fetch_exchange_info_full()
        _EX_INFO_CACHE.update({"ts": now, "data": data})
        return data

def _decimals_from_step_str(step: str) -> int:
    s = (step or "").strip()
    if "e" in s.lower():
        d = Decimal(s)
        tup = d.as_tuple()
        return max(0, -tup.exponent)
    if "." not in s:
        return 0
    s = s.rstrip("0")
    return len(s.split(".")[1]) if "." in s else 0

def get_symbol_filters(symbol: str) -> Dict[str, Any]:
    s = (symbol or "").strip().upper()
    out = {
        "tickSizeStr": DEFAULT_PRICE_TICK_STR,
        "stepSizeStr": DEFAULT_QTY_STEP_STR,
        "tickDecimals": _decimals_from_step_str(DEFAULT_PRICE_TICK_STR),
        "stepDecimals": _decimals_from_step_str(DEFAULT_QTY_STEP_STR),
        "minQty": None,
        "minNotional": None,
        "pricePrecision": None,
        "quantityPrecision": None,
        "is_valid": False,
    }
    # 1) לפי סימבול
    try:
        data = _request("GET", "/fapi/v1/exchangeInfo", params={"symbol": s}).json()
        syms = data.get("symbols") or []
        if syms:
            info = syms[0]
            out["pricePrecision"]    = info.get("pricePrecision")
            out["quantityPrecision"] = info.get("quantityPrecision")
            for f in (info.get("filters") or []):
                t = f.get("filterType")
                if t == "PRICE_FILTER":
                    ts = f.get("tickSize") or DEFAULT_PRICE_TICK_STR
                    out["tickSizeStr"]  = ts
                    out["tickDecimals"] = _decimals_from_step_str(ts)
                elif t in ("LOT_SIZE", "MARKET_LOT_SIZE"):
                    ss = f.get("stepSize") or DEFAULT_QTY_STEP_STR
                    out["stepSizeStr"]  = ss
                    out["stepDecimals"] = _decimals_from_step_str(ss)
                    try:
                        out["minQty"] = float(f.get("minQty")) if f.get("minQty") is not None else None
                    except Exception:
                        out["minQty"] = None
                elif t in ("MIN_NOTIONAL", "NOTIONAL"):
                    try:
                        out["minNotional"] = float(
                            f.get("notional")
                            or f.get("minNotional")
                            or DEFAULT_MIN_NOTIONAL
                        )
                    except Exception:
                        out["minNotional"] = DEFAULT_MIN_NOTIONAL
            out["is_valid"] = True
            return out
    except Exception as e:
        logger.warning({"event": "exchange_info_symbol_failed", "symbol": s, "error": str(e)})

    # 2) מה־cache המלא
    try:
        all_info = futures_exchange_info_safe()
        for info in (all_info.get("symbols") or []):
            if (info.get("symbol") or "").upper() == s:
                out["pricePrecision"]    = info.get("pricePrecision")
                out["quantityPrecision"] = info.get("quantityPrecision")
                for f in (info.get("filters") or []):
                    t = f.get("filterType")
                    if t == "PRICE_FILTER":
                        ts = f.get("tickSize") or DEFAULT_PRICE_TICK_STR
                        out["tickSizeStr"]  = ts
                        out["tickDecimals"] = _decimals_from_step_str(ts)
                    elif t in ("LOT_SIZE", "MARKET_LOT_SIZE"):
                        ss = f.get("stepSize") or DEFAULT_QTY_STEP_STR
                        out["stepSizeStr"]  = ss
                        out["stepDecimals"] = _decimals_from_step_str(ss)
                        try:
                            out["minQty"] = float(f.get("minQty")) if f.get("minQty") is not None else None
                        except Exception:
                            out["minQty"] = None
                    elif t in ("MIN_NOTIONAL", "NOTIONAL"):
                        try:
                            out["minNotional"] = float(
                                f.get("notional")
                                or f.get("minNotional")
                                or DEFAULT_MIN_NOTIONAL
                            )
                        except Exception:
                            out["minNotional"] = DEFAULT_MIN_NOTIONAL
                out["is_valid"] = True
                return out
    except Exception as e:
        logger.warning({"event": "exchange_info_cache_failed", "symbol": s, "error": str(e)})

    # 3) fallback קשיח
    out["minNotional"] = DEFAULT_MIN_NOTIONAL
    return out

# ──────────────────────────────────────────────────────────────────────────────
# Decimal helpers
# ──────────────────────────────────────────────────────────────────────────────

def _quantize_multiple(x: float | str | Decimal, step_str: str, rounding=ROUND_DOWN) -> Decimal:
    try:
        q = Decimal(str(x)) if not isinstance(x, Decimal) else x
        step = Decimal(step_str)
        mult = (q / step).to_integral_value(rounding=rounding)
        val = (mult * step).quantize(step, rounding=ROUND_DOWN)
        return val
    except (InvalidOperation, ValueError):
        q = Decimal("0")
        step = Decimal(step_str if step_str else "1")
        return (q / step).to_integral_value(rounding=rounding) * step

def _to_plain_str(d: Decimal) -> str:
    return format(d, "f")

# ──────────────────────────────────────────────────────────────────────────────
# Signed endpoints (open/close/balance)
# ──────────────────────────────────────────────────────────────────────────────

def set_leverage(symbol: str, leverage: int) -> Dict[str, Any]:
    s = (symbol or "").strip().upper()
    lev = max(1, min(125, int(leverage)))
    return _request("POST", "/fapi/v1/leverage", params={"symbol": s, "leverage": lev}, signed=True).json()

def futures_open_positions() -> Optional[list]:
    try:
        return _request("GET", "/fapi/v2/positionRisk", signed=True).json()
    except Exception:
        return None

def futures_position_risk() -> Optional[list]:
    # alias ידידותי לשם שהקוד משתמש בו
    return futures_open_positions()

def futures_balance() -> list:
    try:
        data = _request("GET", "/fapi/v2/balance", signed=True).json()
        return data if isinstance(data, list) else []
    except Exception:
        return []

# ──────────────────────────────────────────────────────────────────────────────
# Public klines helper (DataFrame)
# ──────────────────────────────────────────────────────────────────────────────

def get_klines_df(symbol: str, interval: str = "15m", limit: int = 200):
    import pandas as pd  # import מקומי כדי למנוע זמן import עיקרי
    s = (symbol or "").strip().upper()
    j = _request("GET", "/fapi/v1/klines", params={"symbol": s, "interval": interval, "limit": int(limit)}).json()
    if not isinstance(j, list) or not j:
        return pd.DataFrame()
    cols = ["open_time","open","high","low","close","volume","close_time","qv","nTrades","taker_base","taker_quote","x"]
    df = pd.DataFrame(j, columns=cols[:len(j[0])])
    for c in ("open","high","low","close","volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df

# ──────────────────────────────────────────────────────────────────────────────
# Place / Cancel orders
# ──────────────────────────────────────────────────────────────────────────────

def place_limit_order(
    *,
    symbol: str,
    side: str,                # BUY/SELL
    quantity: float,
    price: float,
    post_only: bool = False,  # GTX
    reduce_only: bool = False,
    position_side: Optional[str] = None,  # LONG/SHORT
    time_in_force: Optional[str] = None,  # GTC/IOC/FOK/GTX
    new_order_resp_type: str = "RESULT",
    client_order_id: Optional[str] = None,
) -> Dict[str, Any]:
    sym  = (symbol or "").strip().upper()
    sdir = (side   or "").strip().upper()
    if sdir not in ("BUY", "SELL"):
        raise ValueError("side must be BUY or SELL")

    f = get_symbol_filters(sym)
    step_str = f.get("stepSizeStr", DEFAULT_QTY_STEP_STR)
    tick_str = f.get("tickSizeStr", DEFAULT_PRICE_TICK_STR)

    qty_dec = _quantize_multiple(quantity, step_str, rounding=ROUND_DOWN)
    if sdir == "SELL":
        px_dec = _quantize_multiple(price, tick_str, rounding=ROUND_UP)
    else:
        px_dec = _quantize_multiple(price, tick_str, rounding=ROUND_DOWN)

    min_qty = f.get("minQty")
    if isinstance(min_qty, (float, int)) and min_qty is not None:
        from decimal import Decimal as _D
        min_qty_dec = _quantize_multiple(_D(str(min_qty)), step_str, rounding=ROUND_UP)
        if qty_dec < min_qty_dec:
            qty_dec = min_qty_dec

    min_notional = f.get("minNotional") or DEFAULT_MIN_NOTIONAL
    notional = float(qty_dec * px_dec)
    if notional < float(min_notional):
        raise RuntimeError(
            f"MIN_NOTIONAL not met: notional={notional:.8f} < required={min_notional:.8f}. Increase budget or leverage."
        )

    qty_str = _to_plain_str(qty_dec)
    px_str  = _to_plain_str(px_dec)

    tif = "GTX" if post_only else (time_in_force or "GTC").strip().upper()
    if tif not in ("GTC", "IOC", "FOK", "GTX"):
        tif = "GTC"

    params: Dict[str, Any] = {
        "symbol": sym,
        "side": sdir,
        "type": "LIMIT",
        "quantity": qty_str,
        "price": px_str,
        "timeInForce": tif,
        "newOrderRespType": new_order_resp_type,
    }
    if reduce_only:
        params["reduceOnly"] = "true"
    if position_side:
        ps = position_side.strip().upper()
        if ps in ("LONG", "SHORT"):
            params["positionSide"] = ps
    if client_order_id:
        params["newClientOrderId"] = client_order_id

    return _request("POST", "/fapi/v1/order", params=params, signed=True).json()

def _align_trigger_price(desired: float, tick_str: str, side: str, *, is_stop: bool) -> Decimal:
    sdir = (side or "").upper()
    if is_stop:
        rnd = ROUND_DOWN if sdir == "SELL" else ROUND_UP
    else:
        rnd = ROUND_UP if sdir == "SELL" else ROUND_DOWN
    return _quantize_multiple(desired, tick_str, rounding=rnd)

def _place_conditional_market(
    *,
    order_type: str,          # "STOP_MARKET" | "TAKE_PROFIT_MARKET"
    symbol: str,
    side: str,                # BUY/SELL
    stop_price: float,
    quantity: Optional[float] = None,
    reduce_only: bool = True,
    position_side: Optional[str] = None,
    working_type: Optional[str] = None,
    price_protect: Optional[bool] = None,
    new_order_resp_type: str = "RESULT",
    client_order_id: Optional[str] = None,
) -> Dict[str, Any]:
    sym  = (symbol or "").strip().upper()
    sdir = (side   or "").strip().upper()
    if sdir not in ("BUY", "SELL"):
        raise ValueError("side must be BUY or SELL")

    f = get_symbol_filters(sym)
    step_str = f.get("stepSizeStr", DEFAULT_QTY_STEP_STR)
    tick_str = f.get("tickSizeStr", DEFAULT_PRICE_TICK_STR)

    is_stop = (order_type == "STOP_MARKET")
    stop_dec = _align_trigger_price(float(stop_price), tick_str, sdir, is_stop=is_stop)
    stop_str = _to_plain_str(stop_dec)

    params: Dict[str, Any] = {
        "symbol": sym,
        "side": sdir,
        "type": order_type,
        "stopPrice": stop_str,
        "newOrderRespType": new_order_resp_type,
        "workingType": (working_type or WORKING_TYPE),
    }

    if price_protect is None:
        if PRICE_PROTECT:
            params["priceProtect"] = "true"
    else:
        if price_protect:
            params["priceProtect"] = "true"

    if position_side:
        ps = position_side.strip().upper()
        if ps in ("LONG", "SHORT"):
            params["positionSide"] = ps

    if quantity is None:
        params["closePosition"] = "true"
    else:
        qty_dec = _quantize_multiple(quantity, step_str, rounding=ROUND_DOWN)
        params["quantity"] = _to_plain_str(qty_dec)
        if reduce_only:
            params["reduceOnly"] = "true"

    if client_order_id:
        params["newClientOrderId"] = client_order_id

    return _request("POST", "/fapi/v1/order", params=params, signed=True).json()

def place_stop_market_order(**kwargs) -> Dict[str, Any]:
    kwargs = dict(kwargs)
    kwargs["order_type"] = "STOP_MARKET"
    return _place_conditional_market(**kwargs)

def place_stop_market(**kwargs) -> Dict[str, Any]:
    # alias היסטורי
    return place_stop_market_order(**kwargs)

def place_take_profit_market(**kwargs) -> Dict[str, Any]:
    kwargs = dict(kwargs)
    kwargs["order_type"] = "TAKE_PROFIT_MARKET"
    return _place_conditional_market(**kwargs)

def get_order(symbol: str, order_id: Optional[int] = None, client_id: Optional[str] = None) -> Dict[str, Any]:
    if not order_id and not client_id:
        raise ValueError("must provide order_id or client_id")
    params = {"symbol": symbol.upper()}
    if order_id: params["orderId"] = int(order_id)
    if client_id: params["origClientOrderId"] = client_id
    return _request("GET", "/fapi/v1/order", params=params, signed=True).json()

def cancel_order(symbol: str, order_id: Optional[int] = None, client_id: Optional[str] = None) -> Dict[str, Any]:
    if not order_id and not client_id:
        raise ValueError("must provide order_id or client_id")
    params = {"symbol": symbol.upper()}
    if order_id: params["orderId"] = int(order_id)
    if client_id: params["origClientOrderId"] = client_id
    return _request("DELETE", "/fapi/v1/order", params=params, signed=True).json()

def cancel_open_orders(symbol: str) -> List[Dict[str, Any]]:
    params = {"symbol": symbol.upper()}
    j = _request("DELETE", "/fapi/v1/allOpenOrders", params=params, signed=True).json()
    return j if isinstance(j, list) else []

def get_open_orders(symbol: Optional[str] = None) -> list:
    params = {}
    if symbol: params["symbol"] = symbol.upper()
    return _request("GET", "/fapi/v1/openOrders", params=params, signed=True).json()

# ─── User Data Stream ─────────────────────────────────────────────────────────

_listen_key: Optional[str] = None
_keepalive_thread: Optional[threading.Thread] = None
_keepalive_stop = threading.Event()

def start_user_stream_keepalive(period_sec: int = 1800) -> Optional[str]:
    global _listen_key, _keepalive_thread
    if _keepalive_thread and _keepalive_thread.is_alive() and _listen_key:
        return _listen_key
    try:
        lk = _request("POST", "/fapi/v1/listenKey").json().get("listenKey")
        if not lk:
            raise RuntimeError("listenKey missing")
        _listen_key = lk
    except Exception as e:
        logger.error(f"[listenKey] create failed: {e}")
        return None

    _keepalive_stop.clear()

    def _run():
        while not _keepalive_stop.is_set():
            try:
                time.sleep(max(60, period_sec - 60))
                _request("PUT", "/fapi/v1/listenKey", params={"listenKey": _listen_key})
            except Exception as e:
                logger.warning({"event": "listenKey_keepalive_error", "error": str(e)})
                time.sleep(10)

    _keepalive_thread = threading.Thread(target=_run, name="binance-listenkey-keepalive", daemon=True)
    _keepalive_thread.start()
    return _listen_key

def stop_user_stream() -> None:
    global _listen_key, _keepalive_thread
    _keepalive_stop.set()
    try:
        if _listen_key:
            _request("DELETE", "/fapi/v1/listenKey", params={"listenKey": _listen_key})
    except Exception as e:
        logger.warning({"event": "listenKey_delete_error", "error": str(e)})
    _listen_key = None
    _keepalive_thread = None

# ──────────────────────────────────────────────────────────────────────────────
# Back-compat exports
# ──────────────────────────────────────────────────────────────────────────────

def _floor_to_step_dec(x: float | str, step_str: str):
    return _quantize_multiple(x, step_str, rounding=ROUND_DOWN)

def _ceil_to_tick_dec(x: float | str, tick_str: str):
    return _quantize_multiple(x, tick_str, rounding=ROUND_UP)

def _floor_to_tick_dec(x: float | str, tick_str: str):
    return _quantize_multiple(x, tick_str, rounding=ROUND_DOWN)

to_decimal_str = _to_plain_str
_to_decimal_str = _to_plain_str

__all__ = [
    "fapi_ping",
    "futures_mark_price",
    "futures_exchange_info_safe",
    "get_symbol_filters",
    "get_klines_df",
    "set_leverage",
    "futures_open_positions",
    "futures_position_risk",
    "futures_balance",
    "place_limit_order",
    "place_stop_market_order",
    "place_stop_market",
    "place_take_profit_market",
    "get_order",
    "cancel_order",
    "cancel_open_orders",
    "get_open_orders",
    "start_user_stream_keepalive",
    "stop_user_stream",
    "_quantize_multiple",
    "_to_plain_str",
    "_floor_to_step_dec",
    "_ceil_to_tick_dec",
    "_floor_to_tick_dec",
]
































































































































































