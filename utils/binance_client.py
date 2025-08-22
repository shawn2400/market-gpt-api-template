# utils/binance_client.py
# =========================
# מודול לניהול קריאות Binance API (Futures/Spot)
# כולל: Client factory, retries, מחיר עתידי (markPrice), Funding cache
# =========================

from __future__ import annotations
import os, time, logging
from typing import Any, Callable, Optional, Dict, List
import httpx
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException

# 🚀 Cache פנימי
LAST_PRICE_CACHE: Dict[str, Dict[str, Any]] = {}

logger = logging.getLogger("algogpt.binance")

# =========================
# ENV / Config
# =========================
BINANCE_API_KEY = (os.getenv("BINANCE_API_KEY") or "").strip()
BINANCE_API_SECRET = (os.getenv("BINANCE_API_SECRET") or "").strip()
USE_TESTNET = (os.getenv("BINANCE_TESTNET", "false").strip().lower() in ("1", "true", "yes"))
PRICE_MONITOR_DISABLE = (os.getenv("PRICE_MONITOR_DISABLE", "false").strip().lower() in ("1", "true", "yes"))

SUPPRESS_BINANCE_WARNINGS = os.getenv("SUPPRESS_BINANCE_WARNINGS", "0").strip() in ("1", "true", "yes")

# ✅ בסיסי FAPI עם רוטציה
_BINANCE_FAPI_BASES: List[str] = [
    (os.getenv("BINANCE_FAPI_BASE") or "https://fapi.binance.com").rstrip("/"),
    "https://fapi1.binance.com",
    "https://fapi2.binance.com",
    "https://fapi3.binance.com",
]

_DEFAULT_TIMEOUT = float(os.getenv("BINANCE_HTTP_TIMEOUT", "6.0"))
_MAX_RETRIES = int(os.getenv("BINANCE_MAX_RETRIES", "5"))

# =========================
# Client factory
# =========================
def get_client() -> Client:
    if not BINANCE_API_KEY or not BINANCE_API_SECRET:
        raise RuntimeError("Missing BINANCE_API_KEY or BINANCE_API_SECRET")

    client = Client(api_key=BINANCE_API_KEY, api_secret=BINANCE_API_SECRET)

    if USE_TESTNET:
        logger.warning("⚠️ Using Binance TESTNET endpoints")
        client.API_URL = "https://testnet.binance.vision/api"
        client.FUTURES_URL = "https://testnet.binancefuture.com/fapi/v1"
    else:
        client.API_URL = "https://api.binance.com/api"
        client.FUTURES_URL = "https://fapi.binance.com/fapi/v1"

    return client

# =========================
# Retry helper
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
# Futures Exchange Info cache
# =========================
_futures_exchange_info_cache: Optional[Dict[str, Any]] = None
_valid_futures_symbols: Optional[set[str]] = None

def futures_exchange_info_safe() -> Dict[str, Any]:
    global _futures_exchange_info_cache
    if _futures_exchange_info_cache is not None:
        return _futures_exchange_info_cache
    client = get_client()
    info = retry_call(lambda: client.futures_exchange_info(), "futures_exchange_info")
    if isinstance(info, dict):
        _futures_exchange_info_cache = info
    return info

def valid_futures_symbols(force_refresh: bool = False) -> set[str]:
    global _valid_futures_symbols
    if _valid_futures_symbols is not None and not force_refresh:
        return _valid_futures_symbols
    info = futures_exchange_info_safe()
    symbols = set()
    for s in info.get("symbols", []):
        if s.get("status") == "TRADING":
            symbols.add(s.get("symbol", "").upper())
    _valid_futures_symbols = symbols
    return _valid_futures_symbols

def is_valid_futures_symbol(symbol: str) -> bool:
    return symbol.upper() in valid_futures_symbols()

# =========================
# Futures Mark Price (SAFE + funding + cache)
# =========================
def futures_mark_price_dict(symbol: str, tries: int = _MAX_RETRIES) -> Dict[str, Any]:
    sym = symbol.upper().strip()

    if not is_valid_futures_symbol(sym):
        raise RuntimeError(f"[Binance] Symbol {sym} is not valid in Futures")

    if PRICE_MONITOR_DISABLE:
        rec = LAST_PRICE_CACHE.get(sym)
        if rec and "price" in rec:
            return {"symbol": sym, "markPrice": str(rec["price"]), "ts": rec.get("ts")}
        raise RuntimeError(f"[Binance] WS/Cache miss for {sym}")

    last_err: Optional[str] = None
    headers = {"Accept": "application/json", "User-Agent": "AlgoGPT-binance-client"}

    for attempt in range(1, tries + 1):
        for base in _BINANCE_FAPI_BASES:
            url = f"{base}/fapi/v1/premiumIndex"
            try:
                with httpx.Client(timeout=_DEFAULT_TIMEOUT, http2=True) as client:
                    r = client.get(url, params={"symbol": sym}, headers=headers)

                if r.status_code == 200:
                    ctype = r.headers.get("Content-Type", "")
                    if ctype.startswith("application/json"):
                        data = r.json()
                        if isinstance(data, dict) and "markPrice" in data:
                            return data
                        else:
                            last_err = "No markPrice in JSON"
                    else:
                        last_err = f"Invalid content-type {ctype}"
                        level = logging.WARNING if SUPPRESS_BINANCE_WARNINGS else logging.ERROR
                        logger.log(level, f"[Binance] {sym} got non-JSON from {base}")
                        continue
                else:
                    last_err = f"{r.status_code} {r.text[:80]}"
                    level = logging.WARNING if SUPPRESS_BINANCE_WARNINGS else logging.ERROR
                    logger.log(level, f"[Binance] {sym} invalid response from {base}: {last_err}")
            except Exception as e:
                last_err = f"{type(e).__name__}: {e}"
                level = logging.WARNING if SUPPRESS_BINANCE_WARNINGS else logging.ERROR
                logger.log(level, f"[Binance] {sym} exception on {base}: {last_err}")
        time.sleep(0.35 * attempt)

    # ✅ Fallback ל־Cache
    rec = LAST_PRICE_CACHE.get(sym)
    if rec and "price" in rec:
        return {"symbol": sym, "markPrice": str(rec["price"]), "ts": rec.get("ts")}

    raise RuntimeError(f"[Binance] futures_mark_price_dict({sym}) failed after {tries} tries: {last_err}")


def futures_mark_price(symbol: str) -> Optional[float]:
    """
    מחזיר מחיר נוכחי (markPrice) ושומר אותו ב־Cache.
    אם יש גם fundingRate → נשמור ונחזיר.
    """
    sym = symbol.upper()
    try:
        data = futures_mark_price_dict(sym)
        price = float(data.get("markPrice") or 0.0)
        funding = float(data.get("fundingRate") or 0.0) if data.get("fundingRate") else None
        ts = data.get("ts") or int(time.time())

        # ✅ עדכון Cache
        LAST_PRICE_CACHE[sym] = {
            "price": price,
            "fundingRate": funding,
            "nextFundingTime": data.get("nextFundingTime"),
            "ts": ts
        }

        return price

    except Exception as e:
        level = logging.WARNING if SUPPRESS_BINANCE_WARNINGS else logging.ERROR
        logger.log(level, {"event": "futures_mark_price_error", "symbol": sym, "error": str(e)})
        return None


def get_cached_symbol_info(symbol: str) -> Optional[Dict[str, Any]]:
    """
    Utility: מחזיר מה Cache גם מחיר וגם Funding אם יש.
    """
    return LAST_PRICE_CACHE.get(symbol.upper())































































































