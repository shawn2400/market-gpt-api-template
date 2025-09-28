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
    from utils.binance_client import futures_exchange_info_safe as _fex  # type: ignore
    futures_exchange_info_safe = _fex  # type: ignore
except Exception as e:
    logger.warning("[Symbols] could not import futures_exchange_info_safe (%s)", e)
    futures_exchange_info_safe = _fallback_futures_info  # type: ignore

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

    def suggest(self, base: str, quote: str, limit: int = 6) -> List[str]:
        """
        הצעות סמלים בסגנון: <BASE><QUOTE> או התאמות חלקיות לפי התחלה/סוף.
        """
        self.ensure_fresh()
        base_u = str(base or "").upper()
        quote_u = str(quote or DEFAULT_QUOTE).upper()
        if not base_u:
            return []

        # עדיפות להצעה הישירה
        cand = f"{base_u}{quote_u}"
        out: List[str] = [cand] if cand in self._index else []

        # הוספת התאמות לפי prefix/suffix
        for sym in self._index.keys():
            if sym.startswith(base_u) and sym.endswith(quote_u):
                if sym not in out:
                    out.append(sym)
            if len(out) >= limit:
                break

        # אם עדיין אין, נסה QUOTE נפוצים
        if not out:
            for q in list(self._quotes)[:5]:
                s = f"{base_u}{q}"
                if s in self._index:
                    out.append(s)
                if len(out) >= limit:
                    break
        return out[:limit]

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
    """
    מנרמל סמלים מהמשתמש/קובץ לפורמט Binance:
      - מסיר תווים לא אלפאנומריים.
      - בודק האם הסימבול קיים ברשימת ההחלפה העדכנית (ע״י cache עם TTL).
      - אם חסר quote, מוסיף DEFAULT_QUOTE (לרוב USDT).
      - במידה ואינו קיים — ירים ValueError עם הצעות חלופיות.
    """
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

    # אם עדיין לא קיים — נסה להציע חלופות
    suggestions: List[str] = []
    try:
        suggestions = c.suggest(base or raw, q or DEFAULT_QUOTE, limit=6)
    except Exception:
        pass

    raise ValueError(
        f"Symbol '{symbol}' not found in {mkt}. "
        f"Try: {', '.join(suggestions) if suggestions else 'check symbol/market'}"
    )

# אופציונלי: רשימת פרפטואלים בצד ה-USDT (נוח ל-scaners/menus)
def list_perp_usdt_symbols(cache: Optional[SymbolsCache] = None) -> List[str]:
    info = futures_exchange_info_safe(force_refresh=False) or {}
    out: List[str] = []
    for s in (info.get("symbols") or []):
        if str(s.get("contractType") or "").upper() == "PERPETUAL" \
           and str(s.get("quoteAsset") or "").upper() == "USDT" \
           and str(s.get("status") or "") in ("TRADING", "PENDING_TRADING"):
            name = str(s.get("symbol") or "").upper()
            if name:
                out.append(name)
    return out

def symbol_filters(symbol: str, cache: Optional[SymbolsCache] = None) -> Dict[str, Any]:
    c = cache or SymbolsCache("futures")
    return c.filters(symbol)

__all__ = [
    "SymbolsCache", "normalize_symbol", "parse_symbol_parts",
    "list_perp_usdt_symbols", "symbol_filters",
    "DEFAULT_QUOTE", "SYMBOLS_TTL_SEC",
]

if __name__ == "__main__":
    c = SymbolsCache("futures")
    print("has normalize:", hasattr(__import__(__name__), "normalize_symbol"))
    print("quotes count:", len(c.quotes()))














