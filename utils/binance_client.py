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

logger = logging.getLogger("algogpt.binance.client")

# ──────────────────────────────────────────────────────────────────────────────
# ENV / Config
# ──────────────────────────────────────────────────────────────────────────────

def _clean_env(s: Optional[str]) -> str:
    return (s or "").strip().strip('"').replace("\r", "").replace("\n", "").replace("\t", "")

API_KEY     = _clean_env(os.getenv("BINANCE_API_KEY"))
API_SECRET  = _clean_env(os.getenv("BINANCE_API_SECRET"))
BASE        = (os.getenv("BINANCE_FUTURES_HTTP_BASE") or "https://fapi.binance.com").rstrip("/")

# time-sync & recvWindow — נשתמש ב־utils.time_sync אם קיים
try:
    from utils.time_sync import server_time_ms, recv_window_ms
    _HAS_TIME_SYNC = True
except Exception:
    _HAS_TIME_SYNC = False

RECV_WINDOW = int(os.getenv("BINANCE_RECV_WINDOW", "45000"))  # fallback אם time_sync לא נטען
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
    if _HAS_TIME_SYNC:
        try:
            return int(server_time_ms())
        except Exception:
            pass
    return int(time.time() * 1000)

def _recv_window() -> int:
    if _HAS_TIME_SYNC:
        try:
            return int(recv_window_ms())
        except Exception:
            pass
    return int(RECV_WINDOW)

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
            while _order_ts and (now - _order_ts[0]) > ORD_BUCKET_WINDOW:
                _order_ts.popleft()
            if len(_order_ts) < ORD_BUCKET_SIZE:
                _order_ts.append(now)
                return
            wait_for = ORD_BUCKET_WINDOW - (now - _order_ts[0])
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
                req_params.setdefault("recvWindow", _recv_window())
                # חתימה — שמירה על סדר הוספת הפרמטרים
                items = [f"{k}={req_params[k]}" for k in req_params.keys()]
                req_params["signature"] = _sign("&".join(items))

            r = _CLIENT.request(method.upper(), url, params=req_params, timeout=timeout or HTTP_TIMEOUT_SEC)

            if r.status_code == 200:
                return r

            if r.status_code in (418, 429, 500, 502, 503, 504):
                ra = r.headers.get("Retry-After")
                if ra:
                    delay = min(10.0, max(0.5, float(ra)))
                else:
                    base = BINANCE_BACKOFF_BASE * (2 ** attempt)
                    delay = min(10.0, base + random.uniform(0, 0.4))
                time.sleep(delay)
            else:
                try:
                    data = r.json()
                    raise RuntimeError(f"Binance error {data.get('code')}: {data.get('msg')}")
                except Exception:
                    r.raise_for_status()
        except Exception as e:
            last_exc = e
            ms = min(ORD_BACKOFF_MAX_MS, ORD_BACKOFF_BASE_MS * (2 ** attempt))
            time.sleep(ms / 1000.0)
        attempt += 1

    if last_exc:
        raise last_exc
    raise RuntimeError("Unspecified Binance request failure")

# ──────────────────────────────────────────────────────────────────────────────
# Ping / Price
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
    """מעגן את x למספר שלם של step (Decimal). תומך גם ב'1e-3'."""
    try:
        q = Decimal(str(x)) if not isinstance(x, Decimal) else x
        step = Decimal(step_str)
        mult = (q / step).to_integral_value(rounding=rounding)
        val = (mult * step).quantize(step, rounding=ROUND_DOWN)
        return val
    except (InvalidOperation, ValueError):
        # fallback בטוח
        try:
            step = Decimal(step_str)
            return (Decimal(0) * step).quantize(step, rounding=ROUND_DOWN)
        except Exception:
            return Decimal("0")

# ──────────────────────────────────────────────────────────────────────────────
# Account / Balance / Leverage
# ──────────────────────────────────────────────────────────────────────────────
def futures_balance() -> List[Dict[str, Any]]:
    """USDT-M futures balance (v2)."""
    r = _request("GET", "/fapi/v2/balance", signed=True)
    return r.json()

