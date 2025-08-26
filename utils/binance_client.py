# utils/binance_client.py
from __future__ import annotations
import os, time, logging, random
from typing import Any, Optional, Dict
import httpx
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException

logger = logging.getLogger("algogpt.binance")

# --- Keys ---
BINANCE_API_KEY = (os.getenv("BINANCE_API_KEY") or "").strip().replace("\n","").replace("\r","")
BINANCE_API_SECRET = (os.getenv("BINANCE_API_SECRET") or "").strip().replace("\n","").replace("\r","")
USE_TESTNET = (os.getenv("BINANCE_TESTNET", "false").strip().lower() in {"1","true","yes"})

# --- Hosts ---
_BINANCE_FAPI_BASE = (os.getenv("BINANCE_FAPI_BASE") or "https://fapi.binance.com").rstrip("/")
_alts_raw = (os.getenv("BINANCE_FAPI_ALTS") or 
             "https://fapi1.binance.com,https://fapi2.binance.com,https://fapi3.binance.com")
_BINANCE_FAPI_HOSTS: list[str] = []
_seen = set()
for h in [_BINANCE_FAPI_BASE] + [a.strip().rstrip("/") for a in _alts_raw.split(",") if a.strip()]:
    if h and h not in _seen:
        _seen.add(h)
        _BINANCE_FAPI_HOSTS.append(h)

BINANCE_HTTP_BASE = (os.getenv("BINANCE_HTTP_BASE") or "https://api.binance.com").rstrip("/")

SUPPRESS_BINANCE_WARNINGS = (os.getenv("SUPPRESS_BINANCE_WARNINGS", "0").strip().lower() in {"1","true","yes"})
_DEFAULT_TIMEOUT = float(os.getenv("BINANCE_HTTP_TIMEOUT", "8.0"))
_MAX_RETRIES = int(os.getenv("BINANCE_MAX_RETRIES", "5"))

# --- Circuit Breaker ---
_CB_FAILS_FOR_OPEN = int(os.getenv("BINANCE_CB_FAILS_FOR_OPEN", "3"))
_CB_COOLDOWN_SEC   = int(os.getenv("BINANCE_CB_COOLDOWN_SEC", "120"))
_CB_MAX_COOLDOWN   = int(os.getenv("BINANCE_CB_MAX_COOLDOWN", "600"))

LAST_PRICE_CACHE: Dict[str, Dict[str, Any]] = {}
_futures_exchange_info_cache: Optional[Dict[str, Any]] = None
_cb_fail_count: int = 0
_cb_open_until: float = 0.0
_cb_current_cooldown: int = _CB_COOLDOWN_SEC

_UA = {
    "User-Agent": "AlgoGPT/2.x (+httpx)",
    "Accept": "application/json",
    "Connection": "close",
}

# --- Helpers ---
def _is_json(r: httpx.Response) -> bool:
    ctype = (r.headers.get("Content-Type") or "").lower()
    return ctype.startswith("application/json")

