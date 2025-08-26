# utils/binance_client.py
from __future__ import annotations
import os, time, logging, json
from typing import Any, Optional, Dict, List, Set
import httpx
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException

logger = logging.getLogger("algogpt.binance")

# --- Keys ---
BINANCE_API_KEY = (os.getenv("BINANCE_API_KEY") or "").strip().replace("\n","").replace("\r","")
BINANCE_API_SECRET = (os.getenv("BINANCE_API_SECRET") or "").strip().replace("\n","").replace("\r","")
USE_TESTNET = (os.getenv("BINANCE_TESTNET", "false").strip().lower() in ("1","true","yes"))

# --- Hosts ---
_BINANCE_FAPI_BASE = (os.getenv("BINANCE_FAPI_BASE") or "https://fapi.binance.com").rstrip("/")
_alts_raw = (os.getenv("BINANCE_FAPI_ALTS") or
             "https://fapi1.binance.com,https://fapi2.binance.com,https://fapi3.binance.com")
_BINANCE_FAPI_HOSTS: List[str] = []
_seen = set()
for h in [_BINANCE_FAPI_BASE] + [a.strip().rstrip("/") for a in _alts_raw.split(",") if a.strip()]:
    if h and h not in _seen:
        _seen.add(h)
        _BINANCE_FAPI_HOSTS.append(h)

BINANCE_HTTP_BASE = (os.getenv("BINANCE_HTTP_BASE") or "https://api.binance.com").rstrip("/")

SUPPRESS_BINANCE_WARNINGS = (os.getenv("SUPPRESS_BINANCE_WARNINGS", "0").strip().lower() in ("1","true","yes"))
_DEFAULT_TIMEOUT = float(os.getenv("BINANCE_HTTP_TIMEOUT", "8.0"))
_MAX_RETRIES = int(os.getenv("BINANCE_MAX_RETRIES", "5"))

# --- Circuit Breaker ---
_CB_FAILS_FOR_OPEN = int(os.getenv("BINANCE_CB_FAILS_FOR_OPEN", "3"))
_CB_COOLDOWN_SEC   = int(os.getenv("BINANCE_CB_COOLDOWN_SEC", "120"))
_CB_MAX_COOLDOWN   = int(os.getenv("BINANCE_CB_MAX_COOLDOWN", "600"))
_SOFT_ALLOW_EXINFO = (os.getenv("BINANCE_SOFT_ALLOW_EXCHANGE_INFO", "1").strip().lower() in ("1","true","yes"))

LAST_PRICE_CACHE: Dict[str, Dict[str, Any]] = {}
_futures_exchange_info_cache: Optional[Dict[str, Any]] = None
_valid_futures_symbols: Optional[Set[str]] = None

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
    last_err: Optional[Exception] = None
    for base in _BINANCE_FAPI_HOSTS:
        url = f"{base}/{path.lstrip('/')}"
        try:
            with httpx.Client(timeout=timeout, headers=_UA, follow_redirects=False, http2=False) as client:
                r = client.get(url, params=params)
            if r.status_code in (301, 302, 303, 307, 308):
                raise RuntimeError(f"redirect to {r.headers.get('Location')}")
            if not _is_json(r):
                raise RuntimeError("non-json (WAF/HTML)")
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            level = logging.WARNING if SUPPRESS_BINANCE_WARNINGS else logging.ERROR
            logger.log(level, f"[BinanceHTTP] GET {url} failed: {e}")
            continue
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

# --- Public Futures helpers ---
def fapi_ping() -> bool:
    try:
        _get_json("/fapi/v1/ping", timeout=3.0)
        return True
    except Exception as e:
        logger.warning(f"[Binance] fapi_ping fail: {e}")
        return False

def futures_mark_price(symbol: str) -> Optional[float]:
    try:
        data = _get_json("/fapi/v1/premiumIndex", params={"symbol": symbol.upper()}, timeout=5.0)
        return float(data["markPrice"])
    except Exception as e:
        logger.error(f"[Binance] futures_mark_price error {symbol}: {e}")
        return None

def futures_exchange_info_safe() -> dict:
    global _futures_exchange_info_cache, _valid_futures_symbols
    if _futures_exchange_info_cache:
        return _futures_exchange_info_cache
    try:
        data = _get_json("/fapi/v1/exchangeInfo", timeout=10.0)
        _futures_exchange_info_cache = data
        _valid_futures_symbols = {s["symbol"].upper() for s in data.get("symbols", []) if s.get("status") == "TRADING"}
        return data
    except Exception as e:
        logger.error(f"[Binance] futures_exchange_info_safe fail: {e}")
        return {}

def valid_futures_symbols() -> Set[str]:
    global _valid_futures_symbols
    if not _valid_futures_symbols:
        futures_exchange_info_safe()
    return _valid_futures_symbols or set()

# --- Watchlist Cleaner ---
def clean_watchlist(path: str = "watchlist.json") -> None:
    """ניקוי watchlist.json מסימבולים לא חוקיים בפיוצ'רס"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        valid_syms = valid_futures_symbols()
        cleaned = [row for row in data if row.get("symbol", "").upper() in valid_syms]
        if len(cleaned) != len(data):
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cleaned, f, indent=2, ensure_ascii=False)
            logger.warning(f"[Watchlist] Cleaned invalid symbols → {len(data)-len(cleaned)} removed")
    except Exception as e:
        logger.error(f"[Watchlist] Failed to clean: {e}")

































































































































