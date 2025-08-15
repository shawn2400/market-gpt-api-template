# utils/symbols.py
from __future__ import annotations
import time
from typing import Dict, Set, List, Optional
import httpx

BINANCE_SPOT_EXINFO = "https://api.binance.com/api/v3/exchangeInfo"
BINANCE_FAPI_EXINFO = "https://fapi.binance.com/fapi/v1/exchangeInfo"

# קוואוטים נפוצים (נשתמש בניסיון לפי סדר)
__QUOTES: List[str] = ["USDT", "USDC", "FDUSD", "TUSD", "BUSD", "TRY"]

class SymbolsCache:
    def __init__(self, market: str = "futures", ttl: int = 900):
        self.market = "spot" if str(market).lower() == "spot" else "futures"
        self.ttl = int(ttl)
        self._t0: float = 0.0
        self.symbols: Set[str] = set()
        self.bases: Set[str] = set()

    def _expired(self) -> bool:
        return (time.time() - self._t0) > self.ttl or not self.symbols

    def _endpoint(self) -> str:
        return BINANCE_SPOT_EXINFO if self.market == "spot" else BINANCE_FAPI_EXINFO

    def refresh(self) -> None:
        url = self._endpoint()
        with httpx.Client(timeout=6.0) as x:
            r = x.get(url)
            r.raise_for_status()
            data = r.json()
        syms = set()
        bases = set()
        for s in data.get("symbols", []):
            sym = str(s.get("symbol", "")).upper()
            st = str(s.get("status", "")).upper()
            if not sym or st not in ("TRADING", "PENDING_TRADING", "BREAK"):
                continue
            syms.add(sym)
            bases.add(str(s.get("baseAsset", "")).upper())
        self.symbols = syms
        self.bases = bases
        self._t0 = time.time()

    def ensure(self) -> None:
        if self._expired():
            self.refresh()

def _strip(sym: str) -> str:
    s = "".join(ch for ch in sym if ch.isalnum())
    return s.upper()

def _maybe_add_quote(sym_u: str) -> List[str]:
    # אם קיבלנו כבר quote – נחזיר אותו קודם
    out = [sym_u]
    # אחרת ננסה לצרף קוואוטים בניסיון
    for q in __QUOTES:
        if not sym_u.endswith(q):
            out.append(sym_u + q)
    return out

def normalize_symbol(symbol: str, market: str = "futures", cache: Optional[SymbolsCache] = None) -> str:
    sym_u = _strip(symbol)
    c = cache or SymbolsCache(market=market)
    c.ensure()

    # אם כבר תקין
    if sym_u in c.symbols:
        return sym_u

    # אם המשתמש נתן רק base (BTC / ETH / SOL...)
    candidates: List[str] = []
    # אם יש מפריד, נמחק וננסה
    candidates.extend(_maybe_add_quote(sym_u))

    for cand in candidates:
        if cand in c.symbols:
            return cand

    # ניסיון לפצל ידנית (btc/usdt, btc-usdt, btc_usdt)
    for sep in ("/", "-", "_"):
        if sep in symbol:
            b, q = symbol.replace(" ", "").upper().split(sep, 1)
            z = _strip(b + q)
            if z in c.symbols:
                return z

    raise ValueError(f"Unknown or unsupported symbol '{symbol}' for {c.market}")




