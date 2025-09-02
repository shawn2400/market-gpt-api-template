# utils/binance_client.py
from __future__ import annotations

import os
import hmac
import time
import random
import threading
import logging
from typing import Any, Dict, Optional, List
from hashlib import sha256
from decimal import Decimal, ROUND_DOWN, ROUND_UP, InvalidOperation
from collections import deque

import httpx
import pandas as pd

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
BINANCE_MAX_RETRIES = int(os.getenv("BINANCE_MAX_RETRIES", "5"))
BINANCE_BACKOFF_BASE = float(os.getenv("BINANCE_BACKOFF_BASE", "0.7"))

HTTP_MAX_CONNECTIONS = int(os.getenv("HTTP_MAX_CONNECTIONS", "64"))
HTTP_MAX_KEEPALIVE   = int(os.getenv("HTTP_MAX_KEEPALIVE", "32"))

# ברירות מחדל בטוחות אם לא הצלחנו להביא filters
DEFAULT_QTY_STEP_STR   = os.getenv("DEFAULT_QTY_STEP",  "0.001")
DEFAULT_PRICE_TICK_STR = os.getenv("DEFAULT_PRICE_TICK","0.1")
DEFAULT_MIN_NOTIONAL   = float(os.getenv("MIN_NOTIONAL_USDT", "5"))

# טריגר ברירת מחדל לפקודות מותנות
WORKING_TYPE  = (os.getenv("BINANCE_WORKING_TYPE") or "MARK_PRICE").strip().upper()  # MARK_PRICE / CONTRACT_PRICE
PRICE_PROTECT = str(os.getenv("BINANCE_PRICE_PROTECT", "false")).lower() in ("1", "true", "yes", "on")

# Leaky-Bucket להזמנות (QPS limiter)
ORD_BUCKET_SIZE = int(os.getenv("ORDERS_QPS_BUCKET", "8"))
ORD_BUCKET_WINDOW = float(os.getenv("ORDERS_BUCKET_WINDOW_SEC", "10"))
ORD_BACKOFF_BASE_MS = int(os.getenv("ORDER_BACKOFF_BASE_MS", "80"))
ORD_BACKOFF_MAX_MS  = int(os.getenv("ORDER_BACKOFF_MAX_MS", "1200"))

_HEADERS = {
    "X-MBX-APIKEY": API_KEY,
    "Accept": "application/json",
    "Accept-Encoding": "gzip",
    "User-Agent": "AlgoGPT/2 binance-client",
}
_CLIENT = httpx.Client(
    timeout=httpx.Timeout(HTTP_TIMEOUT_SEC),
    headers=_HEADERS,
    limits=httpx.Limits(max_keepalive_connections=HTTP_MAX_KEEPALIVE, max_connections=HTTP_MAX_CONNECTIONS),
    http2=False,
)

def _ts_ms() -> int:
    return int(time.time() * 1000)

def _sign(qs: str) -> str:
    return hmac.new(API_SECRET.encode(), qs.encode(), sha256).hexdigest()

# ──────────────────────────────────────────────────────────────────────────────
# Leaky-bucket gate (thread-safe)
# ──────────────────────────────────────────────────────────────────────────────
_order_gate_lock = threading.Lock()
_order_ts: deque[float] = deque(maxlen=max(ORD_BUCKET_SIZE, 1))

def _is_mutating_order_endpoint(method: str, path: str) -> bool:
    m = method.upper()
    if m not in ("POST", "DELETE"):
        return False
    p = path or ""
    return (
        p.endswith("/fapi/v1/order")
        or p.endswith("/fapi/v1/allOpenOrders")
        or p.endswith("/fapi/v1/leverage")
    )

def _order_leaky_bucket_gate():
    if ORD_BUCKET_SIZE <= 0:
        return
    while True:
        with _order_gate_lock:
            now = time.monotonic()
            # גרוף timestamps ישנים מחלון
            while _order_ts and (now - _order_ts[0]) > ORD_BUCKET_WINDOW:
                _order_ts.popleft()
            if len(_order_ts) < ORD_BUCKET_SIZE:
                _order_ts.append(now)
                return
            # נצטרך לישון עד שפנוי סל
            wait_for = ORD_BUCKET_WINDOW - (now - _order_ts[0])
        # מחוץ ללוק — ישנים
        wait_for = max(0.0, min(wait_for, ORD_BUCKET_WINDOW))
        time.sleep(wait_for + random.uniform(0.0, 0.03))

