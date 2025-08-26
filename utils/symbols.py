# utils/symbols.py
from __future__ import annotations
import os, time, threading, requests
from typing import Optional, Set
from utils.binance_client import futures_exchange_info_safe

_SPOT_BASE = os.getenv("BINANCE_SPOT_HTTP_BASE", "https://api.binance.com")

class SymbolsCache:
    def __init__(self, market: str = "futures"):
        self.market = "spot" if str(market).lower() == "spot" else "futures"
        self._symbols: Set[str] = set()
        self._ts = 0.0
        self._lock = threading.Lock()
        self.ttl = 1800.0  # cache 30 דקות

    def _refresh(self):
        if self.market == "futures":
            info = futures_exchange_info_safe()
            symbols = set()
            for s in info.get("symbols", []):
                if str(s.get("contractType") or "").upper().endswith("PERPETUAL"):
                    symbols.add((s.get("symbol") or "").upper())
            self._symbols = symbols
        else:
            url = f"{_SPOT_BASE}/api/v3/exchangeInfo"
            r = requests.get(url, timeout=6)
            r.raise_for_status()
            info = r.json() or {}
            symbols = set()
            for s in info.get("symbols", []):
                if (s.get("status") or "").upper() == "TRADING":
                    symbols.add((s.get("symbol") or "").upper())
            self._symbols = symbols
        self._ts = time.time()

    def ensure(self):
        with self._lock:
            if not self._symbols or (time.time() - self._ts) > self.ttl:
                self._refresh()

    def has(self, symbol: str) -> bool:
        self.ensure()
        return symbol.upper() in self._symbols

def normalize_symbol(symbol: str, market: str = "futures", cache: Optional[SymbolsCache] = None) -> str:
    s = (symbol or "").upper().strip()
    if not cache:
        cache = SymbolsCache(market=market)
    cache.ensure()
    if not cache.has(s):
        return s
    return s






