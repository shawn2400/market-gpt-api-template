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
USE_TESTNET = os.getenv("BINANCE_TESTNET", "false").lower() in ("1", "true", "yes")

# Direct Binance
BINANCE_FAPI_BASE = (os.getenv("BINANCE_FAPI_BASE") or "https://fapi.binance.com/fapi/v1").rstrip("/")
BINANCE_HTTP_BASE = (os.getenv("BINANCE_HTTP_BASE") or "https://api.binance.com/api/v3").rstrip("/")

# Proxy fallback
BINANCE_PROXY_FAPI = (os.getenv("BINANCE_PROXY_FAPI") or "").rstrip("/")
BINANCE_PROXY_HTTP = (os.getenv("BINANCE_PROXY_HTTP") or "").rstrip("/")

SUPPRESS_BINANCE_WARNINGS = os.getenv("SUPPRESS_BINANCE_WARNINGS", "0").lower() in ("1", "true", "yes")
_DEFAULT_TIMEOUT = float(os.getenv("BINANCE_HTTP_TIMEOUT", "6.0"))
_MAX_RETRIES = int(os.getenv("BINANCE_MAX_RETRIES", "5"))

# Cache
LAST_PRICE_CACHE: Dict[str, Dict[str, Any]] = {}
_futures_exchange_info_cache: Optional[Dict[str, Any]] = None
_valid_futures_symbols: Optional[set[str]] = None


# =========================
# 🧩 Client
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
        client.API_URL = BINANCE_HTTP_BASE
        client.FUTURES_URL = BINANCE_FAPI_BASE

    return client


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
# 📊 Futures Exchange Info (עם Fallback)
# =========================
def futures_exchange_info_safe() -> Dict[str, Any]:
    global _futures_exchange_info_cache
    if _futures_exchange_info_cache is not None:
        return _futures_exchange_info_cache

    client = get_client()
    try:
        info = retry_call(lambda: client.futures_exchange_info(), "futures_exchange_info")
    except Exception as e:
        logger.warning(f"[Binance] Direct futures_exchange_info failed → trying proxy: {e}")
        if BINANCE_PROXY_FAPI:
            url = f"{BINANCE_PROXY_FAPI}/exchangeInfo"
            with httpx.Client(timeout=_DEFAULT_TIMEOUT) as http:
                r = http.get(url)
                r.raise_for_status()
                info = r.json()
        else:
            raise

    if not isinstance(info, dict) or "symbols" not in info:
        raise RuntimeError("Invalid response from Binance futures_exchange_info")

    _futures_exchange_info_cache = info
    return info


def valid_futures_symbols(force_refresh: bool = False) -> set[str]:
    global _valid_futures_symbols
    if _valid_futures_symbols is not None and not force_refresh:
        return _valid_futures_symbols
    info = futures_exchange_info_safe()
    symbols = {s.get("symbol", "").upper() for s in info.get("symbols", []) if s.get("status") == "TRADING"}
    _valid_futures_symbols = symbols
    return _valid_futures_symbols


def is_valid_futures_symbol(symbol: str) -> bool:
    return symbol.upper() in valid_futures_symbols()


# =========================
# 💵 Futures Mark Price (עם Fallback)
# =========================
def futures_mark_price(symbol: str) -> Optional[float]:
    sym = symbol.upper().strip()
    try:
        if not is_valid_futures_symbol(sym):
            raise RuntimeError(f"Invalid futures symbol {sym}")

        url = f"{BINANCE_FAPI_BASE}/premiumIndex"
        headers = {"Accept": "application/json", "User-Agent": "AlgoGPT"}

        with httpx.Client(timeout=_DEFAULT_TIMEOUT, http2=True) as client:
            r = client.get(url, params={"symbol": sym}, headers=headers)

        if r.status_code == 200 and r.headers.get("Content-Type", "").startswith("application/json"):
            data = r.json()
            price = float(data.get("markPrice"))
            LAST_PRICE_CACHE[sym] = {"price": price, "ts": int(time.time())}
            return price
        else:
            raise RuntimeError(f"Invalid direct response {r.status_code}")

    except Exception as e:
        logger.warning(f"[Binance] Direct mark_price failed → trying proxy: {e}")
        if not BINANCE_PROXY_FAPI:
            return None
        try:
            url = f"{BINANCE_PROXY_FAPI}/premiumIndex"
            with httpx.Client(timeout=_DEFAULT_TIMEOUT) as client:
                r = client.get(url, params={"symbol": sym})
            if r.status_code == 200:
                data = r.json()
                price = float(data.get("markPrice"))
                LAST_PRICE_CACHE[sym] = {"price": price, "ts": int(time.time())}
                return price
        except Exception as ex:
            logger.error(f"[Binance] Proxy mark_price also failed: {ex}")
            return None
    return None


# =========================
# 📌 Futures Open Positions
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
                        "leverage": int(p.get("leverage", 0)),
                        "side": "LONG" if amt > 0 else "SHORT",
                    })
            except Exception as e:
                logger.warning(f"[Binance] skip bad position: {e}")
        return out
    except Exception as e:
        raise RuntimeError(f"[Binance] futures_open_positions failed: {e}")








































































