def _get_json(path: str, params: Optional[dict] = None, timeout: float = _DEFAULT_TIMEOUT) -> dict:
    """קריאה עם retry + fallback"""
    global _cb_fail_count, _cb_open_until, _cb_current_cooldown
    last_err: Optional[Exception] = None

    if time.time() < _cb_open_until:
        raise RuntimeError("circuit breaker open")

    for attempt in range(1, _MAX_RETRIES+1):
        for base in _BINANCE_FAPI_HOSTS:
            url = f"{base}/{path.lstrip('/')}"
            try:
                with httpx.Client(timeout=timeout, headers=_UA, follow_redirects=False) as client:
                    r = client.get(url, params=params)

                if r.status_code == 429:
                    sleep_t = min(2**attempt, 30) + random.random()
                    logger.warning(f"[BinanceHTTP] 429 Too Many Requests, sleeping {sleep_t:.1f}s")
                    time.sleep(sleep_t)
                    continue

                if r.status_code in (301, 302, 303, 307, 308):
                    raise RuntimeError(f"redirect to {r.headers.get('Location')}")

                if not _is_json(r):
                    raise RuntimeError("non-json (WAF/HTML)")

                r.raise_for_status()
                _cb_fail_count = 0
                return r.json()

            except Exception as e:
                last_err = e
                _cb_fail_count += 1
                level = logging.WARNING if SUPPRESS_BINANCE_WARNINGS else logging.ERROR
                logger.log(level, f"[BinanceHTTP] GET {url} failed (attempt {attempt}): {e}")
                time.sleep(min(1.5**attempt, 10))
                continue

    if _cb_fail_count >= _CB_FAILS_FOR_OPEN:
        _cb_open_until = time.time() + min(_cb_current_cooldown, _CB_MAX_COOLDOWN)
        _cb_current_cooldown *= 2
        logger.error(f"[BinanceHTTP] Circuit breaker opened for {_cb_current_cooldown}s")

    raise RuntimeError(f"FAPI failed: {type(last_err).__name__}: {last_err}")

# --- Client ---
def get_client() -> Client:
    if not BINANCE_API_KEY or not BINANCE_API_SECRET:
        logger.error("❌ BINANCE_API_KEY / BINANCE_API_SECRET missing → check ENV")
        raise RuntimeError("Missing Binance credentials")

    client = Client(api_key=BINANCE_API_KEY, api_secret=BINANCE_API_SECRET)
    if USE_TESTNET:
        logger.warning("⚠️ Using Binance TESTNET endpoints")
        client.API_URL = "https://testnet.binance.vision/api"
        client.FUTURES_URL = "https://testnet.binancefuture.com/fapi/v1"
    else:
        client.API_URL = f"{BINANCE_HTTP_BASE}/api/v3"
        client.FUTURES_URL = f"{_BINANCE_FAPI_BASE}/fapi/v1"
    return client

# --- Public Wrappers ---
def fapi_ping() -> bool:
    try:
        _get_json("fapi/v1/ping")
        return True
    except Exception as e:
        logger.warning(f"[Binance] fapi_ping failed: {e}")
        try:
            client = get_client()
            client.futures_ping()
            return True
        except Exception as e2:
            logger.error(f"[Binance] fapi_ping fallback failed: {e2}")
            return False

def futures_mark_price(symbol: str) -> Optional[float]:
    """מחזיר Mark Price או None עם fallback ל-SDK"""
    symbol = symbol.upper()
    try:
        data = _get_json("fapi/v1/premiumIndex", params={"symbol": symbol})
        if not data or "markPrice" not in data:
            raise RuntimeError("markPrice missing")
        price = float(data["markPrice"])
        LAST_PRICE_CACHE[symbol] = {"price": price, "ts": time.time()}
        return price
    except Exception as e:
        logger.error(f"[Binance] futures_mark_price error {symbol}: {e}")
        try:
            client = get_client()
            resp = client.futures_mark_price(symbol=symbol)
            price = float(resp.get("markPrice"))
            LAST_PRICE_CACHE[symbol] = {"price": price, "ts": time.time()}
            return price
        except Exception as e2:
            logger.error(f"[Binance] futures_mark_price fallback error {symbol}: {e2}")
            return None

def futures_exchange_info(force: bool = False) -> dict:
    """מידע על חוזים"""
    global _futures_exchange_info_cache
    if _futures_exchange_info_cache and not force:
        return _futures_exchange_info_cache
    try:
        data = _get_json("fapi/v1/exchangeInfo")
        _futures_exchange_info_cache = data
        return data
    except Exception as e:
        logger.warning(f"[Binance] exchangeInfo REST failed: {e}")
        try:
            client = get_client()
            data = client.futures_exchange_info()
            _futures_exchange_info_cache = data
            return data
        except Exception as e2:
            logger.error(f"[Binance] exchangeInfo fallback failed: {e2}")
            return {"symbols": []}































































































































