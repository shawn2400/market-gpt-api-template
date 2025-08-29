# utils/binance_client.py
from __future__ import annotations

import os
import hmac
import math
import time
import threading
import logging
from typing import Any, Dict, Optional
from hashlib import sha256

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

DEFAULT_QTY_STEP   = float(os.getenv("DEFAULT_QTY_STEP",  "0.001"))
DEFAULT_PRICE_TICK = float(os.getenv("DEFAULT_PRICE_TICK","0.1"))
EXINFO_TTL_SEC     = int(os.getenv("EXCHANGE_INFO_TTL_SEC", "900"))  # 15 דקות

_HEADERS = {
    "X-MBX-APIKEY": API_KEY,
    "Accept": "application/json",
    "Accept-Encoding": "gzip",
    "User-Agent": "AlgoGPT/2 binance-client",
}
_CLIENT = httpx.Client(
    timeout=httpx.Timeout(10.0),
    headers=_HEADERS,
    limits=httpx.Limits(max_keepalive_connections=32, max_connections=64),
    http2=False,
)

def _ts_ms() -> int:
    return int(time.time() * 1000)

def _sign(qs: str) -> str:
    return hmac.new(API_SECRET.encode(), qs.encode(), sha256).hexdigest()

def _request(method: str, path: str, *, params: Optional[Dict[str, Any]] = None, signed: bool = False) -> httpx.Response:
    """
    מבצע קריאת HTTP לסביבות Futures. כאשר signed=True מוסיף timestamp/recvWindow/חתימה.
    הערה: אנחנו בונים את מחרוזת החתימה באותו סדר שיישלח בפועל (dict שומר סדר הוספה בפייתון 3.7+).
    """
    url = f"{BASE}{path}"
    params = dict(params or {})
    if signed:
        params.setdefault("timestamp", _ts_ms())
        params.setdefault("recvWindow", RECV_WINDOW)
        # בנה query-string וחתום
        items = [f"{k}={params[k]}" for k in params.keys()]
        sig = _sign("&".join(items))
        params["signature"] = sig

    r = _CLIENT.request(method.upper(), url, params=params)

    if r.status_code == 200:
        return r

    # backoff קצר לשגיאות זמניות/Rate-limit
    if r.status_code in (418, 429, 500, 502, 503, 504):
        ra = r.headers.get("Retry-After")
        time.sleep(min(10.0, float(ra)) if ra else 1.0)

    # ננסה להעלות שגיאה עם פרטי Binance
    try:
        data = r.json()
    except Exception:
        r.raise_for_status()
        return r

    raise RuntimeError(f"Binance error {data.get('code')}: {data.get('msg')}")

# ──────────────────────────────────────────────────────────────────────────────
# Public: Ping / Price
# ──────────────────────────────────────────────────────────────────────────────

def fapi_ping() -> bool:
    return _request("GET", "/fapi/v1/ping").status_code == 200

def futures_mark_price(symbol: str) -> Optional[float]:
    s = (symbol or "").strip().upper()
    j = _request("GET", "/fapi/v1/premiumIndex", params={"symbol": s}).json()
    try:
        px = float(j.get("markPrice") or j.get("price"))
        return px if px > 0 else None
    except Exception:
        return None

# ──────────────────────────────────────────────────────────────────────────────
# exchangeInfo (עם Cache) + get_symbol_info
# ──────────────────────────────────────────────────────────────────────────────

_EX_INFO_CACHE: Dict[str, Any] = {"ts": 0.0, "data": None}
_EX_INFO_LOCK = threading.Lock()

def _fetch_exchange_info_full() -> dict:
    """
    מביא exchangeInfo מלא (ללא פרמטר symbol כדי לאפשר רשימת כל הסימבולים ל-/executor/symbols).
    """
    r = _request("GET", "/fapi/v1/exchangeInfo")
    return r.json()

def futures_exchange_info_safe(force_refresh: bool = False) -> dict:
    """
    מחזיר exchangeInfo עם Cache פנימי ל־EXINFO_TTL_SEC.
    force_refresh=True עוקף cache ומרענן מהשרת.
    """
    now = time.time()
    with _EX_INFO_LOCK:
        if (not force_refresh) and _EX_INFO_CACHE.get("data") and (now - _EX_INFO_CACHE["ts"] < EXINFO_TTL_SEC):
            return _EX_INFO_CACHE["data"]
        data = _fetch_exchange_info_full()
        _EX_INFO_CACHE["ts"] = now
        _EX_INFO_CACHE["data"] = data
        return data

