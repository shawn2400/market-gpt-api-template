# utils/binance_client.py
from __future__ import annotations
import os, logging
from typing import Any, Optional, Dict
import httpx
from binance.client import Client

logger = logging.getLogger("algogpt.binance")

# --- Keys ---
BINANCE_API_KEY = (os.getenv("BINANCE_API_KEY") or "").strip().replace("\n","").replace("\r","")
BINANCE_API_SECRET = (os.getenv("BINANCE_API_SECRET") or "").strip().replace("\n","").replace("\r","")
USE_TESTNET = (os.getenv("BINANCE_TESTNET", "false").strip().lower() in ("1","true","yes"))

# --- Hosts ---
_BINANCE_FAPI_BASE = (os.getenv("BINANCE_FAPI_BASE") or "https://fapi.binance.com").rstrip("/")
BINANCE_HTTP_BASE = (os.getenv("BINANCE_HTTP_BASE") or "https://api.binance.com").rstrip("/")

_UA = {
    "User-Agent": "AlgoGPT/2.x (+httpx)",
    "Accept": "application/json",
    "Connection": "close",
}

_DEFAULT_TIMEOUT = float(os.getenv("BINANCE_HTTP_TIMEOUT", "8.0"))

# --- Cache ---
_futures_exchange_info_cache: Optional[Dict[str, Any]] = None


# --- Helpers ---
def _is_json(r: httpx.Response) -> bool:
    ctype = (r.headers.get("Content-Type") or "").lower()
    return ctype.startswith("application/json")


def _get_json(path: str, params: Optional[dict] = None, timeout: float = _DEFAULT_TIMEOUT) -> dict:
    url = f"{_BINANCE_FAPI_BASE}/{path.lstrip('/')}"
    with httpx.Client(timeout=timeout, headers=_UA, follow_redirects=False) as client:
        r = client.get(url, params=params)
    if not _is_json(r):
        raise RuntimeError(f"non-json response from Binance: {r.text[:80]}")
    r.raise_for_status()
    return r.json()


# --- Client factory ---
def get_client() -> Client:
    if not BINANCE_API_KEY or not BINANCE_API_SECRET:
        raise RuntimeError("❌ Binance API credentials missing")
    client = Client(api_key=BINANCE_API_KEY, api_secret=BINANCE_API_SECRET)
    if USE_TESTNET:
        client.API_URL = "https://testnet.binance.vision/api"
        client.FUTURES_URL = "https://testnet.binancefuture.com/fapi/v1"
    else:
        client.API_URL = f"{BINANCE_HTTP_BASE}/api/v3"
        client.FUTURES_URL = f"{_BINANCE_FAPI_BASE}/fapi/v1"
    return client


# --- Public functions ---
def fapi_ping() -> bool:
    try:
        return _get_json("fapi/v1/ping") == {}
    except Exception as e:
        logger.error(f"[Binance] fapi_ping failed: {e}")
        return False


def futures_mark_price(symbol: str) -> Optional[float]:
    try:
        data = _get_json("fapi/v1/premiumIndex", {"symbol": symbol.upper()})
        return float(data["markPrice"])
    except Exception as e:
        logger.error(f"[Binance] futures_mark_price error {symbol}: {e}")
        return None


def get_symbol_info(symbol: str) -> Optional[dict]:
    """
    מחזיר מידע מלא על סימבול (exchangeInfo).
    נשמר ב־cache כדי לא להעמיס.
    """
    global _futures_exchange_info_cache
    try:
        if _futures_exchange_info_cache is None:
            _futures_exchange_info_cache = _get_json("fapi/v1/exchangeInfo")
        for s in _futures_exchange_info_cache.get("symbols", []):
            if s.get("symbol") == symbol.upper():
                return s
        return None
    except Exception as e:
        logger.error(f"[Binance] get_symbol_info error {symbol}: {e}")
        return None


































































































































