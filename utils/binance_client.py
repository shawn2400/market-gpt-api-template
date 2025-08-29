# utils/binance_client.py
from __future__ import annotations

import os
import hmac
import json
import math
import time
import threading
import logging
from typing import Any, Dict, Optional

import httpx
from hashlib import sha256

logger = logging.getLogger("algogpt.binance.client")

# ──────────────────────────────────────────────────────────────────────────────
# Config / ENV
# ──────────────────────────────────────────────────────────────────────────────

def _clean_env(s: Optional[str]) -> str:
    return (s or "").strip().strip('"').replace("\r", "").replace("\n", "").replace("\t", "")

API_KEY     = _clean_env(os.getenv("BINANCE_API_KEY"))
API_SECRET  = _clean_env(os.getenv("BINANCE_API_SECRET"))
BASE        = (os.getenv("BINANCE_FUTURES_HTTP_BASE") or "https://fapi.binance.com").rstrip("/")
RECV_WINDOW = int(os.getenv("BINANCE_RECV_WINDOW", "45000"))

DEFAULT_QTY_STEP  = float(os.getenv("DEFAULT_QTY_STEP",  "0.001"))
DEFAULT_PRICE_TICK= float(os.getenv("DEFAULT_PRICE_TICK","0.1"))

# ──────────────────────────────────────────────────────────────────────────────
# HTTP client (keep-alive)
# ──────────────────────────────────────────────────────────────────────────────

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

def _request(
    method: str,
    path: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    signed: bool = False,
) -> httpx.Response:
    url = f"{BASE}{path}"
    params = dict(params or {})

    if signed:
        params.setdefault("timestamp", _ts_ms())
        params.setdefault("recvWindow", RECV_WINDOW)
        # בחתימה העתיק: סדר פרמטרים לפי urlencode של httpx (שומר על סדר ההכנסה)
        # אך כדי להיות דטרמיניסטיים, נסדר ידנית:
        items = []
        for k, v in params.items():
            items.append(f"{k}={v}")
        qs = "&".join(items)
        sig = _sign(qs)
        params["signature"] = sig

    r = _CLIENT.request(method.upper(), url, params=params)
    # טיפול סטטוסים/שגיאות
    if r.status_code == 200:
        return r

    # Backoff מינימלי לפי Retry-After (למעלה השכבות הגבוהות כבר עושות ריווח)
    if r.status_code in (418, 429, 500, 502, 503, 504):
        ra = r.headers.get("Retry-After")
        if ra:
            try:
                time.sleep(min(10.0, float(ra)))
            except Exception:
                time.sleep(1.0)

    try:
        data = r.json()
    except Exception:
        r.raise_for_status()
        return r

    code = data.get("code")
    msg  = data.get("msg")
    # זרוק עם פרטים — השכבה הקוראת תציג שגיאה נקייה ללקוח
    raise RuntimeError(f"Binance error {code}: {msg}")

# ──────────────────────────────────────────────────────────────────────────────
# Public: Ping / Price / Filters / Leverage / Positions
# ──────────────────────────────────────────────────────────────────────────────

def fapi_ping() -> bool:
    r = _request("GET", "/fapi/v1/ping", signed=False)
    return r.status_code == 200

def futures_mark_price(symbol: str) -> Optional[float]:
    s = (symbol or "").strip().upper()
    if not s:
        return None
    r = _request("GET", "/fapi/v1/premiumIndex", params={"symbol": s}, signed=False)
    try:
        j = r.json()
        # חלק מהיישומים מחזירים "markPrice" כמחרוזת
        px = float(j.get("markPrice") or j.get("price"))
        return px if px > 0 else None
    except Exception as e:
        logger.error(f"[mark_price] parse failed for {s}: {e}")
        return None

def set_leverage(symbol: str, leverage: int) -> Dict[str, Any]:
    s = (symbol or "").strip().upper()
    lev = max(1, min(125, int(leverage)))
    r = _request("POST", "/fapi/v1/leverage", params={"symbol": s, "leverage": lev}, signed=True)
    return r.json()

def futures_open_positions() -> Optional[list]:
    # positionRisk מחזיר לכל הסימבולים; אפשר גם לסנן ב-client
    r = _request("GET", "/fapi/v2/positionRisk", signed=True)
    try:
        return r.json()
    except Exception:
        return None

def get_symbol_filters(symbol: str) -> Dict[str, Any]:
    """
    מחלץ tickSize/stepSize מה-ExchangeInfo ל-Futures.
    מחזיר מילון שטוח: {"tickSize": ..., "stepSize": ...}
    """
    s = (symbol or "").strip().upper()
    r = _request("GET", "/fapi/v1/exchangeInfo", params={"symbol": s}, signed=False)
    data = r.json()
    syms = data.get("symbols") or []
    if not syms:
        return {"tickSize": DEFAULT_PRICE_TICK, "stepSize": DEFAULT_QTY_STEP}
    filters = syms[0].get("filters") or []
    out = {"tickSize": DEFAULT_PRICE_TICK, "stepSize": DEFAULT_QTY_STEP}
    for f in filters:
        ftype = f.get("filterType")
        if ftype == "PRICE_FILTER":
            try:
                out["tickSize"] = float(f.get("tickSize") or DEFAULT_PRICE_TICK)
            except Exception:
                pass
        elif ftype in ("LOT_SIZE", "MARKET_LOT_SIZE"):
            try:
                out["stepSize"] = float(f.get("stepSize") or DEFAULT_QTY_STEP)
            except Exception:
                pass
    return out

