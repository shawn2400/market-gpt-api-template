# utils/binance_client.py
from __future__ import annotations
import os, time, threading
from typing import Any, Dict, Callable, Optional

from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException

_client: Optional[Client] = None
_lock = threading.Lock()

_BACKOFF_BASE = float(os.getenv("BINANCE_BACKOFF_BASE", "0.7"))
_MAX_TRIES    = int(os.getenv("BINANCE_MAX_RETRIES", "5"))
_RECV_WINDOW  = int(os.getenv("BINANCE_RECV_WINDOW", "10000"))

def _mk_client() -> Client:
    api = os.getenv("BINANCE_API_KEY", "") or ""
    sec = os.getenv("BINANCE_API_SECRET", "") or ""
    # שים לב: זהו client סינכרוני (תואם לקוד שלך שמשתמש ב-to_thread)
    c = Client(api_key=api, api_secret=sec)
    # עדיף לעבוד רק מול Futures
    c.API_URL = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")
    return c

def get_futures_client() -> Client:
    global _client
    with _lock:
        if _client is None:
            _client = _mk_client()
        return _client

def _retry(label: str, fn: Callable[[], Any], tries: int = _MAX_TRIES):
    delay = _BACKOFF_BASE
    last = None
    for i in range(tries):
        try:
            return fn()
        except (BinanceAPIException, BinanceRequestException, Exception) as e:
            last = e
            if i == tries - 1:
                break
            time.sleep(delay)
            delay *= 2
    if last:
        raise last
    raise RuntimeError(f"{label} failed (no exception captured)")

def futures_ping() -> bool:
    c = get_futures_client()
    try:
        _retry("futures_ping", lambda: c.futures_ping())
        return True
    except Exception:
        return False

def futures_server_time() -> Dict[str, Any]:
    c = get_futures_client()
    return _retry("futures_time", lambda: c.futures_time())

def futures_mark_price(symbol: str) -> Dict[str, Any]:
    c = get_futures_client()
    return _retry(
        "futures_mark_price",
        lambda: c.futures_mark_price(symbol=symbol, recvWindow=_RECV_WINDOW),
    )

def futures_exchange_info_safe() -> Dict[str, Any]:
    c = get_futures_client()
    return _retry("futures_exchange_info", lambda: c.futures_exchange_info())

def ensure_hedge_mode(force: bool = False) -> Optional[bool]:
    """
    אם BINANCE_FORCE_HEDGE_MODE=true — ננסה לאכוף Hedge Mode.
    """
    if not force and str(os.getenv("BINANCE_FORCE_HEDGE_MODE", "false")).lower() not in ("1","true","yes"):
        return None
    c = get_futures_client()
    try:
        pos = _retry("futures_get_position_mode", lambda: c.futures_get_position_mode())
        # pos = {'dualSidePosition': True/False}
        dual_now = bool(pos.get("dualSidePosition"))
        if not dual_now:
            _retry("futures_change_position_mode", lambda: c.futures_change_position_mode(dualSidePosition=True))
        return True
    except Exception:
        return False



