def set_leverage(symbol: str, leverage: int) -> Dict[str, Any]:
    s = (symbol or "").upper()
    lev = max(1, min(int(leverage), 125))
    r = _request("POST", "/fapi/v1/leverage", params={"symbol": s, "leverage": lev}, signed=True)
    return r.json()

# ──────────────────────────────────────────────────────────────────────────────
# Orders
# ──────────────────────────────────────────────────────────────────────────────
def place_limit_order(
    *,
    symbol: str,
    side: str,             # BUY / SELL
    quantity: float,
    price: float,
    time_in_force: str = "GTC",
    post_only: bool = False,
    reduce_only: bool = False,
    position_side: Optional[str] = None,  # LONG/SHORT (Hedge) או None
    new_client_order_id: Optional[str] = None,
    new_order_resp_type: str = "RESULT",
) -> Dict[str, Any]:
    s = symbol.upper().strip()
    params: Dict[str, Any] = {
        "symbol": s,
        "side": side.upper(),
        "type": "LIMIT",
        "timeInForce": time_in_force,
        "quantity": f"{quantity:.18f}".rstrip("0").rstrip("."),
        "price": f"{price:.18f}".rstrip("0").rstrip("."),
        "newOrderRespType": new_order_resp_type,
        "reduceOnly": "true" if reduce_only else "false",
    }
    if position_side:
        params["positionSide"] = position_side.upper()
    if post_only:
        params["timeInForce"] = "GTX"  # Post-only דרך GTX
    if new_client_order_id:
        params["newClientOrderId"] = new_client_order_id

    r = _request("POST", "/fapi/v1/order", params=params, signed=True)
    return r.json()

def place_stop_market_order(
    *,
    symbol: str,
    side: str,
    stop_price: float,
    quantity: Optional[float] = None,     # None → closePosition=true
    reduce_only: bool = True,
    position_side: Optional[str] = None,
    working_type: Optional[str] = None,   # MARK_PRICE / CONTRACT_PRICE
    price_protect: Optional[bool] = None,
    new_client_order_id: Optional[str] = None,
    new_order_resp_type: str = "RESULT",
) -> Dict[str, Any]:
    s = symbol.upper().strip()
    params: Dict[str, Any] = {
        "symbol": s,
        "side": side.upper(),
        "type": "STOP_MARKET",
        "stopPrice": f"{stop_price:.18f}".rstrip("0").rstrip("."),
        "newOrderRespType": new_order_resp_type,
    }
    if quantity is None:
        params["closePosition"] = "true"
    else:
        params["quantity"] = f"{quantity:.18f}".rstrip("0").rstrip(".")
        params["reduceOnly"] = "true" if reduce_only else "false"
    if position_side:
        params["positionSide"] = position_side.upper()
    params["workingType"] = (working_type or WORKING_TYPE)
    if price_protect is None:
        price_protect = PRICE_PROTECT
    params["priceProtect"] = "true" if price_protect else "false"
    if new_client_order_id:
        params["newClientOrderId"] = new_client_order_id

    r = _request("POST", "/fapi/v1/order", params=params, signed=True)
    return r.json()

def place_take_profit_market(
    *,
    symbol: str,
    side: str,
    stop_price: float,
    quantity: Optional[float] = None,     # None → closePosition=true
    reduce_only: bool = True,
    position_side: Optional[str] = None,
    working_type: Optional[str] = None,
    price_protect: Optional[bool] = None,
    new_client_order_id: Optional[str] = None,
    new_order_resp_type: str = "RESULT",
) -> Dict[str, Any]:
    s = symbol.upper().strip()
    params: Dict[str, Any] = {
        "symbol": s,
        "side": side.upper(),
        "type": "TAKE_PROFIT_MARKET",
        "stopPrice": f"{stop_price:.18f}".rstrip("0").rstrip("."),
        "newOrderRespType": new_order_resp_type,
    }
    if quantity is None:
        params["closePosition"] = "true"
    else:
        params["quantity"] = f"{quantity:.18f}".rstrip("0").rstrip(".")
        params["reduceOnly"] = "true" if reduce_only else "false"
    if position_side:
        params["positionSide"] = position_side.upper()
    params["workingType"] = (working_type or WORKING_TYPE)
    if price_protect is None:
        price_protect = PRICE_PROTECT
    params["priceProtect"] = "true" if price_protect else "false"
    if new_client_order_id:
        params["newClientOrderId"] = new_client_order_id

    r = _request("POST", "/fapi/v1/order", params=params, signed=True)
    return r.json()

