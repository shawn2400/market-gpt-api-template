# utils/binance_client.py
from __future__ import annotations
import os, time, logging
from typing import Any, Callable, Optional, Dict, List
import httpx
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException

logger = logging.getLogger("algogpt.binance")

# =========================
# 🔑 ENV
# =========================
BINANCE_API_KEY = (os.getenv("BINANCE_API_KEY") or "").strip()
BINANCE_API_SECRET = (os.getenv("BINANCE_API_SECRET") or "").strip()
USE_TESTNET = (os.getenv("BINANCE_TESTNET", "false").strip().lower() in ("1", "true", "yes"))

# Futures API bases + אלטים (ללא סלאשים מיותרים בסוף)
_BINANCE_FAPI_BASE = (os.getenv("BINANCE_FAPI_BASE") or "https://fapi.binance.com").rstrip("/")
_alts_raw = (os.getenv("BINANCE_FAPI_ALTS") or "https://fapi1.binance.com,https://fapi2.binance.com,https://fapi3.binance.com")
_BINANCE_FAPI_HOSTS = [h.strip().rstrip("/") for h in _alts_raw.split(",") if h.strip()]

# סדר ודדה־פ
_seen = set()
_hosts_ordered: List[str] = []
for h in [_BINANCE_FAPI_BASE] + _BINANCE_FAPI_HOSTS:
    if h and h not in _seen:
        _seen.add(h)
        _hosts_ordered.append(h)
_BINANCE_FAPI_HOSTS = _hosts_ordered

BINANCE_HTTP_BASE = (os.getenv("BINANCE_HTTP_BASE") or "https://api.binance.com").rstrip("/")

SUPPRESS_BINANCE_WARNINGS = (os.getenv("SUPPRESS_BINANCE_WARNINGS", "0").strip().lower() in ("1","true","yes"))
_DEFAULT_TIMEOUT = float(os.getenv("BINANCE_HTTP_TIMEOUT", "8.0"))
_MAX_RETRIES = int(os.getenv("BINANCE_MAX_RETRIES", "5"))

# Circuit Breaker ל-exchangeInfo
_CB_FAILS_FOR_OPEN = int(os.getenv("BINANCE_CB_FAILS_FOR_OPEN", "3"))
_CB_COOLDOWN_SEC   = int(os.getenv("BINANCE_CB_COOLDOWN_SEC", "120"))
_CB_MAX_COOLDOWN   = int(os.getenv("BINANCE_CB_MAX_COOLDOWN", "600"))
_SOFT_ALLOW_EXINFO = (os.getenv("BINANCE_SOFT_ALLOW_EXCHANGE_INFO", "1").strip().lower() in ("1","true","yes"))

# HTTP/2 toggle (ברירת מחדל כבוי)
_HTTPX_HTTP2 = (os.getenv("HTTPX_HTTP2", "0").strip().lower() in ("1","true","yes"))

# Cache
LAST_PRICE_CACHE: Dict[str, Dict[str, Any]] = {}
_futures_exchange_info_cache: Optional[Dict[str, Any]] = None
_valid_futures_symbols: Optional[set[str]] = None

# Circuit-breaker state
_cb_fail_count: int = 0
_cb_open_until: float = 0.0
_cb_current_cooldown: int = _CB_COOLDOWN_SEC

_UA = {
    "User-Agent": "AlgoGPT/2.x (+httpx)",
    "Accept": "application/json",
    "Connection": "close",
}

def _is_json(r: httpx.Response) -> bool:
    ctype = (r.headers.get("Content-Type") or "").lower()
    return ctype.startswith("application/json")

def _get_json(path: str, params: Optional[dict] = None, timeout: float = _DEFAULT_TIMEOUT) -> dict | list:
    """
    קריאה ישירה אל FAPI עם רוטציה בין בסיסים, ללא follow_redirects (WAF),
    ובדיקה שהתגובה JSON ולא HTML. אין כאן CB – CB מנוהל עבור exchangeInfo.
    """
    last_err: Optional[Exception] = None
    for base in _BINANCE_FAPI_HOSTS:
        url = f"{base}/{path.lstrip('/')}"
        try:
            # HTTP/2 כבוי כברירת מחדל – אפשר להדליק עם HTTPX_HTTP2=1
            with httpx.Client(timeout=timeout, headers=_UA, follow_redirects=False, http2=_HTTPX_HTTP2) as client:
                r = client.get(url, params=params)
            if r.status_code in (301, 302, 303, 307, 308):
                raise RuntimeError(f"redirect to {r.headers.get('Location')}")
            if not _is_json(r):
                raise RuntimeError("non-json (WAF/HTML)")
            r.raise_for_status()
            data = r.json()
            return data
        except Exception as e:
            last_err = e
            level = logging.WARNING if SUPPRESS_BINANCE_WARNINGS else logging.ERROR
            logger.log(level, f"[BinanceHTTP] GET {url} failed: {e}")
            continue
    raise RuntimeError(f"FAPI failed: {type(last_err).__name__}: {last_err}")

# =========================
# 🧩 Client (לקריאות חתומות בלבד)
# =========================
def get_client() -> Client:
    if not BINANCE_API_KEY or not BINANCE_API_SECRET:
        logger.error("❌ BINANCE_API_KEY / BINANCE_API_SECRET missing → check ENV")
        raise RuntimeError("Missing Binance credentials")

    client = Client(api_key=BINANCE_API_KEY, api_secret=BINANCE_API_SECRET)

    if USE_TESTNET:
        logger.warning("⚠️ Using Binance TESTNET endpoints")
        # שים לב: ה-SDK מצפה לבסיס (ללא /api/v3 או /fapi/v1)
        client.API_URL = "https://testnet.binance.vision"
        client.FUTURES_URL = "https://testnet.binancefuture.com"
    else:
        client.API_URL = BINANCE_HTTP_BASE
        client.FUTURES_URL = _BINANCE_FAPI_BASE
    return client

