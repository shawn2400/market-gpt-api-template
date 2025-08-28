# utils/symbols.py
from __future__ import annotations

import os
import time
import logging
import re
from typing import Dict, Any, List, Optional, Tuple, Set

import httpx

logger = logging.getLogger("algogpt.symbols")

# ──────────────────────────────────────────────────────────────────────────────
# ENV / Defaults
# ──────────────────────────────────────────────────────────────────────────────
DEFAULT_QUOTE = (os.getenv("DEFAULT_QUOTE") or "USDT").upper()
SYMBOLS_TTL_SEC = int(os.getenv("SYMBOLS_CACHE_TTL", "900"))  # 15 דקות
SPOT_EXCHANGE_INFO_URL = os.getenv(
    "BINANCE_SPOT_EXCHANGE_INFO",
    "https://api.binance.com/api/v3/exchangeInfo",
)

COMMON_QUOTES: Set[str] = {
    "USDT", "USDC", "BUSD", "FDUSD", "TUSD", "BIDR", "TRY", "EUR", "BRL", "GBP"
}

# ניסיון ראשי לייבא exchangeInfo של Futures
try:
    from utils.binance_client import futures_exchange_info_safe
except Exception:
    # fallback בטוח – לא מפיל import
    from utils.binance_client import _CLIENT as _BN  # type: ignore

    def futures_exchange_info_safe(force_refresh: bool = False) -> Dict[str, Any]:  # type: ignore
        return _BN.exchange_info(force_refresh=force_refresh)  # type: ignore

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────
_sep_re = re.compile(r"[^A-Z0-9]+")

def _sanitize_symbol(sym: str) -> str:
    """
    מנרמל קלט: 'btc/usdt' → 'BTCUSDT', 'btc-usdt' → 'BTCUSDT', ' btc usdt ' → 'BTCUSDT'
    """
    s = str(sym or "").strip().upper()
    if not s:
        return s
    s = _sep_re.sub(" ", s)
    parts = [p for p in s.split() if p]
    return "".join(parts)

# ──────────────────────────────────────────────────────────────────────────────
# Symbols Cache
# ──────────────────────────────────────────────────────────────────────────────
class SymbolsCache:
    """
    Cache ל-exchangeInfo לפי שוק (spot / futures) עם TTL למניעת עומס.
    """
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
        if self.market == "futures":
            info = futures_exchange_info_safe(force_refresh=True)
        else:
            info = self._fetch_spot_exchange_info()

        index: Dict[str, Dict[str, Any]] = {}
        quotes: Set[str] = set()
        for s in (info.get("symbols") or []):
            sym = str(s.get("symbol") or "").upper()
            if not sym:
                continue
            status = s.get("status")
            # מסננים לא-פעילים
            if status and status not in ("TRADING", "PENDING_TRADING"):
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
        logger.info(f"[SymbolsCache] refreshed market={self.market} count={len(self._index)} quotes={len(self._quotes)}")

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

    # עזרים לפילטרים
    def tick_size(self, symbol: str) -> float:
        pf = self.filters(symbol).get("PRICE_FILTER", {})
        return float(pf.get("tickSize", "0.00000001"))

    def step_size(self, symbol: str) -> float:
        lf = self.filters(symbol).get("LOT_SIZE", {})
        return float(lf.get("stepSize", "0.00000001"))

    def min_qty(self, symbol: str) -> float:
        lf = self.filters(symbol).get("LOT_SIZE", {})
        return float(lf.get("minQty", "0"))

    def min_notional(self, symbol: str) -> float:
        nf = self.filters(symbol).get("NOTIONAL") or self.filters(symbol).get("MIN_NOTIONAL") or {}
        return float(nf.get("minNotional", "0"))

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

    def suggest(self, base: str, quote: str = DEFAULT_QUOTE, limit: int = 6) -> List[str]:
        """
        הצעות לסימבולים דומים לפי base ו־quote.
        """
        self.ensure_fresh()
        base_u = str(base).upper()
        quote_u = str(quote).upper()
        out: List[str] = []
        for sym, meta in self._index.items():
            if not sym.endswith(quote_u):
                continue
            st = meta.get("status")
            if st and st not in ("TRADING", "PENDING_TRADING"):
                continue
            if sym.startswith(base_u) or base_u in sym:
                out.append(sym)
        out.sort()
        return out[:limit]

# ──────────────────────────────────────────────────────────────────────────────
# Public helpers
# ──────────────────────────────────────────────────────────────────────────────
def parse_symbol_parts(symbol: str, cache: Optional[SymbolsCache] = None) -> Tuple[str, Optional[str]]:
    """
    מפצל 'BTCUSDT' ל־('BTC','USDT') לפי quotes ידועים.
    אם לא נמצא quote, מחזיר (SYMBOL, None).
    """
    s = str(symbol or "").upper()
    if not s:
        return "", None
    c = cache or SymbolsCache("futures")
    quotes = sorted(c.quotes(), key=lambda q: -len(q))  # הארוכים קודם
    for q in quotes:
        if s.endswith(q):
            return s[: -len(q)], q
    return s, None

def normalize_symbol(
    symbol: str,
    market: str = "futures",
    cache: Optional[SymbolsCache] = None,
) -> str:
    """
    מנרמל קלט לסימבול תקני:
    - מסיר מפרידים
    - משלים quote דיפולטי אם צריך
    - מאמת קיום ב-exchangeInfo; אחרת זורק ValueError עם הצעות.
    """
    if not symbol or not str(symbol).strip():
        raise ValueError("symbol is empty")

    mkt = "spot" if str(market).lower() == "spot" else "futures"
    c = cache or SymbolsCache(mkt)

    raw = _sanitize_symbol(symbol)
    if not raw:
        raise ValueError("symbol is empty")

    if c.exists(raw):
        return raw

    base, q = parse_symbol_parts(raw, c)
    if q is None:
        candidate = f"{base}{DEFAULT_QUOTE}"
        if c.exists(candidate):
            return candidate

    suggestions = c.suggest(base or raw, q or DEFAULT_QUOTE, limit=6)
    raise ValueError(
        f"Symbol '{symbol}' not found in {mkt} exchangeInfo. "
        f"Try: {', '.join(suggestions) if suggestions else 'check symbol/market'}"
    )

__all__ = [
    "SymbolsCache",
    "normalize_symbol",
    "parse_symbol_parts",
    "DEFAULT_QUOTE",
    "SYMBOLS_TTL_SEC",
]

# בדיקת עשן מקומית (לא תרוץ בפרודקשן)
if __name__ == "__main__":
    c = SymbolsCache("futures")
    print("has normalize:", hasattr(__import__(__name__), "normalize_symbol"))
    print("quotes count:", len(c.quotes()))










