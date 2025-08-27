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

# --- Official Host ONLY (avoid fapi1/2/3 WAF) ---
FAPI_HOST = os.getenv("BINANCE_FAPI_BASE", "https://fapi.binance.com").rstrip("/")
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
    return "application/json" in ctype

def _get_json(path: str, params: Optional[dict] = None, timeout: float = DEFAULT_TIMEOUT) -> Optional[dict]:
    """קריאת GET מה־Binance REST API הרשמי"""
    url = f"{FAPI_HOST}/{path.lstrip('/')}"
    try:
        with httpx.Client(timeout=timeout, headers={"User-Agent": "AlgoGPT/2.x"}, http2=False) as client:
            r = client.get(url, params=params)
        if not _is_json(r):
            logger.error(f"[BinanceHTTP] non-json response from {url} (status={r.status_code})")
            return None
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.error(f"[BinanceHTTP] {url} failed: {e}")
        return None

# --- Futures helpers ---
def fapi_ping() -> bool:
    try:
        return _get_json("fapi/v1/ping") is not None
    except Exception as e:
        logger.error(f"[Binance] fapi_ping failed: {e}")
        return False

def futures_mark_price(symbol: str) -> Optional[float]:
    """Mark Price עדכני עם fallback ל־WebSocket אם נדרש"""
    try:
        data = _get_json("fapi/v1/premiumIndex", params={"symbol": symbol.upper()})
        if data and "markPrice" in data:
            return float(data["markPrice"])
    except Exception as e:
        logger.error(f"[Binance] futures_mark_price HTTP failed for {symbol}: {e}")

    # --- fallback ל־WebSocket ---
    if ws_get_price:
        try:
            price = ws_get_price(symbol.upper())
            if price:
                logger.info(f"[BinanceWS] {symbol} via WS fallback: {price}")
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
    data = _get_json("fapi/v1/exchangeInfo")
    _futures_exchange_info_cache = data or {}
    return _futures_exchange_info_cache

def get_symbol_info(symbol: str, force_refresh: bool = False) -> Optional[Dict[str, Any]]:
    """מחזיר מידע מלא על סימבול אחד מתוך exchangeInfo"""
    info = futures_exchange_info_safe(force_refresh=force_refresh)
    if not info or "symbols" not in info:
        return None
    for s in info["symbols"]:
        if s.get("symbol") == symbol.upper():
            return s
    return None










































































































































