# utils/binance_client.py
from __future__ import annotations
import os, logging
from typing import Any, Optional, Dict
import httpx
import hmac, hashlib, time

logger = logging.getLogger("algogpt.binance")

# --- Keys ---
BINANCE_API_KEY = (os.getenv("BINANCE_API_KEY") or "").strip()
BINANCE_API_SECRET = (os.getenv("BINANCE_API_SECRET") or "").strip()
USE_TESTNET = os.getenv("BINANCE_TESTNET", "0").lower() in ("1", "true", "yes")

# --- Hosts ---
FAPI_BASE = os.getenv("BINANCE_FAPI_BASE", "https://fapi.binance.com").rstrip("/")
HTTP_BASE = os.getenv("BINANCE_HTTP_BASE", "https://api.binance.com").rstrip("/")

DEFAULT_TIMEOUT = float(os.getenv("BINANCE_HTTP_TIMEOUT", "8.0"))

# --- Fallback ל־WS ---
try:
    from utils.ws_fallback import get_price as ws_get_price
except ImportError:
    ws_get_price = None


# --- Helpers ---
def _signed_request(method: str, path: str, params: dict | None = None) -> dict:
    """קריאת REST חתומה עם HMAC SHA256"""
    if not BINANCE_API_KEY or not BINANCE_API_SECRET:
        raise RuntimeError("Binance API keys missing")

    ts = int(time.time() * 1000)
    params = params or {}
    params["timestamp"] = ts

    query = "&".join([f"{k}={v}" for k, v in params.items()])
    sig = hmac.new(
        BINANCE_API_SECRET.encode(), query.encode(), hashlib.sha256
    ).hexdigest()
    query += f"&signature={sig}"

    url = f"{FAPI_BASE}/{path.lstrip('/')}"
    headers = {"X-MBX-APIKEY": BINANCE_API_KEY}

    with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
        r = client.request(method.upper(), url, params=query, headers=headers)
        r.raise_for_status()
        return r.json()


def _public_request(path: str, params: dict | None = None) -> dict:
    url = f"{FAPI_BASE}/{path.lstrip('/')}"
    with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
        r = client.get(url, params=params)
        r.raise_for_status()
        return r.json()


# --- Public ---
def fapi_ping() -> bool:
    try:
        _public_request("fapi/v1/ping")
        return True
    except Exception as e:
        logger.error(f"[Binance] fapi_ping failed: {e}")
        return False


def futures_mark_price(symbol: str) -> Optional[float]:
    """מחזיר Mark Price עדכני עם fallback ל־WS"""
    try:
        data = _public_request("fapi/v1/premiumIndex", {"symbol": symbol.upper()})
        if "markPrice" in data:
            return float(data["markPrice"])
    except Exception as e:
        logger.error(f"[Binance] futures_mark_price error {symbol}: {e}")

    if ws_get_price:
        try:
            return float(ws_get_price(symbol.upper()))
        except Exception as e:
            logger.error(f"[BinanceWS] fallback failed for {symbol}: {e}")
    return None


_futures_exchange_info_cache: Optional[Dict[str, Any]] = None

def futures_exchange_info_safe(force_refresh: bool = False) -> Dict[str, Any]:
    global _futures_exchange_info_cache
    if _futures_exchange_info_cache and not force_refresh:
        return _futures_exchange_info_cache
    _futures_exchange_info_cache = _public_request("fapi/v1/exchangeInfo")
    return _futures_exchange_info_cache


def get_symbol_info(symbol: str, force_refresh: bool = False) -> Optional[dict]:
    """שולף מידע על סימבול מסוים מתוך exchangeInfo"""
    info = futures_exchange_info_safe(force_refresh=force_refresh)
    for s in info.get("symbols", []):
        if s.get("symbol") == symbol.upper():
            return s
    return None


def futures_open_positions() -> list[dict]:
    """שליפת פוזיציות פתוחות ב-Futures"""
    try:
        return _signed_request("GET", "fapi/v2/positionRisk")
    except Exception as e:
        logger.error(f"[Binance] futures_open_positions failed: {e}")
        return []











































































































































