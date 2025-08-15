# utils/symbols.py
from __future__ import annotations

import os
import time
import re
import threading
from typing import Dict, Optional, Set

import httpx

# Binance bases (override via env if needed)
BINANCE_SPOT_HTTP_BASE = os.getenv("BINANCE_SPOT_HTTP_BASE", "https://api.binance.com").rstrip("/")
BINANCE_FUTURES_HTTP_BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com").rstrip("/")

# exchangeInfo refresh TTL (seconds)
_SYMBOLS_TTL = int(os.getenv("SYMBOLS_TTL_SECONDS", "21600"))  # 6h

# Common aliases / fixes per market
ALIASES_FUTURES: Dict[str, str] = {
    # In Binance Futures SHIB is 1000SHIBUSDT (not SHIBUSDT)
    "SHIBUSDT": "1000SHIBUSDT",
    "1KSHIBUSDT": "1000SHIBUSDT",
    "XBTUSDT": "BTCUSDT",
}
ALIASES_SPOT: Dict[str, str] = {
    "XBTUSDT": "BTCUSDT",
    "1KSHIBUSDT": "SHIBUSDT",  # spot uses plain SHIBUSDT
}

_PAIR_SEPS = re.compile(r"[/\-\_:]", re.IGNORECASE)


class SymbolsCache:
    """
    Symbols cache per market (futures/spot) with auto-refresh.
    - refresh() pulls exchangeInfo and builds active symbols set
    - normalize() canonicalizes input (X/Y → X\Y → XUSDT), applies aliases, validates
    """
    def __init__(self, market: str = "futures") -> None:
        self.market = "spot" if str(market).lower() == "spot" else "futures"
        self._symbols: Set[str] = set()
        self._last_refresh: float = 0.0
        self._lock = threading.Lock()

    def _base_url(self) -> str:
        return BINANCE_SPOT_HTTP_BASE if self.market == "spot" else BINANCE_FUTURES_HTTP_BASE

    def _exchange_info_path(self) -> str:
        return "/api/v3/exchangeInfo" if self.market == "spot" else "/fapi/v1/exchangeInfo"

    def _aliases(self) -> Dict[str, str]:
        return ALIASES_SPOT if self.market == "spot" else ALIASES_FUTURES

    def _needs_refresh(self) -> bool:
        return not self._symbols or (time.time() - self._last_refresh) > _SYMBOLS_TTL

    def refresh(self) -> None:
        with self._lock:
            if not self._needs_refresh():
                return
            url = self._base_url() + self._exchange_info_path()
            try:
                with httpx.Client(timeout=5.0) as x:
                    r = x.get(url)
                    r.raise_for_status()
                    data = r.json()
            except Exception as e:
                if not self._symbols:
                    raise RuntimeError(f"failed to fetch exchangeInfo ({self.market}): {e}")
                return

            new_syms: Set[str] = set()
            for s in (data.get("symbols") or []):
                try:
                    sym = str(s.get("symbol") or "").strip().upper()
                    if not sym:
                        continue
                    status = str(s.get("status") or "TRADING").upper()
                    # futures exchangeInfo sometimes lacks TRADING in same format—keep all
                    new_syms.add(sym)
                except Exception:
                    continue

            if new_syms:
                self._symbols = new_syms
                self._last_refresh = time.time()

    def _canon_pair(self, sym: str) -> str:
        s = (sym or "").strip().upper()
        if not s:
            return s
        s = _PAIR_SEPS.sub("", s)  # BTC/USDT -> BTCUSDT
        # If only base provided (e.g., BTC), default to USDT
        if s and (not s.endswith("USDT")) and (len(s) <= 6):
            s = s + "USDT"
        return s

    def normalize(self, symbol: str) -> str:
        if not symbol or not str(symbol).strip():
            raise ValueError("empty symbol")

        self.refresh()

        s = self._canon_pair(symbol)
        aliases = self._aliases()
        if s in aliases:
            s = aliases[s]

        if s not in self._symbols:
            # Last-chance fix for futures SHIB
            if self.market == "futures" and s == "SHIBUSDT":
                s2 = "1000SHIBUSDT"
                if s2 in self._symbols:
                    return s2
            raise ValueError(f"Invalid or unsupported symbol for {self.market}: {s}")

        return s


def normalize_symbol(symbol: str, market: str = "futures", cache: Optional[SymbolsCache] = None) -> str:
    c = cache or SymbolsCache(market=market)
    return c.normalize(symbol)



