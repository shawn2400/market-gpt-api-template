# utils/binance_client.py
from __future__ import annotations
import os, time, threading
from typing import Any, Dict, Callable
from binance.client import Client

_client = None
_client_lock = threading.Lock()
_ex_info_cache: Dict[str, Any] | None = None
_ex_info_ts: float = 0.0
_EX_TTL = float(os.getenv("EXCHANGEINFO_TTL_SEC", "1800"))  # 30 דקות

def get_client() -> Client:
    global _client
    with _client_lock:
        if _client is None:
            api = os.getenv("BINANCE_API_KEY") or ""
            sec = os.getenv("BINANCE_API_SECRET") or ""
            _client = Client(api_key=api, api_secret=sec)
        return _client

# --- תאימות לאחור לקוד ישן שמייבא שמות שונים ---
def get_futures_client() -> Client:
    return get_client()

def futures_mark_price(symbol: str) -> Dict[str, Any]:
    c = get_client()
    return c.futures_mark_price(symbol=symbol)

# --- עזרי Retry/Cache ---
def retry_call(fn: Callable[[], Any], label: str, tries: int = 3, delay: float = 0.5):
    last = None
    for i in range(tries):
        try:
            return fn()
        except Exception as e:
            last = e
            time.sleep(delay * (2 ** i))
    raise last if last else RuntimeError(f"{label} failed")

def futures_exchange_info_safe() -> Dict[str, Any]:
    global _ex_info_cache, _ex_info_ts
    now = time.time()
    if _ex_info_cache and (now - _ex_info_ts) < _EX_TTL:
        return _ex_info_cache
    client = get_client()
    data = retry_call(lambda: client.futures_exchange_info(), "futures_exchange_info", tries=3)
    _ex_info_cache = data or {}
    _ex_info_ts = now
    return _ex_info_cache



























