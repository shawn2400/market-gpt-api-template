# utils/binance_client.py
from __future__ import annotations
import os, logging
from typing import Any, Optional, Dict
import httpx

logger = logging.getLogger("algogpt.binance")

# --- Keys ---
BINANCE_API_KEY = (os.getenv("BINANCE_API_KEY") or "").strip()
BINANCE_API_SECRET = (os.getenv("BINANCE_API_SECRET") or "").strip()
USE_TESTNET = os.getenv("BINANCE_TESTNET", "0").lower() in ("1", "true", "yes")

# --- Hosts ---
FAPI_HOSTS = [
    os.getenv("BINANCE_FAPI_BASE", "https://fapi.binance.com").rstrip("/"),
    "https://fapi1.binance.com",
    "https://fapi2.binance.com",
    "https://fapi3.binance.com",
]
HTTP_BASE = os.getenv("BINANCE_HTTP_BASE", "https://api.binance.com").rstrip("/")

DEFAULT_TIMEOUT = float(os.getenv("BINANCE_HTTP_TIMEOUT", "8.0"))

# --- Fallback ל־WS ---
try:
    from utils.ws_fallback import get_price as ws_get_price
except ImportError:
    ws_get_price = None

# --- Helpers ---
def _is_json(r: httpx.Response) -> bool:
    ctype = (r.headers.get("Content-Type") or "").lower()
    return ctype.startswith("application/json")

def _get_json(path: str, params: Optional[dict] = None, timeout: float = DEFAULT_TIMEOUT) -> dict:
    """קריאת GET עם fallback בין כמה hosts"""
    last_err: Optional[Exception] = None
    for base in FAPI_HOSTS:
        url = f"{base}/{path.lstrip('/')}"
        try:
            with httpx.Client(timeout=timeout, headers={"User-Agent": "AlgoGPT/2.x"}, http2=False) as client:
                r = client.get(url, params=params)
            if not _is_json(r):
                raise RuntimeError(f"non-json response from {url}")
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            logger.warning(f"[BinanceHTTP] {url} failed: {e}")
            continue
    raise RuntimeError(f"All Binance hosts failed: {last_err}")

# --- Futures helpers ---
def fapi_ping() -> bool:
    try:
        _get_json("fapi/v1/ping")
        return True
    except Exception as e:
        logger.error(f"[Binance] fapi_ping failed: {e}")
        return False

def futures_mark_price(symbol: str) -> Optional[float]:
    """Mark Price עדכני עם fallback ל־WebSocket אם נדרש"""
    try:
        data = _get_json("fapi/v1/premiumIndex", params={"symbol": symbol.upper()})
        if "markPrice" in data:
            return float(data["markPrice"])
    except Exception as e:
        logger.error(f"[Binance] futures_mark_price HTTP failed for {symbol}: {e}")

    # --- fallback ל־WebSocket ---
    if ws_get_price:
        try:
            price = ws_get_price(symbol.upper())
            if price:
                logger.info(f"[BinanceWS] {symbol} price via WS fallback: {price}")
                return float(price)
        except Exception as e:
            logger.error(f"[BinanceWS] fallback failed for {symbol}: {e}")
    return None

# --- Exchange Info ---
_futures_exchange_info_cache: Optional[Dict[str, Any]] = None

def futures_exchange_info_safe(force_refresh: bool = False) -> Dict[str, Any]:
    global _futures_exchange_info_cache
    if _futures_exchange_info_cache and not force_refresh:
        return _futures_exchange_info_cache
    _futures_exchange_info_cache = _get_json("fapi/v1/exchangeInfo")
    return _futures_exchange_info_cache








































































































































