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
USE_TESTNET = os.getenv("BINANCE_TESTNET", "false").strip().lower() in ("1", "true", "yes")

# Futures API bases (ללא www) + אלטים
_BINANCE_FAPI_BASE = (os.getenv("BINANCE_FAPI_BASE") or "https://fapi1.binance.com").rstrip("/")
_alts_raw = (os.getenv("BINANCE_FAPI_ALTS") or "https://fapi2.binance.com,https://fapi3.binance.com")
_BINANCE_FAPI_HOSTS = [h.strip().rstrip("/") for h in _alts_raw.split(",") if h.strip()]
# ודא שאין כפילויות והבסיס הראשי הוא ראשון
_seen = set()
_hosts_ordered: List[str] = []
for h in [_BINANCE_FAPI_BASE] + _BINANCE_FAPI_HOSTS:
    if h and h not in _seen:
        _seen.add(h)
        _hosts_ordered.append(h)
_BINANCE_FAPI_HOSTS = _hosts_ordered

BINANCE_HTTP_BASE = (os.getenv("BINANCE_HTTP_BASE") or "https://api.binance.com").rstrip("/")

SUPPRESS_BINANCE_WARNINGS = os.getenv("SUPPRESS_BINANCE_WARNINGS", "0").strip().lower() in ("1", "true", "yes")
_DEFAULT_TIMEOUT = float(os.getenv("BINANCE_HTTP_TIMEOUT", "8.0"))
_MAX_RETRIES = int(os.getenv("BINANCE_MAX_RETRIES", "5"))

# =========================
# ⚡ Circuit Breaker (לקריאות ציבוריות בלבד)
# =========================
_CB_FAIL_THRESHOLD = int(os.getenv("BINANCE_CB_FAIL_THRESHOLD", "3"))
_CB_COOLDOWN_BASE = int(os.getenv("BINANCE_CB_COOLDOWN_BASE", "120"))   # שניות
_CB_COOLDOWN_MAX  = int(os.getenv("BINANCE_CB_COOLDOWN_MAX", "600"))    # שניות

_cb_failures: int = 0
_cb_open_until: float = 0.0
_cb_cooldown: int = _CB_COOLDOWN_BASE

_last_host: str | None = None
_last_error: str | None = None
_last_json_ok: bool = False
_last_ts: float | None = None

# Cache
LAST_PRICE_CACHE: Dict[str, Dict[str, Any]] = {}
_futures_exchange_info_cache: Optional[Dict[str, Any]] = None
_valid_futures_symbols: Optional[set[str]] = None

_UA = {
    "User-Agent": "AlgoGPT/2.x (+httpx)",
    "Accept": "application/json",
    "Connection": "close",
}

def _is_json(r: httpx.Response) -> bool:
    ctype = (r.headers.get("Content-Type") or "").lower()
    return ctype.startswith("application/json")

def _cb_is_open(now: float | None = None) -> bool:
    if now is None:
        now = time.time()
    return now < _cb_open_until

def _cb_record_success():
    global _cb_failures, _cb_cooldown, _last_error
    _cb_failures = 0
    _cb_cooldown = _CB_COOLDOWN_BASE
    _last_error = None

def _cb_record_failure(err: Exception):
    global _cb_failures, _cb_open_until, _cb_cooldown, _last_error
    _cb_failures += 1
    _last_error = f"{type(err).__name__}: {err}"
    if _cb_failures >= _CB_FAIL_THRESHOLD:
        _cb_open_until = time.time() + _cb_cooldown
        _cb_cooldown = min(_cb_cooldown * 2, _CB_COOLDOWN_MAX)
        # נשאיר את _cb_failures לאיפוס אחרי קירור
        logger.warning({"event": "binance_cb_open", "open_seconds": _cb_cooldown})

