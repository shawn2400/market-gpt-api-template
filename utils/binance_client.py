# utils/binance_client.py
from __future__ import annotations

import os
import time
import hmac
import json
import math
import hashlib
import logging
from typing import Any, Dict, Optional, Tuple

import httpx

logger = logging.getLogger("algogpt.binance")


# ============
# ENV & Config
# ============
def _clean_env(s: Optional[str]) -> str:
    """Remove whitespace/newlines/tabs and strip edges."""
    if not s:
        return ""
    return "".join(c for c in s if c not in "\r\n\t ").strip()


BINANCE_API_KEY = _clean_env(os.getenv("BINANCE_API_KEY"))
BINANCE_API_SECRET = _clean_env(os.getenv("BINANCE_API_SECRET"))

# Testnet toggle
USE_TESTNET = (os.getenv("BINANCE_TESTNET", "false").lower() in ("1", "true", "yes"))

# Base URLs – prefer explicit FUTURES var, then legacy names
FAPI_BASE = (
    os.getenv("BINANCE_FUTURES_HTTP_BASE")
    or os.getenv("BINANCE_FAPI_BASE")
    or ("https://testnet.binancefuture.com" if USE_TESTNET else "https://fapi.binance.com")
).rstrip("/")

HTTP_TIMEOUT = float(os.getenv("BINANCE_HTTP_TIMEOUT", "8.0"))
RECV_WINDOW = int(float(os.getenv("BINANCE_RECV_WINDOW", "10000")))
MAX_RETRIES = int(os.getenv("BINANCE_MAX_RETRIES", "5"))
BACKOFF_BASE = float(os.getenv("BINANCE_BACKOFF_BASE", "0.7"))  # seconds

# Optional tweaks
SUPPRESS_WARN = os.getenv("SUPPRESS_BINANCE_WARNINGS", "1") in ("1", "true", "yes")

if SUPPRESS_WARN:
    logging.getLogger("httpx").setLevel(logging.WARNING)


