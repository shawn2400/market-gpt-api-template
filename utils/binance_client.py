# utils/binance_client.py
from __future__ import annotations
import os, logging
from typing import Any, Optional, Dict, List
import httpx
from binance.client import Client

logger = logging.getLogger("algogpt.binance")

# --- Keys ---
BINANCE_API_KEY = (os.getenv("BINANCE_API_KEY") or "").strip().replace("\n", "").replace("\r", "")
BINANCE_API_SECRET = (os.getenv("BINANCE_API_SECRET") or "").strip().replace("\n", "").replace("\r", "")
USE_TESTNET = os.getenv("BINANCE_TESTNET", "false").strip().lower() in ("1", "true", "yes")

# --- Hosts ---
_BINANCE_FAPI_BASE = (os.getenv("BINANCE_FAPI_BASE") or "https://fapi.binance.com").rstrip("/")
_alts_raw = os.getenv("BINANCE_FAPI_ALTS") or "https://fapi1.binance.com,https://fapi2.binance.com,https://fapi3.binance.com"
_BINANCE_FAPI_HOSTS = list({h.strip().rstrip("/") for h in [_BINANCE_FAPI_BASE] + _alts_raw.split(",") if h.strip()})

BINANCE_HTTP_BASE = (os.getenv("BINANCE_HTTP_BASE") or "https://api.binance.com").rstrip("/")

_DEFAULT_TIMEOUT = float(os.getenv("BINANCE_HTTP_TIMEOUT", "8.0"))
SUPPRESS_BINANCE_WARNINGS = os.getenv("SUPPRESS_BINANCE_WARNINGS", "0").lower() in ("1", "true", "yes")

# --- Caches ---
_futures_exchange_info_cache: Optional[Dict[str, Any]] = None
_valid_futures_symbols: Optional[set[str]] = None

_UA = {"User-Agent": "AlgoGPT/2.x (+httpx)", "Accept": "application/json", "Connection": "close"}


# --- Helpers ---
def _is_json(r: httpx.Response) -> bool:
    return (r.headers.get("Content-Type") or "").lower().startswith("application/json")


def _get_json(path: str, params: Optional[dict] = None, timeout: float = _DEFAULT_TIMEOUT) -> dict:
    last_err: Optional[Exception] = None
    for base in _BINANCE_FAPI_HOSTS:
        url = f"{base}/{path.lstrip('/')}"
        try:
            with httpx.Client(timeout=timeout, headers=_UA) as client:
                r = client.get(url, params=params)
            if not _is_json(r):
                raise RuntimeError("non-json response (WAF/HTML)")
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            lvl = logging.WARNING if SUPPRESS_BINANCE_WARNINGS else logging.ERROR
            logger.log(lvl, f"[BinanceHTTP] GET {url} failed: {e}")
            continue
    raise RuntimeError(f"FAPI failed: {type(last_err).__name__}: {last_err}")


# --- Client ---
def get_client() -> Client:
    if not BINANCE_API_KEY or not BINANCE_API_SECRET:
        raise RuntimeError("Missing Binance credentials")
    client = Client(api_key=BINANCE_API_KEY, api_secret=BINANCE_API_SECRET)
    if USE_TESTNET:
        client.API_URL = "https://testnet.binance.vision/api"
        client.FUTURES_URL = "https://testnet.binancefuture.com/fapi/v1"
    else:
        client.API_URL = f"{BINANCE_HTTP_BASE}/api/v3"
        client.FUTURES_URL = f"{_BINANCE_FAPI_BASE}/fapi/v1"
    return client


# --- Public helpers ---
def fapi_ping() -> bool:
    try:
        _get_json("fapi/v1/ping")
        return True
    except Exception as e:
        logger.warning(f"[Binance] fapi_ping failed: {e}")
        return False


def futures_mark_price(symbol: str) -> Optional[float]:
    try:
        data = _get_json("fapi/v1/premiumIndex", params={"symbol": symbol.upper()})
        return float(data.get("markPrice")) if "markPrice" in data else None
    except Exception as e:
        logger.error(f"[Binance] futures_mark_price error {symbol}: {e}")
        return None


def futures_exchange_info_safe(force_refresh: bool = False) -> Dict[str, Any]:
    global _futures_exchange_info_cache, _valid_futures_symbols
    if _futures_exchange_info_cache and not force_refresh:
        return _futures_exchange_info_cache
    data = _get_json("fapi/v1/exchangeInfo")
    _futures_exchange_info_cache = data
    _valid_futures_symbols = {s["symbol"] for s in data.get("symbols", []) if s.get("contractType") == "PERPETUAL"}
    return _futures_exchange_info_cache


def get_symbol_info(symbol: str, force_refresh: bool = False) -> Optional[Dict[str, Any]]:
    info = futures_exchange_info_safe(force_refresh=force_refresh)
    for s in info.get("symbols", []):
        if s.get("symbol") == symbol.upper():
            return s
    return None


def futures_open_positions() -> List[Dict[str, Any]]:
    try:
        client = get_client()
        acc_info = client.futures_account()
        return [p for p in acc_info.get("positions", []) if float(p.get("positionAmt", "0")) != 0.0]
    except Exception as e:
        logger.error(f"[Binance] futures_open_positions failed: {e}")
        return []


def status_snapshot() -> Dict[str, Any]:
    """סטטוס כללי של חשבון Binance Futures"""
    snap = {"ok": False, "positions": 0}
    try:
        client = get_client()
        acc_info = client.futures_account()
        pos = [p for p in acc_info.get("positions", []) if float(p.get("positionAmt", "0")) != 0.0]
        snap.update({"ok": True, "positions": len(pos), "assets": acc_info.get("assets", [])})
    except Exception as e:
        snap.update({"error": str(e)})
    return snap








































































































































