# utils/symbols.py
from __future__ import annotations

import os, time, logging, re
from typing import Dict, Any, List, Optional, Tuple, Set
import httpx

logger = logging.getLogger("algogpt.symbols")

# ────────────────────────────────────────────────
# ENV / Defaults
# ────────────────────────────────────────────────
DEFAULT_QUOTE = (os.getenv("DEFAULT_QUOTE") or "USDT").upper()
SYMBOLS_TTL_SEC = int(os.getenv("SYMBOLS_CACHE_TTL", "900"))
SPOT_EXCHANGE_INFO_URL = os.getenv(
    "BINANCE_SPOT_EXCHANGE_INFO",
    "https://api.binance.com/api/v3/exchangeInfo",
)

COMMON_QUOTES: Set[str] = {
    "USDT", "USDC", "BUSD", "FDUSD", "TUSD", "BIDR", "TRY", "EUR", "BRL", "GBP"
}

# ────────────────────────────────────────────────
# Futures exchangeInfo safe loader
# ────────────────────────────────────────────────
def _fallback_futures_info(force_refresh: bool = False) -> Dict[str, Any]:
    return {"symbols": []}

try:
    from utils.binance_client import futures_exchange_info_safe as _fex
    futures_exchange_info_safe = _fex  # type: ignore
except Exception as e:
    logger.warning("[Symbols] could not import futures_exchange_info_safe (%s)", e)
    futures_exchange_info_safe = _fallback_futures_info

# ────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────
_sep_re = re.compile(r"[^A-Z0-9]+")

def _sanitize_symbol(sym: str) -> str:
    s = str(sym or "").strip().upper()
    if not s:
        return s
    s = _sep_re.sub(" ", s)
    parts = [p for p in s.split() if p]
    return "".join(parts)

# ────────────────────────────────────────────────
# SymbolsCache
# ────────────────────────────────────────────────
class SymbolsCache:
    def __init__(self, market: str = "futures", ttl_sec: int = SYMBOLS_TTL_SEC) -> None:
        self.market = "spot" if str(market).lower() == "spot" else "futures"
        self.ttl = max(30, int(ttl_sec))
        self._ts: float = 0.0
        self._raw: Dict[str, Any] = {}
        self._index: Dict[str, Dict[str, Any]] = {}
        self._quotes: Set[str] = set(COMMON_QUOTES)

    def _expired(self) -> bool:
        return (time.time() - self._ts) > self.ttl or not self._index

    def _fetch_spot_exchange_info(self) -> Dict[str, Any]:
        with httpx.Client(timeout=6.0) as x:
            r = x.get(SPOT_EXCHANGE_INFO_URL)
            r.raise_for_status()
            return r.json()

    def refresh(self, force: bool = False) -> None:
        if not force and not self._expired():
            return
        try:
            if self.market == "futures":
                info = futures_exchange_info_safe(force_refresh=True) or {}
            else:
                info = self._fetch_spot_exchange_info()
        except Exception as e:
            logger.warning("[SymbolsCache] refresh failed: %s", e)
            info = {"symbols": []}

        index: Dict[str, Dict[str, Any]] = {}
        quotes: Set[str] = set()
        for s in (info.get("symbols") or []):
            sym = str(s.get("symbol") or "").upper()
            if not sym:
                continue
            st = s.get("status")
            if st and st not in ("TRADING", "PENDING_TRADING"):
                continue
            index[sym] = s
            q = s.get("quoteAsset")
            if q:
                quotes.add(str(q).upper())

        self._raw = info
        self._index = index
        if quotes:
            self._quotes = quotes
        self._ts = time.time()

    # API
    def ensure_fresh(self, force: bool = False) -> None:
        if force or self._expired():
            self.refresh(force=True)

    def get_all(self) -> Set[str]:
        self.ensure_fresh()
        return set(self._index.keys())

    def exists(self, symbol: str) -> bool:
        self.ensure_fresh()
        return str(symbol).upper() in self._index

    def get(self, symbol: str) -> Optional[Dict[str, Any]]:
        self.ensure_fresh()
        return self._index.get(str(symbol).upper())

    def quotes(self) -> Set[str]:
        self.ensure_fresh()
        return set(self._quotes)

    def filters(self, symbol: str) -> Dict[str, Any]:
        s = self.get(symbol)
        if not s:
            raise ValueError(f"Unknown symbol: {symbol}")
        return {f["filterType"]: f for f in s.get("filters", [])}

# ────────────────────────────────────────────────
# Public helpers
# ────────────────────────────────────────────────
def parse_symbol_parts(symbol: str, cache: Optional[SymbolsCache] = None) -> Tuple[str, Optional[str]]:
    s = str(symbol or "").upper()
    if not s:
        return "", None
    c = cache or SymbolsCache("futures")
    quotes = sorted(c.quotes(), key=lambda q: -len(q))
    for q in quotes:
        if s.endswith(q):
            return s[:-len(q)], q
    return s, None

def normalize_symbol(symbol: str, market: str = "futures", cache: Optional[SymbolsCache] = None) -> str:
    if not symbol or not str(symbol).strip():
        raise ValueError("symbol is empty")

    mkt = "spot" if str(market).lower() == "spot" else "futures"
    c = cache or SymbolsCache(mkt)

    raw = _sanitize_symbol(symbol)
    if not raw:
        raise ValueError("symbol is empty")

    try:
        if c.exists(raw):
            return raw
    except Exception as e:
        logger.warning("[Symbols] cache.exists failed (%s) – returning raw", e)
        return raw

    base, q = parse_symbol_parts(raw, c)
    if q is None:
        candidate = f"{base}{DEFAULT_QUOTE}"
        try:
            if c.exists(candidate):
                return candidate
        except Exception:
            return candidate

    suggestions = []
    try:
        suggestions = c.suggest(base or raw, q or DEFAULT_QUOTE, limit=6)
    except Exception:
        pass

    raise ValueError(
        f"Symbol '{symbol}' not found in {mkt}. "
        f"Try: {', '.join(suggestions) if suggestions else 'check symbol/market'}"
    )

__all__ = ["SymbolsCache", "normalize_symbol", "parse_symbol_parts", "DEFAULT_QUOTE", "SYMBOLS_TTL_SEC"]

if __name__ == "__main__":
    c = SymbolsCache("futures")
    print("has normalize:", hasattr(__import__(__name__), "normalize_symbol"))
    print("quotes count:", len(c.quotes()))