def _get_json(path: str, params: Optional[dict] = None, timeout: float = _DEFAULT_TIMEOUT) -> dict:
    """
    קריאה ישירה אל FAPI עם רוטציה בין fapi1/2/3, ללא מעקב אחרי הפניות (WAF),
    ובדיקה שהתגובה JSON ולא HTML. כולל Circuit Breaker.
    """
    global _last_host, _last_json_ok, _last_ts

    now = time.time()
    if _cb_is_open(now):
        secs = int(_cb_open_until - now)
        raise RuntimeError(f"circuit_open ({secs}s left)")

    last_err: Optional[Exception] = None
    for base in _BINANCE_FAPI_HOSTS:
        url = f"{base}/{path.lstrip('/')}"
        try:
            with httpx.Client(timeout=timeout, headers=_UA, follow_redirects=False, http2=True) as client:
                r = client.get(url, params=params)
            _last_host = base
            _last_ts = time.time()
            if r.status_code in (301, 302, 303, 307, 308):
                raise RuntimeError(f"redirect to {r.headers.get('Location')}")
            if not _is_json(r):
                raise RuntimeError("non-json (WAF/HTML)")
            r.raise_for_status()
            _last_json_ok = True
            _cb_record_success()
            return r.json()
        except Exception as e:
            _last_json_ok = False
            last_err = e
            level = logging.WARNING if SUPPRESS_BINANCE_WARNINGS else logging.ERROR
            logger.log(level, f"[BinanceHTTP] GET {url} failed: {e}")
            _cb_record_failure(e)
            # ננסה host הבא
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
        client.API_URL = "https://testnet.binance.vision/api"
        client.FUTURES_URL = "https://testnet.binancefuture.com/fapi/v1"
    else:
        client.API_URL = f"{BINANCE_HTTP_BASE}/api/v3"
        client.FUTURES_URL = f"{_BINANCE_FAPI_HOSTS[0]}/fapi/v1"

    return client

# =========================
# 🛈 Startup banner
# =========================
try:
    logger.info({
        "event": "binance_client_mode",
        "http_only_for_public": True,
        "signed_via_sdk": True,
        "hosts": _BINANCE_FAPI_HOSTS,
        "timeout": _DEFAULT_TIMEOUT,
        "retries": _MAX_RETRIES,
        "testnet": USE_TESTNET,
        "cb_threshold": _CB_FAIL_THRESHOLD,
        "cb_base": _CB_COOLDOWN_BASE,
        "cb_max": _CB_COOLDOWN_MAX,
    })
except Exception:
    pass

# =========================
# 📊 Futures Exchange Info (HTTP נקי)
# =========================
def futures_exchange_info_safe(force_refresh: bool = False) -> Dict[str, Any]:
    global _futures_exchange_info_cache
    if _futures_exchange_info_cache is not None and not force_refresh:
        return _futures_exchange_info_cache

    info = _get_json("/fapi/v1/exchangeInfo")
    if not isinstance(info, dict) or "symbols" not in info:
        raise RuntimeError("Invalid response from Binance futures_exchange_info")

    _futures_exchange_info_cache = info
    return info

def valid_futures_symbols(force_refresh: bool = False) -> set[str]:
    global _valid_futures_symbols
    if _valid_futures_symbols is not None and not force_refresh:
        return _valid_futures_symbols
    info = futures_exchange_info_safe(force_refresh=force_refresh)
    symbols = {s.get("symbol", "").upper() for s in info.get("symbols", []) if s.get("status") == "TRADING"}
    _valid_futures_symbols = symbols
    return _valid_futures_symbols

def is_valid_futures_symbol(symbol: str) -> bool:
    try:
        return symbol.upper() in valid_futures_symbols()
    except Exception as e:
        level = logging.WARNING if SUPPRESS_BINANCE_WARNINGS else logging.ERROR
        logger.log(level, f"[Binance] is_valid_futures_symbol: exchangeInfo unavailable → soft-allow ({e})")
        return True

# =========================
# 💵 Futures Mark Price (HTTP ישיר)
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
        # החזר מהקאש אם יש
        cached = LAST_PRICE_CACHE.get(sym)
        if cached:
            return float(cached.get("price"))
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
# 📡 Public status helper
# =========================
def binance_http_status() -> Dict[str, Any]:
    now = time.time()
    return {
        "hosts": _BINANCE_FAPI_HOSTS,
        "last_host": _last_host,
        "last_json_ok": bool(_last_json_ok),
        "last_ts": int(_last_ts) if _last_ts else None,
        "circuit": {
            "is_open": _cb_is_open(now),
            "open_seconds_left": max(0, int(_cb_open_until - now)) if _cb_is_open(now) else 0,
            "failures": _cb_failures,
            "cooldown_next": _cb_cooldown,
            "threshold": _CB_FAIL_THRESHOLD,
            "base": _CB_COOLDOWN_BASE,
            "max": _CB_COOLDOWN_MAX,
        },
        "last_error": _last_error,
        "timeout": _DEFAULT_TIMEOUT,
        "testnet": USE_TESTNET,
    }













































































































