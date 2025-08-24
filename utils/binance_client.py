# utils/binance_client.py
from __future__ import annotations
import os, time, logging
from typing import Any, Callable, Optional, Dict, List
import httpx

# ה-SDK נשאר רק לקריאות חתומות (positions וכו')
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException

logger = logging.getLogger("algogpt.binance")

# =========================
# 🔑 ENV
# =========================
BINANCE_API_KEY = (os.getenv("BINANCE_API_KEY") or "").strip()
BINANCE_API_SECRET = (os.getenv("BINANCE_API_SECRET") or "").strip()
USE_TESTNET = (os.getenv("BINANCE_TESTNET", "false").strip().lower() in ("1", "true", "yes"))

# בסיסי FAPI (ללא www) + אלטים לסיבוב
_BASE = (os.getenv("BINANCE_FAPI_BASE") or "https://fapi1.binance.com").rstrip("/")
_alts = (os.getenv("BINANCE_FAPI_ALTS") or "https://fapi2.binance.com,https://fapi3.binance.com")
_HOSTS = []
_seen = set()
for h in ([_BASE] + [x.strip() for x in _alts.split(",") if x.strip()]):
    h = h.rstrip("/")
    if h and h not in _seen:
        _seen.add(h)
        _HOSTS.append(h)

BINANCE_HTTP_BASE = (os.getenv("BINANCE_HTTP_BASE") or "https://api.binance.com").rstrip("/")

SUPPRESS_BINANCE_WARNINGS = (os.getenv("SUPPRESS_BINANCE_WARNINGS", "1").strip().lower() in ("1","true","yes"))
_DEFAULT_TIMEOUT = float(os.getenv("BINANCE_HTTP_TIMEOUT", "8.0"))
_MAX_RETRIES = int(os.getenv("BINANCE_MAX_RETRIES", "5"))

# Circuit Breaker (להתמודד עם WAF/HTML זמני)
CB_FAILS_FOR_OPEN = int(os.getenv("BINANCE_CB_FAILS_FOR_OPEN", "3"))     # כמה כשלונות רצופים פותחים CB
CB_COOLDOWN_SEC   = int(os.getenv("BINANCE_CB_COOLDOWN_SEC", "120"))     # כמה זמן לרדת מהגז
CB_MAX_COOLDOWN   = int(os.getenv("BINANCE_CB_MAX_COOLDOWN", "600"))     # תקרת cooldown מצטבר
CB_SOFT_ALLOW_EXCHANGE_INFO = (os.getenv("BINANCE_SOFT_ALLOW_EXCHANGE_INFO", "1").strip().lower() in ("1","true","yes"))

_UA = {
    "User-Agent": "AlgoGPT/2.x (+httpx; binance-shield)",
    "Accept": "application/json",
    "Connection": "close",
}

# =========================
# 🧠 State
# =========================
LAST_PRICE_CACHE: Dict[str, Dict[str, Any]] = {}
_futures_exchange_info_cache: Optional[Dict[str, Any]] = None
_valid_futures_symbols: Optional[set[str]] = None

_cb_open_until: float = 0.0
_cb_fails: int = 0
_cb_cooldown: int = CB_COOLDOWN_SEC

def _cb_is_open() -> bool:
    return time.time() < _cb_open_until

def _cb_on_success() -> None:
    global _cb_fails, _cb_cooldown, _cb_open_until
    _cb_fails = 0
    _cb_cooldown = CB_COOLDOWN_SEC
    _cb_open_until = 0.0

def _cb_on_failure(reason: str) -> None:
    """
    אם תופסים HTML/WAF/Redirect – מעלים fail-count. כשעוברים סף → פותחים CB.
    """
    global _cb_fails, _cb_cooldown, _cb_open_until
    _cb_fails += 1
    level = logging.WARNING if SUPPRESS_BINANCE_WARNINGS else logging.ERROR
    logger.log(level, f"[BinanceShield] failure={_cb_fails} reason={reason}")
    if _cb_fails >= CB_FAILS_FOR_OPEN:
        # פותח CB ומגדיל cooldown (עד תקרה)
        _cb_open_until = time.time() + _cb_cooldown
        _cb_cooldown = min(CB_MAX_COOLDOWN, _cb_cooldown * 2)
        logger.warning(f"[BinanceShield] circuit OPEN for {int(_cb_open_until - time.time())}s")

def _is_json(resp: httpx.Response) -> bool:
    ctype = (resp.headers.get("Content-Type") or "").lower()
    return ctype.startswith("application/json")

