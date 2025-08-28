# utils/symbols.py
from __future__ import annotations

import os
import time
import re
from typing import Dict, Any, List, Optional, Tuple

try:
    # primary import (recommended)
    from utils.binance_client import futures_exchange_info_safe
except ImportError:
    # safe fallback for older builds (avoid hard crash on import)
    from utils.binance_client import _CLIENT as _BN   # type: ignore
    def futures_exchange_info_safe(force_refresh: bool = False) -> Dict[str, Any]:
        return _BN.exchange_info(force_refresh=force_refresh)  # type: ignore

DEFAULT_QUOTE = os.getenv("DEFAULT_QUOTE", "USDT").upper()
SYMBOLS_TTL_SEC = int(os.getenv("SYMBOLS_CACHE_TTL", "600"))

# quotes שנפוצים בבינאנס פיוצ'רס (מוגדרים גם דיפולטית אם אין cache)
COMMON_QUOTES = {"USDT", "USDC", "BUSD", "FDUSD", "TUSD", "BIDR", "TRY"}


class SymbolsCache:
    """
    Cache קליל ל-exchangeInfo של Binance Futures + עזרי פילטרים/עיגול.
    """
    def __init__(self, ttl_sec: int = SYMBOLS_TTL_SEC):
        self.ttl = max(30, int(ttl_sec))
        self._last: float = 0.0
        self._raw: Dict[str, Any] = {}
        self._index: Dict[str, Dict[str, Any]] = {}
        self._quotes: set[str] = set(COMMON_QUOTES)

    def _refresh(self, force: bool = False) -> None:
        now = time.time()
        if not force and self._raw and (now - self._last) < self.ttl:
            return
        info = futures_exchange_info_safe(force_refresh=force)
        self._raw = info or {}
        self._index = {s["symbol"]: s for s in self._raw.get("symbols", [])}
        # בנה סט של Quotes מתוך הרשימה בפועל
        quotes = set()
        for s in self._raw.get("symbols", []):
            q = s.get("quoteAsset")
            if q:
                quotes.add(q)
        if quotes:
            self._quotes = quotes
        self._last = now

    # API ציבורי
    def ensure_fresh(self, force: bool = False) -> None:
        self._refresh(force=force)

    def list_symbols(self, only_trading: bool = True) -> List[str]:
        self.ensure_fresh()
        out: List[str] = []
        for s in self._raw.get("symbols", []):
            if only_trading and s.get("status") != "TRADING":
                continue
            out.append(s["symbol"])
        return out

    def quotes(self) -> set[str]:
        self.ensure_fresh()
        return set(self._quotes)

    def get(self, symbol: str) -> Optional[Dict[str, Any]]:
        self.ensure_fresh()
        return self._index.get(symbol.upper())

    def valid(self, symbol: str) -> bool:
        return self.get(symbol) is not None

    def filters(self, symbol: str) -> Dict[str, Any]:
        s = self.get(symbol)
        if not s:
            raise ValueError(f"Unknown symbol: {symbol}")
        return {f["filterType"]: f for f in s.get("filters", [])}

    def tick_size(self, symbol: str) -> float:
        f = self.filters(symbol).get("PRICE_FILTER", {})
        return float(f.get("tickSize", "0.00000001"))

    def step_size(self, symbol: str) -> float:
        f = self.filters(symbol).get("LOT_SIZE", {})
        return float(f.get("stepSize", "0.00000001"))

    def min_qty(self, symbol: str) -> float:
        f = self.filters(symbol).get("LOT_SIZE", {})
        return float(f.get("minQty", "0"))

    def min_notional(self, symbol: str) -> float:
        f = self.filters(symbol).get("NOTIONAL") or self.filters(symbol).get("MIN_NOTIONAL") or {}
        return float(f.get("minNotional", "0"))

    def snap_price(self, symbol: str, price: float) -> float:
        tick = self.tick_size(symbol)
        if tick <= 0:
            return price
        return (int(price / tick)) * tick

    def snap_qty(self, symbol: str, qty: float) -> float:
        step = self.step_size(symbol)
        if step <= 0:
            return qty
        return (int(qty / step)) * step

    def suggest(self, base: str, quote: str = DEFAULT_QUOTE, limit: int = 5) -> List[str]:
        """
        מחזיר סימבולים אפשריים לפי base+quote (לדוג' "BTC"+"USDT" → ["BTCUSDT"])
        עם התאמות קלות כמו 1000SHIBUSDT וכו'.
        """
        self.ensure_fresh()
        base_u = base.upper()
        quote_u = quote.upper()
        hits = []
        for sym, s in self._index.items():
            if s.get("status") != "TRADING":
                continue
            if not sym.endswith(quote_u):
                continue
            if sym.startswith(base_u) or base_u in sym:
                hits.append(sym)
        hits.sort()
        return hits[:limit]


# Singleton cache חשוף לשימוש מיידי
SYMBOLS = SymbolsCache()


_sep_re = re.compile(r"[^A-Z0-9]+")

def _split_tokens(text: str) -> List[str]:
    text = text.strip().upper()
    # החלף מפרידים נפוצים עבור "BTC/USDT", "btc-usdt", "btc usdt"
    text = _sep_re.sub(" ", text)
    parts = [p for p in text.split() if p]()







