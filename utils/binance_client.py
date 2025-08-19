# utils/binance_client.py
from __future__ import annotations
import os
import time
import threading
from typing import Callable, Any, Dict, Optional, List, Tuple
import json
import requests

from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException

# ---- Bases & Domains rotation (כולל מראות חלופיות) ----
_SPOT_HTTP_BASE = os.getenv("BINANCE_SPOT_HTTP_BASE", "https://api.binance.com").rstrip("/")
_FUT_PRIMARY    = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com").rstrip("/")
_FUT_DOMAIN_POOL: List[str] = [
    _FUT_PRIMARY,
    "https://fapi1.binance.com",
    "https://fapi2.binance.com",
    "https://fapi3.binance.com",
]

_client: Optional[Client] = None
_client_lock = threading.Lock()

_ex_info_cache: Dict[str, Any] | None = None
_ex_info_ts: float = 0.0
_EX_TTL = float(os.getenv("EXCHANGEINFO_TTL_SEC", "1800"))  # 30 דקות

# --- API Keys (ניקוי תווי רווח/שורה) ---
_api_key = (os.getenv("BINANCE_API_KEY") or "").strip()
_api_secret = (os.getenv("BINANCE_API_SECRET") or "").strip()

# ---- Shared HTTP session (headers "אמיתיים") ----
_requests_session = requests.Session()
_requests_session.trust_env = False  # הימנע מפרוקסי סביבתיים מפתיעים
_requests_session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "X-MBX-APIKEY": _api_key or "",
})

_DEFAULT_TIMEOUT = float(os.getenv("BINANCE_HTTP_TIMEOUT_SEC", "6.0"))

def get_client() -> Client:
    """Client יחיד מושחל-בטוח, עם בסיסי API מעודכנים."""
    global _client
    with _client_lock:
        if _client is None:
            c = Client(_api_key, _api_secret)
            c.API_URL = _SPOT_HTTP_BASE
            # python-binance משתמש ב-FUTURES_URL ל-UM futures
            c.FUTURES_URL = _FUT_PRIMARY
            _client = c
        return _client

def get_futures_client() -> Client:
    return get_client()

# ---- HTTP helpers עם רוטציית דומיינים ----
def _is_cloudfront_block(resp: requests.Response) -> bool:
    ct = resp.headers.get("Content-Type", "")
    if "text/html" in ct.lower():
        # דף שגיאת CloudFront מגיע כ-HTML
        return True
    # לעתים מחזיר 403 עם JSON? ננסה לנחש:
    if resp.status_code == 403:
        return True
    return False

def _http_get_json(path: str, params: Optional[Dict[str, Any]] = None, label: str = "") -> Tuple[Dict[str, Any], str]:
    """מנסה GET JSON עם רוטציית דומיינים. מחזיר (json, base_used)."""
    last_err: Optional[Exception] = None
    for idx, base in enumerate(_FUT_DOMAIN_POOL):
        url = f"{base}{path}"
        try:
            r = _requests_session.get(url, params=params, timeout=_DEFAULT_TIMEOUT)
            # אם CloudFront/HTML – ננסה דומיין הבא
            if _is_cloudfront_block(r):
                last_err = RuntimeError(f"CloudFront 403/HTML from {url}")
                continue
            r.raise_for_status()
            # וודא JSON
            ct = r.headers.get("Content-Type", "")
            if "application/json" not in ct.lower():
                # ננסה עדיין לפרש JSON (חלק מהפרוקסים מציינים טעות ב-CT)
                try:
                    data = r.json()
                except Exception as je:
                    raise RuntimeError(f"Non-JSON response from {url}") from je
            else:
                data = r.json()
            if isinstance(data, dict):
                return data, base
            # אם זו רשימה – נארוז בתור dict סטנדרטי
            return {"data": data}, base
        except Exception as e:
            last_err = e
            # backoff קצר
            time.sleep(0.25 * (idx + 1))
            continue
    if last_err:
        raise last_err
    raise RuntimeError(f"{label or 'GET'} failed (no domains reachable)")

# ---- Retry helper ----
def _retry_call(fn: Callable[[], Any], label: str, tries: int = 3, delay: float = 0.4):
    last = None
    for i in range(tries):
        try:
            return fn()
        except (BinanceAPIException, BinanceRequestException, Exception) as e:
            last = e
            time.sleep(delay * (2 ** i))
    if last:
        raise last
    raise RuntimeError(f"{label} failed")

# ---- Public/Meta ----
def futures_exchange_info_safe() -> Dict[str, Any]:
    """ExchangeInfo עם קאש ו-TTL כדי להפחית עומסים/בלוקים."""
    global _ex_info_cache, _ex_info_ts
    now = time.time()
    if _ex_info_cache and (now - _ex_info_ts) < _EX_TTL:
        return _ex_info_cache
    client = get_futures_client()
    data = _retry_call(lambda: client.futures_exchange_info(), "futures_exchange_info", tries=3)
    _ex_info_cache = data or {}
    _ex_info_ts = now
    return _ex_info_cache

def futures_ping() -> bool:
    """פינג ציבורי עם רוטציית דומיינים. לא נזרוק חריגות — נחזיר False אם נכשל."""
    try:
        # נתיב פינג תקין ל-UM Futures
        data, base = _http_get_json("/fapi/v1/ping", params=None, label="futures_ping")
        # פינג תקין מחזיר גוף ריק/{} → אם עברנו סטטוס 200, זה טוב
        return True
    except Exception:
        return False

def futures_mark_price(symbol: str) -> Dict[str, Any]:
    """קריאת Mark Price (premiumIndex). מחזירה dict עקבי, או {"ok": False, "error": "..."}."""
    sym = symbol.upper()
    try:
        data, base = _http_get_json("/fapi/v1/premiumIndex", params={"symbol": sym}, label="premiumIndex")
        # תקינה: שדה markPrice קיים
        price_str = str(data.get("markPrice") or "")
        mark_price = float(price_str) if price_str else None
        return {
            "ok": True,
            "symbol": sym,
            "markPrice": mark_price,
            "raw": data,
            "endpoint": base,
        }
    except Exception as e:
        return {
            "ok": False,
            "symbol": sym,
            "error": str(e),
        }

# ---- Convenience לבריאות מערכת (בשימוש health_full.py) ----
def ping_and_info() -> Dict[str, Any]:
    """פינג + החלפת דומיינים + דגימת exchangeInfo קלה כדי לאמת קישוריות."""
    ping_ok = futures_ping()
    info_ok = False
    symbols_cnt = None
    err = None
    if ping_ok:
        try:
            ex = futures_exchange_info_safe()
            symbols = ex.get("symbols") or []
            symbols_cnt = len(symbols)
            info_ok = symbols_cnt > 0
        except Exception as e:
            err = str(e)
            info_ok = False
    return {
        "ping_ok": ping_ok,
        "info_ok": info_ok,
        "symbols": symbols_cnt,
        "error": err,
    }


































