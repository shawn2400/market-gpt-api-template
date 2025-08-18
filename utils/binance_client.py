from __future__ import annotations
import os
import time
import threading
from typing import Callable, Any, Dict, Optional
import requests

from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException

_SPOT_HTTP_BASE = os.getenv("BINANCE_SPOT_HTTP_BASE", "https://api.binance.com").rstrip("/")
_FUT_HTTP_BASE  = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com").rstrip("/")

_client: Optional[Client] = None
_client_lock = threading.Lock()

_ex_info_cache: Dict[str, Any] | None = None
_ex_info_ts: float = 0.0
_EX_TTL = float(os.getenv("EXCHANGEINFO_TTL_SEC", "1800"))  # 30 דקות

_requests_session = requests.Session()
_requests_session.headers.update({
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "X-MBX-APIKEY": os.getenv("BINANCE_API_KEY", "")
})

def get_client() -> Client:
    global _client
    with _client_lock:
        if _client is None:
            api = os.getenv("BINANCE_API_KEY") or ""
            secret = os.getenv("BINANCE_API_SECRET") or ""
            _client = Client(api, secret)
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
        url = f"{_FUT_HTTP_BASE}/fapi/v1/ping"
        response = _requests_session.get(url, timeout=5)
        return response.status_code == 200
    except Exception:
        return False

def futures_mark_price(symbol: str) -> Dict[str, Any]:
    try:
        url = f"{_FUT_HTTP_BASE}/fapi/v1/premiumIndex"
        response = _requests_session.get(url, params={"symbol": symbol.upper()}, timeout=5)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return {"error": str(e)}

































