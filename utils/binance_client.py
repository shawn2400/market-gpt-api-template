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

# Futures API bases (ללא www) + אלטים
_BINANCE_FAPI_BASE = (os.getenv("BINANCE_FAPI_BASE") or "https://fapi.binance.com").rstrip("/")
_alts_raw = (os.getenv("BINANCE_FAPI_ALTS") or "https://fapi1.binance.com,https://fapi2.binance.com,https://fapi3.binance.com")
_BINANCE_FAPI_HOSTS = [h.strip().rstrip("/") for h in _alts_raw.split(",") if h.strip()]
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

# Circuit Breaker לפרוסס exchangeInfo
_CB_FAILS_FOR_OPEN = int(os.getenv("BINANCE_CB_FAILS_FOR_OPEN", "3"))
_CB_COOLDOWN_SEC   = int(os.getenv("BINANCE_CB_COOLDOWN_SEC", "120"))
_CB_MAX_COOLDOWN   = int(os.getenv("BINANCE_CB_MAX_COOLDOWN", "600"))
_SOFT_ALLOW_EXINFO = (os.getenv("BINANCE_SOFT_ALLOW_EXCHANGE_INFO", "1").strip().lower() in ("1","true","yes"))

# Cache
LAST_PRICE_CACHE: Dict[str, Dict[str, Any]] = {}
_futures_exchange_info_cache: Optional[Dict[str, Any]] = None
_symbol_info_cache: Dict[str, Dict[str, Any]] = {}
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

def _get_json(path: str, params: Optional[dict] = None, timeout: float = _DEFAULT_TIMEOUT) -> dict:
    """
    קריאה ישירה אל FAPI עם רוטציה בין fapi/fapi1/2/3, ללא follow_redirects (WAF),
    ובדיקה שהתגובה JSON ולא HTML. ה־http2 כבוי כדי למנוע תלות ב־h2.
    """
    last_err: Optional[Exception] = None
    for base in _BINANCE_FAPI_HOSTS:
        url = f"{base}/{path.lstrip('/')}"
        try:
            # http2=False → אין צורך ב-h2
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

# =========================
# 🧩 Client (לקריאות חתומות בלבד)
# =========================
def get_client() -> Client:
    if not BINANCE_API_KEY or not BINANCE_API_SECRET:
        logger.error("❌ BINANCE_API_KEY / BINANCE_API_SECRET missing → check ENV")
        raise RuntimeError("Missing Binance credentials")

    client = Client(api_key=BINANCE_API_KEY, api_secret=BINANCE_API_SECRET)  # use sdk for signed calls only

    if USE_TESTNET:
        logger.warning("⚠️ Using Binance TESTNET endpoints")
        client.API_URL = "https://testnet.binance.vision/api"
        client.FUTURES_URL = "https://testnet.binancefuture.com/fapi/v1"
    else:
        client.API_URL = f"{BINANCE_HTTP_BASE}/api/v3"
        client.FUTURES_URL = f"{_BINANCE_FAPI_BASE}/fapi/v1"
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
        logger.warning({"event": "binance_cb_open", "cooldown_sec": _cb_current_cooldown, "until": _cb_open_until})
        _cb_current_cooldown = min(_cb_current_cooldown * 2, _CB_MAX_COOLDOWN)

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
    # אם CB פתוח – נחזיר קאש/מבנה ריק (אם soft-allow) או נזרוק שגיאה
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
        _symbol_info_cache.clear()
        _cb_on_success()
        return info
    except Exception as e:
        _cb_on_fail()
        level = logging.WARNING if SUPPRESS_BINANCE_WARNINGS else logging.ERROR
        logger.log(level, f"[Binance] exchangeInfo failed: {e}")
        if _SOFT_ALLOW_EXINFO:
            return _futures_exchange_info_cache or {"symbols": []}
        raise

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

# ---------- NEW: get_cached_symbol_info ----------
def get_cached_symbol_info(symbol: str, force_refresh: bool = False) -> Optional[Dict[str, Any]]:
    """
    מחזיר את אובייקט ה־symbol מתוך exchangeInfo, עם קאש פנימי.
    """
    sym = symbol.upper().strip()
    if not sym:
        return None
    if not force_refresh and sym in _symbol_info_cache:
        return _symbol_info_cache[sym]

    info = futures_exchange_info_safe(force_refresh=force_refresh)
    for s in info.get("symbols", []):
        if s.get("symbol", "").upper() == sym:
            _symbol_info_cache[sym] = s
            return s
    return None

# =========================
# 💵 Futures Mark Price (HTTP ישיר; לא נחסם ע"י CB)
# =========================
def futures_mark_price(symbol: str) -> Optional[float]:
    sym = symbol.upper().strip()
    try:
        data = _get_json("/fapi/v1/premiumIndex", params={"symbol": sym})
        if isinstance(data, dict) and "markPrice" in data:
            price = float(data["markPrice"])
            LAST_PRICE_CACHE[sym] = {"price": price, "ts": int(time.time())}
            return price
        raise RuntimeError(f"unexpected premiumIndex payload type={type(data)}")
    except Exception as e:
        logger.error(f"[Binance] futures_mark_price error {sym}: {e}")
        return None

# =========================
# 📌 Futures Open Positions (חתום → SDK)
# =========================
def futures_open_positions(symbol: Optional[str] = None) -> List[Dict[str, Any]]:
    client = get_client()
    try:
        if symbol:
            resp = retry_call(lambda: client.futures_position_information(symbol=symbol.upper()), f"futures_positions({symbol})")
        else:
            resp = retry_call(lambda: client.futures_position_information(), "futures_positions(all)")
        if not isinstance(resp, list):
            raise RuntimeError(f"Unexpected response type: {type(resp)}")

        out: List[Dict[str, Any]] = []
        for p in resp:
            try:
                amt = float(p.get("positionAmt", 0))
                if amt != 0:
                    out.append({
                        "symbol": p.get("symbol"),
                        "positionAmt": amt,
                        "entryPrice": float(p.get("entryPrice", 0)),
                        "unRealizedProfit": float(p.get("unRealizedProfit", 0)),
                        "leverage": int(float(p.get("leverage", 0) or 0)),
                        "side": "LONG" if amt > 0 else "SHORT",
                    })
            except Exception as e:
                logger.warning(f"[Binance] skip bad position: {e}")
        return out
    except Exception as e:
        raise RuntimeError(f"[Binance] futures_open_positions failed: {e}")

# =========================
# 🔁 Retry helper
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























































































