def get_symbol_info(symbol: str, force_refresh: bool = False) -> Optional[dict]:
    """
    מאתר אובייקט סימבול מתוך exchangeInfo. מחזיר None אם לא נמצא.
    """
    info = futures_exchange_info_safe(force_refresh=force_refresh)
    sym = (symbol or "").upper()
    for s in info.get("symbols", []):
        if (s.get("symbol") or "").upper() == sym:
            return s
    return None

# ──────────────────────────────────────────────────────────────────────────────
# Filters / Leverage / Positions / Balance
# ──────────────────────────────────────────────────────────────────────────────

def get_symbol_filters(symbol: str) -> Dict[str, Any]:
    s = (symbol or "").strip().upper()
    data = _request("GET", "/fapi/v1/exchangeInfo", params={"symbol": s}).json()
    syms = data.get("symbols") or []
    if not syms:
        return {"tickSize": DEFAULT_PRICE_TICK, "stepSize": DEFAULT_QTY_STEP}
    filters = syms[0].get("filters") or []
    out = {"tickSize": DEFAULT_PRICE_TICK, "stepSize": DEFAULT_QTY_STEP}
    for f in filters:
        t = f.get("filterType")
        if t == "PRICE_FILTER":
            try:
                out["tickSize"] = float(f.get("tickSize") or DEFAULT_PRICE_TICK)
            except Exception:
                pass
        elif t in ("LOT_SIZE", "MARKET_LOT_SIZE"):
            try:
                out["stepSize"] = float(f.get("stepSize") or DEFAULT_QTY_STEP)
            except Exception:
                pass
    return out

def set_leverage(symbol: str, leverage: int) -> Dict[str, Any]:
    s = (symbol or "").strip().upper()
    lev = max(1, min(125, int(leverage)))
    return _request("POST", "/fapi/v1/leverage", params={"symbol": s, "leverage": lev}, signed=True).json()

def futures_open_positions() -> Optional[list]:
    try:
        return _request("GET", "/fapi/v2/positionRisk", signed=True).json()
    except Exception:
        return None

def futures_balance() -> list:
    """USD-M Futures wallet balances (used by /health_full)."""
    try:
        data = _request("GET", "/fapi/v2/balance", signed=True).json()
        return data if isinstance(data, list) else []
    except Exception:
        return []

# ──────────────────────────────────────────────────────────────────────────────
# Rounding helpers
# ──────────────────────────────────────────────────────────────────────────────

def _floor_to_step(x: float, step: float) -> float:
    return x if step <= 0 else (math.floor(x / step) * step)

def _floor_to_tick(px: float, tick: float) -> float:
    return px if tick <= 0 else (math.floor(px / tick) * tick)

# ──────────────────────────────────────────────────────────────────────────────
# Orders (LIMIT GTX / IOC / FOK / reduceOnly / positionSide)
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
    time_in_force: Optional[str] = None,  # GTC/IOC/FOK/GTX (GTX גובר אם post_only=True)
    new_order_resp_type: str = "RESULT",
    client_order_id: Optional[str] = None,
) -> Dict[str, Any]:
    sym  = (symbol or "").strip().upper()
    sdir = (side   or "").strip().upper()
    if sdir not in ("BUY", "SELL"):
        raise ValueError("side must be BUY or SELL")

    try:
        f = get_symbol_filters(sym)
        tick = float(f.get("tickSize", DEFAULT_PRICE_TICK))
        step = float(f.get("stepSize", DEFAULT_QTY_STEP))
    except Exception:
        tick, step = DEFAULT_PRICE_TICK, DEFAULT_QTY_STEP

    qty = max(_floor_to_step(float(quantity), step), step)
    px  = max(_floor_to_tick(float(price), tick), tick)

    tif = "GTX" if post_only else (time_in_force or "GTC").strip().upper()
    if tif not in ("GTC", "IOC", "FOK", "GTX"):
        tif = "GTC"

    params: Dict[str, Any] = {
        "symbol": sym,
        "side": sdir,
        "type": "LIMIT",
        "quantity": qty,
        "price": px,
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

def get_open_orders(symbol: Optional[str] = None) -> list:
    params = {}
    if symbol: params["symbol"] = symbol.upper()
    return _request("GET", "/fapi/v1/openOrders", params=params, signed=True).json()

# ─── User Data Stream (listenKey keepalive) ───────────────────────────────────

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






















































































































