# ──────────────────────────────────────────────────────────────────────────────
# Core request with retries + backoff + jitter
# ──────────────────────────────────────────────────────────────────────────────
def _request(
    method: str,
    path: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    signed: bool = False,
    timeout: Optional[float] = None,
) -> httpx.Response:
    url = f"{BASE}{path}"
    attempt = 0
    last_exc: Optional[Exception] = None

    while attempt <= max(1, BINANCE_MAX_RETRIES):
        try:
            # Gate להזמנות בלבד (POST/DELETE order/*)
            if _is_mutating_order_endpoint(method, path):
                _order_leaky_bucket_gate()

            req_params = dict(params or {})
            if signed:
                req_params.setdefault("timestamp", _ts_ms())
                req_params.setdefault("recvWindow", RECV_WINDOW)
                # חתימה — שמירה על סדר הוספת הפרמטרים
                items = [f"{k}={req_params[k]}" for k in req_params.keys()]
                req_params["signature"] = _sign("&".join(items))

            r = _CLIENT.request(method.upper(), url, params=req_params, timeout=timeout or HTTP_TIMEOUT_SEC)

            if r.status_code == 200:
                return r

            # Backoff על קודי עומס/שגיאה
            if r.status_code in (418, 429, 500, 502, 503, 504):
                ra = r.headers.get("Retry-After")
                if ra:
                    delay = min(10.0, max(0.5, float(ra)))
                else:
                    base = BINANCE_BACKOFF_BASE * (2 ** attempt)
                    delay = min(10.0, base + random.uniform(0, 0.4))
                time.sleep(delay)
            else:
                # ייתן פרטים אם יש JSON
                try:
                    data = r.json()
                    raise RuntimeError(f"Binance error {data.get('code')}: {data.get('msg')}")
                except Exception:
                    r.raise_for_status()
        except Exception as e:
            last_exc = e
            # backoff קצר בין ניסיונות (ללא הגזמה)
            ms = min(ORD_BACKOFF_MAX_MS, ORD_BACKOFF_BASE_MS * (2 ** attempt))
            time.sleep(ms / 1000.0)
        attempt += 1

    if last_exc:
        raise last_exc
    raise RuntimeError("Unspecified Binance request failure")

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
    """
    נסיון בטוח להביא פילטרים עבור סימבול:
      1) /exchangeInfo?symbol=SYMBOL
      2) cache של exchangeInfo מלא
      3) fallback קשיח לערכי ברירת מחדל
    """
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

    # 3) fallback קשיח — עדיין ניתן לבצע, אבל יש סכנה ל-MIN_NOTIONAL
    out["minNotional"] = DEFAULT_MIN_NOTIONAL
    return out

# ──────────────────────────────────────────────────────────────────────────────
# Decimal helpers
# ──────────────────────────────────────────────────────────────────────────────
def _quantize_multiple(x: float | str | Decimal, step_str: str, rounding=ROUND_DOWN) -> Decimal:
    """מעגן את x למספר שלם של step (Decimal). תומך גם ב-'1e-3'."""
    try:
        q = Decimal(str(x)) if not isinstance(x, Decimal) else x
        step = Decimal(step_str)
        mult = (q / step).to_integral_value(rounding=rounding)
        val = (mult * step).quantize(step, rounding=ROUND_DOWN)
        return val
    except (InvalidOperation, ValueError):
        # חזרה ל-default אם קלט לא תקין
        q = Decimal("0")
        step = Decimal(step_str if step_str else "1")
        return (q / step).to_integral_value(rounding=rounding) * step

def _to_plain_str(d: Decimal) -> str:
    return format(d, "f")

# ──────────────────────────────────────────────────────────────────────────────
# Signed endpoints (balance/positions)
# ──────────────────────────────────────────────────────────────────────────────
def futures_position_risk() -> Optional[list]:
    try:
        return _request("GET", "/fapi/v2/positionRisk", signed=True).json()
    except Exception:
        return None

# שמירת תאימות לשם ישן אם קיים בקוד אחר
def futures_open_positions() -> Optional[list]:
    return futures_position_risk()

def futures_balance() -> list:
    try:
        data = _request("GET", "/fapi/v2/balance", signed=True).json()
        return data if isinstance(data, list) else []
    except Exception:
        return []

