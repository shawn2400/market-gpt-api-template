# utils/symbols.py
from __future__ import annotations
import time
import re
from typing import Dict, Optional, Tuple, List
import httpx

__all__ = ["normalize_symbol", "SymbolsCache"]

# מרובדים נפוצים בפיוצ'רס
__QUOTES: Tuple[str, ...] = ("USDT", "USDC", "FDUSD", "BUSD")

_SPOT_EXI = "https://api.binance.com/api/v3/exchangeInfo"
_FUT_EXI  = "https://fapi.binance.com/fapi/v1/exchangeInfo"

class SymbolsCache:
    def __init__(self, market: str = "futures", ttl: int = 3600):
        self.market = "spot" if str(market).lower() == "spot" else "futures"
        self.ttl = int(ttl)
        self.ts: float = 0.0
        self.symbols: Dict[str, Dict] = {}  # SYMBOL -> raw
        self.base_to_quotes: Dict[str, List[str]] = {}

    def _endpoint(self) -> str:
        return _SPOT_EXI if self.market == "spot" else _FUT_EXI

    def _refresh(self) -> None:
        if (time.time() - self.ts) < self.ttl and self.symbols:
            return
        url = self._endpoint()
        with httpx.Client(timeout=6.0) as x:
            r = x.get(url)
            r.raise_for_status()
            data = r.json()
        syms = {}
        b2q: Dict[str, List[str]] = {}
        for s in (data.get("symbols") or []):
            status = (s.get("status") or s.get("contractStatus") or "TRADING")
            if status != "TRADING":
                continue
            sym = str(s.get("symbol") or "").upper()
            base = str(s.get("baseAsset") or "").upper()
            quote = str(s.get("quoteAsset") or "").upper()
            if not sym or not base or not quote:
                continue
            syms[sym] = s
            b2q.setdefault(base, []).append(quote)
        self.symbols = syms
        self.base_to_quotes = b2q
        self.ts = time.time()

    def find(self, candidate: str) -> Optional[str]:
        self._refresh()
        c = candidate.upper()
        if c in self.symbols:
            return c
        return None

    def best_with_base(self, base: str) -> Optional[str]:
        self._refresh()
        base = base.upper()
        quotes = self.base_to_quotes.get(base) or []
        # העדף USDT/FDUSD
        for q in ("USDT", "FDUSD", "USDC", "BUSD"):
            if q in quotes:
                sym = base + q
                if sym in self.symbols:
                    return sym
        # fallback כלשהו
        for q in quotes:
            sym = base + q
            if sym in self.symbols:
                return sym
        return None


_WS = re.compile(r"[\s\-/]+")

def _split_base_quote(s: str) -> Tuple[str, Optional[str]]:
    s = s.strip().upper()
    s = _WS.sub("", s)
    # "BTCUSDT" ארוך -> נסה לחלץ quote מוכר
    for q in __QUOTES:
        if s.endswith(q) and len(s) > len(q):
            return s[:-len(q)], q
    # "BTC/USDT" או "BTC-USDT" כבר קוזז ע"י regex למעלה, כך שאין מפריד
    return s, None

def _maybe_add_quote(base_or_symbol: str) -> List[str]:
    s = base_or_symbol.upper()
    # אם כבר נראה כמו SYMBOL מלא
    for q in __QUOTES:
        if s.endswith(q) and len(s) > len(q):
            return [s]
    # נסה כל quote מוכר
    return [s + q for q in __QUOTES]

def normalize_symbol(user_input: str, *, market: str = "futures", cache: Optional[SymbolsCache] = None) -> str:
    """
    מקבל קלט גמיש ("btc", "btc/usdt", "BTCUSDT") ומחזיר SYMBOL חוקי לפי exchangeInfo.
    """
    if not user_input or not str(user_input).strip():
        raise ValueError("empty symbol")

    market = "spot" if str(market).lower() == "spot" else "futures"
    c = cache or SymbolsCache(market=market)

    raw = str(user_input).upper().strip()
    raw = raw.replace("PERP", "").replace("_", "/")
    base, maybe_quote = _split_base_quote(raw)

    # רשימת מועמדים לפי קלט
    candidates: List[str] = []
    if maybe_quote:
        candidates.append(base + maybe_quote)
    else:
        candidates.extend(_maybe_add_quote(base))

    # נסה למצוא במדויק
    for cand in candidates:
        hit = c.find(cand)
        if hit:
            return hit

    # נסה "הטבת" base בלבד
    best = c.best_with_base(base)
    if best:
        return best

    raise ValueError(f"unknown symbol '{user_input}' for market={market}")



