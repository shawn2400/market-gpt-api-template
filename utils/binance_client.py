# utils/binance_client.py
from __future__ import annotations

import os, time, hmac, hashlib, logging, json, math
from typing import Any, Dict, Optional, Tuple
import httpx

logger = logging.getLogger("algogpt.binance")

# --- Env & Config ---
def _clean_env(s: Optional[str]) -> str:
    return "".join(c for c in s or "" if c not in "\r\n\t ").strip()

BINANCE_API_KEY = _clean_env(os.getenv("BINANCE_API_KEY"))
BINANCE_API_SECRET = _clean_env(os.getenv("BINANCE_API_SECRET"))
USE_TESTNET = os.getenv("BINANCE_TESTNET", "false").lower() in ("1", "true", "yes")

FAPI_BASE = (
    os.getenv("BINANCE_FUTURES_HTTP_BASE")
    or ("https://testnet.binancefuture.com" if USE_TESTNET else "https://fapi.binance.com")
).rstrip("/")

HTTP_TIMEOUT = float(os.getenv("BINANCE_HTTP_TIMEOUT", "8.0"))
RECV_WINDOW = int(float(os.getenv("BINANCE_RECV_WINDOW", "10000")))

# --- Client ---
class _BinanceFutures:
    def __init__(self):
        self.api_key = BINANCE_API_KEY
        self.api_secret = BINANCE_API_SECRET
        self.base = FAPI_BASE
        self.recv_window = RECV_WINDOW
        self._time_offset_ms = 0
        self._client = httpx.Client(timeout=HTTP_TIMEOUT)

    def _now_ms(self) -> int:
        return int(time.time() * 1000)

    def _sign(self, params: Dict[str, Any]) -> Tuple[str, str]:
        query = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        sig = hmac.new(self.api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        return query, sig

    def _headers(self) -> Dict[str, str]:
        return {"X-MBX-APIKEY": self.api_key}

    def _signed(self, method: str, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        if not self.api_key or not self.api_secret:
            raise RuntimeError("Missing Binance API keys")
        params = dict(params or {})
        params.setdefault("timestamp", self._now_ms() + self._time_offset_ms)
        params.setdefault("recvWindow", self.recv_window)
        query, sig = self._sign(params)
        url = f"{self.base}/{path}?{query}&signature={sig}"
        r = self._client.request(method.upper(), url, headers=self._headers())
        r.raise_for_status()
        return r.json()

    def _public_get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        url = f"{self.base}/{path}"
        r = self._client.get(url, params=params or {})
        r.raise_for_status()
        return r.json()

    # ---- Useful endpoints ----
    def mark_price(self, symbol: str) -> Optional[float]:
        try:
            data = self._public_get("fapi/v1/premiumIndex", {"symbol": symbol.upper()})
            return float(data.get("markPrice")) if "markPrice" in data else None
        except Exception as e:
            logger.error(f"[Binance] mark_price error {symbol}: {e}")
            return None

    def balance(self) -> list[dict]:
        return self._signed("GET", "fapi/v2/balance")

    def position_risk(self) -> list[dict]:
        return self._signed("GET", "fapi/v2/positionRisk")


# --- Singleton ---
_CLIENT = _BinanceFutures()

# --- Wrappers ---
def futures_mark_price(symbol: str) -> Optional[float]:
    return _CLIENT.mark_price(symbol)

def futures_balance() -> list[dict]:
    return _CLIENT.balance()

def futures_open_positions() -> list[dict]:
    return _CLIENT.position_risk()

# ✅ Compatibility shim for trader.py
def _signed_request(method: str, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
    """Shim to keep backward compatibility with trader.py"""
    return _CLIENT._signed(method, path, params)














































































































