# ──────────────────────────────────────────────────────────────────────────────
# Helpers: rounding
# ──────────────────────────────────────────────────────────────────────────────

def _floor_to_step(x: float, step: float) -> float:
    if step <= 0:
        return x
    return math.floor(x / step) * step

def _floor_to_tick(px: float, tick: float) -> float:
    if tick <= 0:
        return px
    return math.floor(px / tick) * tick

# ──────────────────────────────────────────────────────────────────────────────
# Orders (LIMIT GTX / IOC / FOK / reduceOnly / positionSide)
# ──────────────────────────────────────────────────────────────────────────────

def place_limit_order(
    *,
    symbol: str,
    side: str,                # "BUY"/"SELL"
    quantity: float,
    price: float,
    post_only: bool = False,  # True => TIF=GTX
    reduce_only: bool = False,
    position_side: Optional[str] = None,  # None/"LONG"/"SHORT" (Dual/Hedge Mode)
    time_in_force: Optional[str] = None,  # None/GTC/IOC/FOK/GTX
    new_order_resp_type: str = "RESULT",  # RESULT/ACK/FULL
    client_order_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    מיפוי מדויק ל-Binance USD-M Futures:
    - type=LIMIT
    - timeInForce: GTX (Post-Only), או IOC/FOK/GTC.
    - reduceOnly: bool
    - positionSide: נשלח רק אם סופק (Hedge Mode).
    """

    sym  = (symbol or "").strip().upper()
    sdir = (side   or "").strip().upper()
    if sdir not in ("BUY", "SELL"):
        raise ValueError("side must be BUY or SELL")

    # עיגול לפי פילטרים (עם Fallback)
    try:
        filt = get_symbol_filters(sym)
        tick = float(filt.get("tickSize", DEFAULT_PRICE_TICK))
        step = float(filt.get("stepSize", DEFAULT_QTY_STEP))
    except Exception:
        tick, step = DEFAULT_PRICE_TICK, DEFAULT_QTY_STEP

    qty   = max(_floor_to_step(float(quantity), step), step)
    px    = max(_floor_to_tick(float(price), tick), tick)

    # GTX (Post-Only) גובר על TIF שהגיע מבחוץ
    tif: str
    if post_only:
        tif = "GTX"
    else:
        tif = (time_in_force or "GTC").strip().upper()
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

    # reduceOnly זמין ב-Futures LIMIT
    if reduce_only:
        params["reduceOnly"] = "true"

    # positionSide — רק אם באמת צריך (Hedge Mode)
    if position_side:
        ps = position_side.strip().upper()
        if ps in ("LONG", "SHORT", "BOTH"):
            # במצב BOTH עדיף לא לשלוח בכלל; נשאיר רק LONG/SHORT
            if ps != "BOTH":
                params["positionSide"] = ps

    if client_order_id:
        params["newClientOrderId"] = client_order_id

    r = _request("POST", "/fapi/v1/order", params=params, signed=True)
    try:
        return r.json()
    except Exception as e:
        # אם לא JSON — נזרוק כטקסט
        raise RuntimeError(f"order response parse failed: {e}; raw={r.text}")

# ──────────────────────────────────────────────────────────────────────────────
# User Data Stream (listenKey keepalive)
# ──────────────────────────────────────────────────────────────────────────────

_listen_key: Optional[str] = None
_keepalive_thread: Optional[threading.Thread] = None
_keepalive_stop = threading.Event()

def start_user_stream_keepalive(period_sec: int = 1800) -> Optional[str]:
    """
    מייצר listenKey ושומר חי באמצעות thread שמבצע PUT כל period_sec.
    בטוח להפעלה מספר פעמים (idempotent).
    """
    global _listen_key, _keepalive_thread

    # אם כבר רץ — החזר את המפתח הנוכחי
    if _keepalive_thread and _keepalive_thread.is_alive() and _listen_key:
        return _listen_key

    # צור מפתח חדש
    try:
        r = _request("POST", "/fapi/v1/listenKey", signed=False)
        lk = r.json().get("listenKey")
        if not lk:
            raise RuntimeError("listenKey missing in response")
        _listen_key = lk
    except Exception as e:
        logger.error(f"[listenKey] create failed: {e}")
        return None

    _keepalive_stop.clear()

    def _run():
        # keepalive עד שנבקש לעצור
        while not _keepalive_stop.is_set():
            try:
                time.sleep(max(60, period_sec - 60))  # ריפוד קטן לפני פקיעת 60ד'
                _request("PUT", "/fapi/v1/listenKey", params={"listenKey": _listen_key}, signed=False)
                logger.debug({"event": "listenKey_keepalive"})
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
            _request("DELETE", "/fapi/v1/listenKey", params={"listenKey": _listen_key}, signed=False)
    except Exception as e:
        logger.warning({"event": "listenKey_delete_error", "error": str(e)})
    _listen_key = None
    _keepalive_thread = None


















































































































































