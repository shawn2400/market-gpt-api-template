from __future__ import annotations
import os
import time
import threading
from typing import Callable, Any, Dict, Optional

import requests
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException

_SPOT_HTTP_BASE = os.getenv("BINANCE_SPOT_HTTP_BASE", "https://api.binance.com").rstrip("/")
_FUT_HTTP_BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com").rstrip("/")

_client: Optional[Client] = None
_client_lock = threading.Lock()

_ex_info_cache: Optional[Dict[str, Any]] = None
_ex_info_ts: float = 0.0
_EX_TTL = float(os.getenv("EXCHANGEINFO_TTL_SEC", "1800"))  # 30 דקות

# הגדר session עם User-Agent
_requests_session = requests.Session()
_requests_session.headers.update({
    "User-Agent": "Mozilla/5.0",
})

def get_client() -> Client:
    global _client
    with _client_lock:
        if _client is None:
            api = os.getenv("BINANCE_API_KEY") or ""
            secret = os.getenv("BINANCE_API_SECRET") or ""
            _client = Client(api, secret, requests_params={"session": _requests_session})
            _client.API_URL = _SPOT_HTTP_BASE
            _client.FUTURES_URL = _FUT_HTTP_BASE
        return _client

def get_futures_client() -> Client:
    return get_client()

def _retry_call(fn: Callable[[], Any], label: str, tries: int = 3, delay: float = 0.5):
    last = None
    for i in range(tries):
        try:
            return fn()
        except (BinanceAPIException, BinanceRequestException, Exception) as e:
            last = e
            time.sleep(delay * (2 ** i))
    if last:
        raise last
    raise RuntimeError(f"{label} failed")

def futures_exchange_info_safe() -> Dict[str, Any]:
    global _ex_info_cache, _ex_info_ts
    now = time.time()
    if _ex_info_cache and (now - _ex_info_ts) < _EX_TTL:
        return _ex_info_cache
    client = get_futures_client()
    data = _retry_call(lambda: client.futures_exchange_info(), "futures_exchange_info", tries=3)
    _ex_info_cache = data or {}
    _ex_info_ts = now
    return _ex_info_cache

def futures_ping() -> bool:
    try:
        _retry_call(lambda: get_futures_client().futures_ping(), "futures_ping", tries=2)
        return True
    except Exception:
        return False

def futures_mark_price(symbol: str) -> Dict[str, Any]:
    sym = (symbol or "").upper()
    try:
        return _retry_call(lambda: get_futures_client().futures_mark_price(symbol=sym), "futures_mark_price", tries=3)
    except Exception:
        # fallback עם requests
        url = f"{_FUT_HTTP_BASE}/fapi/v1/premiumIndex?symbol={sym}"
        try:
            res = _requests_session.get(url, timeout=5)
            res.raise_for_status()
            return res.json()
        except Exception as e:
            raise RuntimeError(f"futures_mark_price failed via both client and requests: {e}")































