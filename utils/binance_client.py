# utils/binance_client.py
import os, time, threading
from typing import Any, Dict, Callable
from binance.client import Client
from binance.exceptions import BinanceAPIException

_client = None
_lock = threading.Lock()
_ex_info_cache: Dict[str, Any] | None = None
_ex_info_ts = 0.0
_EX_TTL = float(os.getenv("EXCHANGEINFO_TTL_SEC", "1800"))

def get_client() -> Client:
    global _client
    with _lock:
        if _client is None:
            api = os.getenv("BINANCE_API_KEY", "")
            secret = os.getenv("BINANCE_API_SECRET", "")
            _client = Client(api, secret)
        return _client

# תאימות לאחור: יש קוד שמייבא זאת
def get_futures_client() -> Client:
    return get_client()

def retry_call(fn: Callable[[], Any], label: str, tries: int = 3, delay: float = 0.5):
    last = None
    for i in range(tries):
        try:
            return fn()
        except Exception as e:
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
    cli = get_client()
    data = retry_call(lambda: cli.futures_exchange_info(), "futures_exchange_info", tries=3)
    _ex_info_cache = data or {}
    _ex_info_ts = now
    return _ex_info_cache

def futures_mark_price(symbol: str) -> Dict[str, Any]:
    cli = get_client()
    try:
        return retry_call(lambda: cli.futures_mark_price(symbol=symbol), "futures_mark_price")
    except BinanceAPIException as e:
        return {"error": str(e), "symbol": symbol}



