# ──────────────────────────────────────────────────────────────────────────────
# Klines helper (Pandas)
# ──────────────────────────────────────────────────────────────────────────────
def get_klines_df(symbol: str, interval: str = "15m", limit: int = 200) -> pd.DataFrame:
    s = (symbol or "").upper().strip()
    r = _request("GET", "/fapi/v1/klines", params={"symbol": s, "interval": interval, "limit": limit})
    arr = r.json()
    if not isinstance(arr, list) or not arr:
        return pd.DataFrame()
    cols = ["open_time","open","high","low","close","volume","close_time","qv","nTrades","taker_base","taker_quote","x"]
    df = pd.DataFrame(arr, columns=cols[:len(arr[0])])
    for c in ("open","high","low","close","volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df

# ──────────────────────────────────────────────────────────────────────────────
# Place LIMIT order (open position)
# ──────────────────────────────────────────────────────────────────────────────
def place_limit_order(
    *,
    symbol: str,
    side: str,                # BUY/SELL
    quantity: float,
    price: float,
    post_only: bool = False,  # GTX
    reduce_only: bool = False,
    position_side: Optional[str] = None,  # LONG/SHORT (Hedge) או None
    time_in_force: Optional[str] = None,  # GTC/IOC/FOK/GTX
    new_order_resp_type: str = "RESULT",
    client_order_id: Optional[str] = None,
) -> Dict[str, Any]:
    sym  = (symbol or "").strip().upper()
    sdir = (side   or "").strip().upper()
    if sdir not in ("BUY", "SELL"):
        raise ValueError("side must be BUY or SELL")

    # קבל filters + עיגון דיוק
    f = get_symbol_filters(sym)
    step_str = f.get("stepSizeStr", DEFAULT_QTY_STEP_STR)
    tick_str = f.get("tickSizeStr", DEFAULT_PRICE_TICK_STR)

    qty_dec = _quantize_multiple(quantity, step_str, rounding=ROUND_DOWN)
    if sdir == "SELL":
        px_dec = _quantize_multiple(price, tick_str, rounding=ROUND_UP)
    else:
        px_dec = _quantize_multiple(price, tick_str, rounding=ROUND_DOWN)

    # minQty
    min_qty = f.get("minQty")
    if isinstance(min_qty, (float, int)) and min_qty is not None:
        min_qty_dec = _quantize_multiple(Decimal(str(min_qty)), step_str, rounding=ROUND_UP)
        if qty_dec < min_qty_dec:
            qty_dec = min_qty_dec

    # MIN_NOTIONAL
    min_notional = f.get("minNotional") or DEFAULT_MIN_NOTIONAL
    notional = float(qty_dec * px_dec)
    if notional < float(min_notional):
        raise RuntimeError(
            f"MIN_NOTIONAL not met: notional={notional:.8f} < required={min_notional:.8f}. "
            f"Increase budget or leverage."
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
        "quantity": qty_str,   # ← string
        "price": px_str,       # ← string
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

# ──────────────────────────────────────────────────────────────────────────────
# Conditional (BRACKET) orders: STOP_MARKET / TAKE_PROFIT_MARKET
# ──────────────────────────────────────────────────────────────────────────────
def _align_trigger_price(desired: float, tick_str: str, side: str, *, is_stop: bool) -> Decimal:
    """
    Rounding direction chosen to be conservative:
      - STOP for SELL (long SL below): round DOWN
      - STOP for BUY  (short SL above): round UP
      - TP   for SELL (long TP above):  round UP
      - TP   for BUY  (short TP below): round DOWN
    """
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
    quantity: Optional[float] = None,     # אם None → closePosition=true
    reduce_only: bool = True,
    position_side: Optional[str] = None,  # LONG/SHORT
    working_type: Optional[str] = None,   # MARK_PRICE / CONTRACT_PRICE
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

    # יישור מחירי טריגר ל-tick לפי הכיוון/סוג
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
        # סגור את כל הפוזיציה בכיוון הנגדי כשהטריגר יופעל
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

# שם תאימות: בקוד יש שימוש place_stop_market
def place_stop_market(**kwargs) -> Dict[str, Any]:
    return place_stop_market_order(**kwargs)

def place_take_profit_market(**kwargs) -> Dict[str, Any]:
    kwargs = dict(kwargs)
    kwargs["order_type"] = "TAKE_PROFIT_MARKET"
    return _place_conditional_market(**kwargs)

# ─── Orders Management (Wrappers) ─────────────────────────────────────────────
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

def cancel_open_orders(symbol: str) -> Dict[str, Any]:
    params = {"symbol": symbol.upper()}
    return _request("DELETE", "/fapi/v1/allOpenOrders", params=params, signed=True).json()

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
    "set_leverage",
    "futures_position_risk",
    "futures_open_positions",
    "futures_balance",
    "get_klines_df",
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


































































































































