def _http_get_json(path: str, params: Optional[dict] = None, timeout: float = _DEFAULT_TIMEOUT) -> dict:
    """
    קריאה ישירה אל FAPI עם רוטציית דומיינים, ללא מעקב אחר הפניות,
    בדיקה שמחזירים JSON – אחרת נחשב WAF/HTML ונפעיל CB.
    """
    if _cb_is_open():
        raise RuntimeError("circuit_open")

    last_err: Optional[Exception] = None
    for base in _HOSTS:
        url = f"{base}/{path.lstrip('/')}"
        try:
            with httpx.Client(timeout=timeout, headers=_UA, follow_redirects=False, http2=True) as client:
                r = client.get(url, params=params)
            if r.status_code in (301,302,303,307,308):
                _cb_on_failure("redirect")
                last_err = RuntimeError(f"redirect to {r.headers.get('Location')}")
                continue
            if not _is_json(r):
                _cb_on_failure("non-json")
                last_err = RuntimeError("non-json (WAF/HTML)")
                continue
            r.raise_for_status()
            _cb_on_success()
            return r.json()
        except Exception as e:
            last_err = e
            # לא פותחים CB על שגיאות רשת רגילות – ננסה host הבא
            level = logging.WARNING if SUPPRESS_BINANCE_WARNINGS else logging.ERROR
            logger.log(level, f"[BinanceHTTP] GET {url} failed: {e}")
            continue
    raise RuntimeError(f"FAPI failed: {type(last_err).__name__}: {last_err}")

# =========================
# 🧩 Client (חתום בלבד)
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
        client.FUTURES_URL = f"{_BASE}/fapi/v1"

    return client

# Banner קטן לזיהוי קונפיג בזמן עלייה
try:
    logger.info({
        "event": "binance_client_mode",
        "hosts": _HOSTS,
        "timeout": _DEFAULT_TIMEOUT,
        "retries": _MAX_RETRIES,
        "cb_threshold": CB_FAILS_FOR_OPEN,
        "cb_cooldown": CB_COOLDOWN_SEC,
        "testnet": USE_TESTNET,
    })
except Exception:
    pass

# =========================
# 📊 Futures Exchange Info (עם SOFT-MODE)
# =========================
def futures_exchange_info_safe(force_refresh: bool = False) -> Dict[str, Any]:
    """
    לעולם לא מפיל את השירות.
    אם CB פתוח או מתקבלת תגובת WAF → במצב soft מחזיר cache/ריק,
    ובוודאי לא זורק חריגה שמפילה תהליכי רקע.
    """
    global _futures_exchange_info_cache
    if _futures_exchange_info_cache is not None and not force_refresh:
        return _futures_exchange_info_cache
    try:
        info = _http_get_json("/fapi/v1/exchangeInfo")
        if not isinstance(info, dict) or "symbols" not in info:
            raise RuntimeError("bad exchangeInfo shape")
        _futures_exchange_info_cache = info
        return info
    except Exception as e:
        level = logging.WARNING if SUPPRESS_BINANCE_WARNINGS else logging.ERROR
        logger.log(level, f"[Binance] exchangeInfo degraded: {e}")
        if _futures_exchange_info_cache:
            return _futures_exchange_info_cache
        # soft-mode: מחזיר מבנה ריק כדי לא לחסום זרימה
        if CB_SOFT_ALLOW_EXCHANGE_INFO:
            return {"timezone":"UTC","serverTime":int(time.time()*1000),"symbols":[]}
        return {}

def valid_futures_symbols(force_refresh: bool = False) -> set[str]:
    global _valid_futures_symbols
    if _valid_futures_symbols is not None and not force_refresh:
        return _valid_futures_symbols
    info = futures_exchange_info_safe(force_refresh=force_refresh)
    symbols = {s.get("symbol","").upper() for s in info.get("symbols", []) if s.get("status") == "TRADING"}
    _valid_futures_symbols = symbols
    return _valid_futures_symbols

def is_valid_futures_symbol(symbol: str) -> bool:
    try:
        syms = valid_futures_symbols()
        # אם אין כלום (WAF/CB), אל תחסום סימבול – אפשר “soft-allow”
        return True if not syms else (symbol.upper() in syms)
    except Exception as e:
        level = logging.WARNING if SUPPRESS_BINANCE_WARNINGS else logging.ERROR
        logger.log(level, f"[Binance] is_valid_futures_symbol degraded: {e}")
        return True

# =========================
# 💵 Futures Mark Price (קשיח + קאש)
# =========================
def futures_mark_price(symbol: str) -> Optional[float]:
    sym = symbol.upper().strip()
    try:
        data = _http_get_json("/fapi/v1/premiumIndex", params={"symbol": sym})
        if isinstance(data, dict) and "markPrice" in data:
            price = float(data["markPrice"])
            LAST_PRICE_CACHE[sym] = {"price": price, "ts": int(time.time())}
            return price
        raise RuntimeError(f"unexpected premiumIndex payload type={type(data)}")
    except Exception as e:
        # לא מפיל את השרת. מחזיר קאש אם יש.
        level = logging.WARNING if SUPPRESS_BINANCE_WARNINGS else logging.ERROR
        logger.log(level, f"[Binance] markPrice degraded {sym}: {e}")
        cached = LAST_PRICE_CACHE.get(sym)
        if cached and "price" in cached:
            return float(cached["price"])
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
        # גם כאן — לא מפילים שירותים אחרים
        raise RuntimeError(f"[Binance] futures_open_positions failed: {e}")

# =========================
# 🔁 Retry helper (לקריאות חתומות בלבד)
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













































































































