# utils/binance_client.py
from __future__ import annotations

import os
import hmac
import time
import threading
import logging
import random
from typing import Any, Dict, Optional
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
BINANCE_MAX_RETRIES = int(os.getenv("BINANCE_MAX_RETRIES", "5"))

# HTTP limits from env
HTTP_MAX_CONNECTIONS = int(os.getenv("HTTP_MAX_CONNECTIONS", "64"))
HTTP_MAX_KEEPALIVE   = int(os.getenv("HTTP_MAX_KEEPALIVE", "32"))

# Safe fallbacks
DEFAULT_QTY_STEP_STR   = os.getenv("DEFAULT_QTY_STEP",  "0.001")
DEFAULT_PRICE_TICK_STR = os.getenv("DEFAULT_PRICE_TICK","0.1")
DEFAULT_MIN_NOTIONAL   = float(os.getenv("MIN_NOTIONAL_USDT", "5"))

# Trigger defaults
WORKING_TYPE  = (os.getenv("BINANCE_WORKING_TYPE") or "MARK_PRICE").strip().upper()
PRICE_PROTECT = str(os.getenv("BINANCE_PRICE_PROTECT", "false")).lower() in ("1", "true", "yes", "on")

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
# Orders Leaky-Bucket (QPS limiter) + Backoff
# ──────────────────────────────────────────────────────────────────────────────
_ORDERS_BUCKET = int(os.getenv("ORDERS_QPS_BUCKET", "8"))
_ORDERS_WINDOW = int(os.getenv("ORDERS_BUCKET_WINDOW_SEC", "10"))
_BACKOFF_BASE_MS = int(os.getenv("ORDER_BACKOFF_BASE_MS", "80"))
_BACKOFF_MAX_MS  = int(os.getenv("ORDER_BACKOFF_MAX_MS", "1200"))

_order_times: deque[float] = deque(maxlen=max(128, _ORDERS_BUCKET * 4))
_order_lock = threading.Lock()

def _should_gate(method: str, path: str) -> bool:
    # מגביל קריאות שמשנות הזמנות
    p = path or ""
    m = (method or "").upper()
    return (("/fapi/v1/order" in p) or ("/fapi/v1/allOpenOrders" in p)) and (m in ("POST", "DELETE"))

def _order_gate() -> None:
    if _ORDERS_BUCKET <= 0:
        return
    with _order_lock:
        now = time.time()
        # ניקה חלון ישן
        while _order_times and (now - _order_times[0] > _ORDERS_WINDOW):
            _order_times.popleft()
        if len(_order_times) >= _ORDERS_BUCKET:
            wait = _ORDERS_WINDOW - (now - _order_times[0]) + random.uniform(0.0, 0.05)
            if wait > 0:
                time.sleep(min(wait, _ORDERS_WINDOW))
        _order_times.append(time.time())

def _calc_backoff(i: int, retry_after: Optional[str]) -> float:
    if retry_after:
        try:
            return float(retry_after)
        except Exception:
            pass
    ms = min(_BACKOFF_MAX_MS, _BACKOFF_BASE_MS * (2 ** i)) + int(50 * random.random())
    return max(0.05, ms / 1000.0)

# ──────────────────────────────────────────────────────────────────────────────
# Core Request with retries
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
    params = dict(params or {})

    if signed:
        params.setdefault("timestamp", _ts_ms())
        params.setdefault("recvWindow", RECV_WINDOW)
        # שמור סדר פרמטרים לחתימה
        items = [f"{k}={params[k]}"

































































































































