# ──────────────────────────────────────────────────────────────────────────────
# User Stream (listenKey) keepalive
# ──────────────────────────────────────────────────────────────────────────────
_LISTEN_KEY: Optional[str] = None
_LISTEN_KEY_LOCK = threading.Lock()
_LISTEN_BG: Optional[threading.Thread] = None
_LISTEN_STOP = threading.Event()

def _create_listen_key() -> str:
    r = _request("POST", "/fapi/v1/listenKey")
    js = r.json()
    return str(js.get("listenKey"))

def _keepalive_listen_key(lk: str) -> None:
    _request("PUT", "/fapi/v1/listenKey", params={"listenKey": lk})

def _delete_listen_key(lk: str) -> None:
    try:
        _request("DELETE", "/fapi/v1/listenKey", params={"listenKey": lk})
    except Exception:
        pass

def start_user_stream_keepalive(period_sec: int = 1800) -> Optional[str]:
    global _LISTEN_KEY, _LISTEN_BG
    with _LISTEN_KEY_LOCK:
        if _LISTEN_BG and _LISTEN_BG.is_alive():
            return _LISTEN_KEY
        try:
            _LISTEN_KEY = _create_listen_key()
        except Exception as e:
            logger.warning({"event": "listenkey_create_failed", "error": str(e)})
            _LISTEN_KEY = None
            return None
        _LISTEN_STOP.clear()

        def _run():
            while not _LISTEN_STOP.wait(timeout=max(60, period_sec - 60)):
                try:
                    if _LISTEN_KEY:
                        _keepalive_listen_key(_LISTEN_KEY)
                except Exception as e:
                    logger.warning({"event": "listenkey_keepalive_failed", "error": str(e)})
                    try:
                        _LISTEN_KEY = _create_listen_key()
                    except Exception:
                        pass

        t = threading.Thread(target=_run, name="listenkey_keepalive", daemon=True)
        t.start()
        _LISTEN_BG = t
        logger.info({"event": "listenkey_keepalive_started"})
        return _LISTEN_KEY

def stop_user_stream() -> None:
    global _LISTEN_KEY, _LISTEN_BG
    _LISTEN_STOP.set()
    if _LISTEN_BG and _LISTEN_BG.is_alive():
        try:
            _LISTEN_BG.join(timeout=1.0)
        except Exception:
            pass
    with _LISTEN_KEY_LOCK:
        if _LISTEN_KEY:
            try:
                _delete_listen_key(_LISTEN_KEY)
            except Exception:
                pass
        _LISTEN_KEY = None
        _LISTEN_BG = None
        logger.info({"event": "listenkey_keepalive_stopped"})

# ──────────────────────────────────────────────────────────────────────────────
# __all__
# ──────────────────────────────────────────────────────────────────────────────
__all__ = [
    "DEFAULT_QTY_STEP_STR", "DEFAULT_PRICE_TICK_STR", "DEFAULT_MIN_NOTIONAL",
    "fapi_ping", "futures_mark_price", "futures_balance",
    "futures_exchange_info_safe", "get_symbol_filters",
    "set_leverage",
    "place_limit_order", "place_stop_market_order", "place_take_profit_market",
    "_quantize_multiple",
    "start_user_stream_keepalive", "stop_user_stream",
]



































































































































