# ===============
# HTTP Client Wrap
# ===============
class _BinanceFutures:
    """
    Robust Binance Futures REST client (sync) with:
      - HMAC-SHA256 signing
      - Timestamp drift handling (-1021)
      - Retries with exponential backoff
      - Public & signed helpers
    """

    def __init__(self) -> None:
        self.api_key = BINANCE_API_KEY
        self.api_secret = BINANCE_API_SECRET
        self.base = FAPI_BASE
        self.timeout = HTTP_TIMEOUT
        self.recv_window = RECV_WINDOW
        self.max_retries = MAX_RETRIES
        self.backoff_base = BACKOFF_BASE
        self._time_offset_ms = 0  # server_time - local_time

        self._exchange_info_cache: Optional[Dict[str, Any]] = None

        self._client = httpx.Client(timeout=self.timeout, http2=False)

        if not self.api_key or not self.api_secret:
            logger.warning("[Binance] API keys missing – signed endpoints will fail.")

    # ---- Utilities ----
    def _now_ms(self) -> int:
        return int(time.time() * 1000)

    def _server_time_ms(self) -> int:
        """
        GET fapi/v1/time → {'serverTime': <ms>}
        """
        url = f"{self.base}/fapi/v1/time"
        r = self._client.get(url)
        r.raise_for_status()
        data = r.json()
        return int(data["serverTime"])

    def _sync_time(self) -> None:
        try:
            server_ms = self._server_time_ms()
            local_ms = self._now_ms()
            self._time_offset_ms = server_ms - local_ms
            logger.info(f"[Binance] Time synced. Offset={self._time_offset_ms} ms")
        except Exception as e:
            logger.error(f"[Binance] Time sync failed: {e}")

    def _headers(self) -> Dict[str, str]:
        return {"X-MBX-APIKEY": self.api_key} if self.api_key else {}

    def _sign(self, params: Dict[str, Any]) -> Tuple[str, str]:
        # urlencode in sorted key order (Binance accepts non-sorted too, sorted keeps stable)
        # Note: httpx handles params dict, but we must sign on the raw query string.
        items = []
        for k in sorted(params.keys()):
            v = params[k]
            items.append(f"{k}={v}")
        query = "&".join(items)
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            query.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return query, signature

    def _backoff(self, attempt: int) -> float:
        # exponential backoff with jitter
        base = self.backoff_base * (2 ** attempt)
        # cap backoff to a few seconds to avoid long stalls
        return min(base, 4.5)

    # ---- Core Requestors ----
    def _public_get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        url = f"{self.base}/{path.lstrip('/')}"
        for attempt in range(self.max_retries):
            try:
                r = self._client.get(url, params=params or {})
                r.raise_for_status()
                return r.json()
            except httpx.HTTPStatusError as e:
                status = e.response.status_code
                body = e.response.text
                logger.error(f"[Binance] public GET {path} failed ({status}): {body[:200]}")
                if status >= 500:
                    time.sleep(self._backoff(attempt))
                    continue
                raise
            except Exception as e:
                logger.error(f"[Binance] public GET {path} exception: {e}")
                time.sleep(self._backoff(attempt))
        raise RuntimeError(f"[Binance] public GET {path} exhausted retries")

    def _signed(self, method: str, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        if not self.api_key or not self.api_secret:
            raise RuntimeError("Binance API keys missing")

        params = dict(params or {})
        # timestamp with server offset (after sync)
        params.setdefault("timestamp", self._now_ms() + self._time_offset_ms)
        params.setdefault("recvWindow", self.recv_window)

        url = f"{self.base}/{path.lstrip('/')}"

        for attempt in range(self.max_retries):
            # Build signature on current params
            query, sig = self._sign(params)
            full_url = f"{url}?{query}&signature={sig}"
            try:
                r = self._client.request(method.upper(), full_url, headers=self._headers())
                # Handle 429/418 (ban/rate-limit) with backoff
                if r.status_code in (418, 429) or r.status_code >= 500:
                    logger.warning(
                        f"[Binance] signed {method} {path} rate/5xx ({r.status_code}): {r.text[:200]}"
                    )
                    time.sleep(self._backoff(attempt))
                    continue

                # If outside recvWindow (-1021), sync time and retry
                if r.status_code == 400:
                    try:
                        data = r.json()
                    except Exception:
                        data = {}
                    code = data.get("code")
                    if code == -1021:
                        logger.warning("[Binance] -1021 (timestamp). Syncing time and retrying...")
                        self._sync_time()
                        # refresh timestamp for next attempt
                        params["timestamp"] = self._now_ms() + self._time_offset_ms
                        continue

                r.raise_for_status()
                return r.json()

            except httpx.HTTPStatusError as e:
                body = e.response.text
                try:
                    err = e.response.json()
                except Exception:
                    err = {"raw": body}
                logger.error(
                    f"[Binance] signed {method} {path} failed {e.response.status_code}: {json.dumps(err)[:300]}"
                )
                # Non-retriable client errors (except -1021 handled above)
                if 400 <= e.response.status_code < 500:
                    raise
                time.sleep(self._backoff(attempt))

            except Exception as e:
                logger.error(f"[Binance] signed {method} {path} exception: {e}")
                time.sleep(self._backoff(attempt))

        raise RuntimeError(f"[Binance] signed {method} {path} exhausted retries")

    # =========
    # Endpoints
    # =========
    def ping(self) -> bool:
        try:
            self._public_get("fapi/v1/ping")
            return True
        except Exception as e:
            logger.error(f"[Binance] fapi_ping failed: {e}")
            return False

    def server_time(self) -> int:
        return self._server_time_ms()

    def premium_index(self, symbol: str) -> Dict[str, Any]:
        return self._public_get("fapi/v1/premiumIndex", {"symbol": symbol.upper()})

    def mark_price(self, symbol: str) -> Optional[float]:
        try:
            data = self.premium_index(symbol)
            mp = data.get("markPrice")
            if mp is not None:
                return float(mp)
        except Exception as e:
            logger.error(f"[Binance] mark_price error {symbol}: {e}")
        return None

    def exchange_info(self, force_refresh: bool = False) -> Dict[str, Any]:
        if self._exchange_info_cache is not None and not force_refresh:
            return self._exchange_info_cache
        self._exchange_info_cache = self._public_get("fapi/v1/exchangeInfo")
        return self._exchange_info_cache

    def symbol_info(self, symbol: str, force_refresh: bool = False) -> Optional[Dict[str, Any]]:
        info = self.exchange_info(force_refresh=force_refresh)
        for s in info.get("symbols", []):
            if s.get("symbol") == symbol.upper():
                return s
        return None

    def position_risk(self) -> list[dict]:
        """
        GET fapi/v2/positionRisk (signed)
        """
        try:
            res = self._signed("GET", "fapi/v2/positionRisk")
            if isinstance(res, list):
                return res
            return []
        except Exception as e:
            logger.error(f"[Binance] futures_open_positions failed: {e}")
            return []

    def balance(self) -> list[dict]:
        """
        GET fapi/v2/balance (signed)
        """
        try:
            res = self._signed("GET", "fapi/v2/balance")
            if isinstance(res, list):
                return res
            return []
        except Exception as e:
            logger.error(f"[Binance] balance failed: {e}")
            return []

    # Generic signed helpers (useful for routes/trader)
    def signed_get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        return self._signed("GET", path, params)

    def signed_post(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        return self._signed("POST", path, params)

    def signed_delete(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        return self._signed("DELETE", path, params)


# Singleton client
_CLIENT = _BinanceFutures()


# ========================
# Backward-compatible APIs
# ========================
def fapi_ping() -> bool:
    return _CLIENT.ping()

def futures_mark_price(symbol: str) -> Optional[float]:
    return _CLIENT.mark_price(symbol)

_futures_exchange_info_cache_shadow: Optional[Dict[str, Any]] = None

def futures_exchange_info_safe(force_refresh: bool = False) -> Dict[str, Any]:
    # keep name and behavior stable for existing imports
    global _futures_exchange_info_cache_shadow
    if _futures_exchange_info_cache_shadow is not None and not force_refresh:
        return _futures_exchange_info_cache_shadow
    _futures_exchange_info_cache_shadow = _CLIENT.exchange_info(force_refresh=force_refresh)
    return _futures_exchange_info_cache_shadow

def get_symbol_info(symbol: str, force_refresh: bool = False) -> Optional[dict]:
    return _CLIENT.symbol_info(symbol, force_refresh=force_refresh)

def futures_open_positions() -> list[dict]:
    return _CLIENT.position_risk()

def futures_balance() -> list[dict]:
    return _CLIENT.balance()


# ===========
# Self-checks
# ===========
if __name__ == "__main__":
    print("Ping:", fapi_ping())
    try:
        print("Server time:", _CLIENT.server_time())
    except Exception as e:
        print("Server time error:", e)

    # Signed check (will warn if keys missing)
    try:
        bal = futures_balance()
        print("Balance sample:", bal[:1])
    except Exception as e:
        print("Balance error:", e)












































































































































