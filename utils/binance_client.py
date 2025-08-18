# utils/binance_client.py
from __future__ import annotations
import os
import time
import threading
from typing import Callable, Any, Dict, Optional

from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException

_client: Optional[Client] = None
_client_lock = threading.Lock()

_ex_info_cache: Dict[str, Any] | None = None
_ex_info_ts: float = 0.0
_EX_TTL = float(os.getenv("EXCHANGEINFO_TTL_SEC", "1800"))  # 30m default

API_KEY = os.getenv("BINANCE_API_KEY", "") or ""
API_SECRET = os.getenv("BINANCE_API_SECRET", "") or ""

def get_client() -> Client:
    """
    Thread-safe singleton client (futures-enabled).
    Works for SPOT/FUTURES endpoints via python-binance unified client.
    """
    global _client
    with _client_lock:
        if _client is None:
            # recvWindow is controlled per-call; keep base client clean
            _client = Client(API_KEY, API_SECRET)
        return _client

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

# ---------- Futures health / metadata ----------

def futures_ping() -> bool:
    """
    Quick connectivity check to USD-M Futures API.
    Raises on failure; returns True on success.
    """
    client = get_client()
    try:
        # python-binance exposes futures_ping(); no params needed
        retry_call(lambda: client.futures_ping(), "futures_ping", tries=3)
        return True
    except (BinanceAPIException, BinanceRequestException) as e:
        raise
    except Exception as e:
        raise

def futures_exchange_info_safe() -> Dict[str, Any]:
    """
    Cached exchange info for futures (does not raise on refresh failure after cached).
    """
    global _ex_info_cache, _ex_info_ts
    now = time.time()
    if _ex_info_cache and (now - _ex_info_ts) < _EX_TTL:
        return _ex_info_cache
    client = get_client()
    data = retry_call(lambda: client.futures_exchange_info(), "futures_exchange_info", tries=3)
    _ex_info_cache = data or {}
    _ex_info_ts = now
    return _ex_info_cache or {}

# ---------- Prices ----------

def futures_mark_price(symbol: str) -> Dict[str, Any]:
    """
    Returns dict like: {'symbol': 'BTCUSDT', 'markPrice': '...', ...}
    """
    client = get_client()
    sym = (symbol or "").upper().strip()
    if not sym:
        raise ValueError("symbol required")
    return retry_call(lambda: client.futures_mark_price(symbol=sym), "futures_mark_price", tries=3)

# ---------- (Optional) account mode helpers ----------

def ensure_hedge_mode(enabled: bool = False) -> Optional[Dict[str, Any]]:
    """
    Enforce hedge mode on/off if BINANCE_FORCE_HEDGE_MODE=true.
    Safe to call on startup; ignores if keys missing.
    """
    v = str(os.getenv("BINANCE_FORCE_HEDGE_MODE", "false")).lower() in ("1","true","yes","y","on")
    if not v and not enabled:
        return None
    client = get_client()
    try:
        return retry_call(lambda: client.futures_change_multi_asset_margin("true" if enabled else "false"),
                          "futures_change_multi_asset_margin", tries=2)
    except Exception:
        return None



