# =========================
# 🔒 Circuit Breaker helpers
# =========================
def _cb_is_open() -> bool:
    return time.time() < _cb_open_until

def _cb_on_fail() -> None:
    global _cb_fail_count, _cb_open_until, _cb_current_cooldown
    _cb_fail_count += 1
    if _cb_fail_count >= _CB_FAILS_FOR_OPEN and not _cb_is_open():
        _cb_open_until = time.time() + _cb_current_cooldown
        _cb_current_cooldown = min(_cb_current_cooldown * 2, _CB_MAX_COOLDOWN)
        logger.warning({"event": "binance_cb_open", "cooldown_sec": _cb_current_cooldown, "until": _cb_open_until})

def _cb_on_success() -> None:
    global _cb_fail_count, _cb_open_until, _cb_current_cooldown
    _cb_fail_count = 0
    _cb_open_until = 0.0
    _cb_current_cooldown = _CB_COOLDOWN_SEC

# =========================
# 📊 Futures Exchange Info (מוגן CB)
# =========================
def futures_exchange_info_safe(force_refresh: bool = False) -> Dict[str, Any]:
    global _futures_exchange_info_cache
    if _cb_is_open() and not force_refresh:
        if _futures_exchange_info_cache and not force_refresh:
            return _futures_exchange_info_cache
        if _SOFT_ALLOW_EXINFO:
            return {"symbols": []}
        raise RuntimeError("exchangeInfo circuit-breaker open")

    try:
        info = _get_json("/fapi/v1/exchangeInfo")
        if not isinstance(info, dict) or "symbols" not in info:
            raise RuntimeError("Invalid response from Binance exchangeInfo")
        _futures_exchange_info_cache = info
        _cb_on_success()
        return info
    except Exception as e:
        _cb_on_fail()
        raise RuntimeError(f"exchangeInfo failed: {e}")

def valid_futures_symbols(force_refresh: bool = False) -> set[str]:
    global _valid_futures_symbols
    if _valid_futures_symbols is not None and not force_refresh:
        return _valid_futures_symbols
    try:
        info = futures_exchange_info_safe(force_refresh=force_refresh)
        symbols = {s.get("symbol", "").upper() for s in info.get("symbols", []) if s.get("status") == "TRADING"}
    except Exception as e:
        level = logging.WARNING if SUPPRESS_BINANCE_WARNINGS else logging.ERROR
        logger.log(level, f"[Binance] valid_futures_symbols: {e}")
        symbols = set()
    _valid_futures_symbols = symbols
    return _valid_futures_symbols

def is_valid_futures_symbol(symbol: str) -> bool:
    try:
        return symbol.upper() in valid_futures_symbols()
    except Exception as e:
        level = logging.WARNING if SUPPRESS_BINANCE_WARNINGS else logging.ERROR
        logger.log(level, f"[Binance] is_valid_futures_symbol: soft-allow ({e})")
        return True

# =========================
# 💵 Futures Mark Price (HTTP ישיר; לא נחסם ע"י CB)
# =========================
def futures_mark_price(symbol: str) -> Optional[float]:
    sym = symbol.upper().strip()
    try:
        data = _get_json("/fapi/v1/premiumIndex", params={"symbol": sym})
        # לרוב זה dict. אם מסיבה כלשהי זו רשימה – נאתר את הסימבול.
        if isinstance(data, dict) and "markPrice" in data:
            price = float(data["markPrice"])
        elif isinstance(data, list):
            rec = next((d for d in data if str(d.get("symbol", "")).upper() == sym and "markPrice" in d), None)
            price = float(rec["markPrice"]) if rec else None
        else:
            raise RuntimeError(f"unexpected premiumIndex payload type={type(data)}")

        if price is not None:
            LAST_PRICE_CACHE[sym] = {"price": price, "ts": int(time.time())}
        return price
    except Exception as e:
        logger.error(f"[Binance] futures_mark_price error {sym}: {e}")
        return None

# =========================
# 🔁 Retry helper (לקריאות חתומות דרך ה-SDK)
# =========================
def retry_call(fn: Callable[[], Any], label: str, retries: int = _MAX_RETRIES, delay: float = 0.5) -> Any:
    last_exc: Optional[Exception] = None
    for i in range(retries):
        try:
            return fn()
        except (BinanceAPIException, BinanceRequestException, httpx.HTTPError) as e:
            last_exc = e
            level = logging.WARNING if SUPPRESS_BINANCE_WARNINGS else logging.ERROR
            logger.log(level, f"[Binance] {label} failed ({i+1}/{retries}): {e}")
            time.sleep(delay)
        except Exception as e:
            last_exc = e
            logger.error(f"[Binance] {label} unexpected error: {e}")
            time.sleep(delay)
    raise RuntimeError(f"[Binance] {label} failed after {retries} retries: {last_exc}")

# =========================
# 📋 Status helper (לראוטר)
# =========================
def status_snapshot() -> dict:
    return {
        "hosts": _BINANCE_FAPI_HOSTS,
        "timeout": _DEFAULT_TIMEOUT,
        "retries": _MAX_RETRIES,
        "exchange_info": {
            "cb_open": _cb_is_open(),
            "cb_fails": _cb_fail_count,
            "cb_until": _cb_open_until,
            "cooldown_next": _cb_current_cooldown,
            "soft_allow": _SOFT_ALLOW_EXINFO,
            "cache_symbols": len((_futures_exchange_info_cache or {}).get("symbols", [])),
        }
    }























































































































