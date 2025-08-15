# utils/symbols.py
from __future__ import annotations
import time
from typing import Optional, Set, Dict, List

import httpx

BINANCE_FAPI = "https://fapi.binance.com"
BINANCE_SPOT = "https://api.binance.com"

# קווטים נפוצים – נשתמש ב-USDT כברירת מחדל אם לא הועבר
_QUOTES = ("USDT", "BUSD", "USDC", "FDUSD", "TUSD")

# חלק מהזוגות בבינאנס פיוצ'רס מגיעים בפורמט "1000SHIBUSDT", "1000PEPEUSDT"
_THOUSANDS_BASES = {"SHIB", "PEPE"}

def _now() -> float:
    return time.time()

class SymbolsCache:
    """
    קאש קליל לשמות סימבולים לפי שוק (futures/spot), עם ריענון מ-exchangeInfo.
    שימוש:
        fut = SymbolsCache(market="futures")
        sym = normalize_symbol("avax", market="futures", cache=fut)  # → "AVAXUSDT"
    """
    def __init__(self, market: str = "futures", ttl_sec: int = 900) -> None:
        self.market = "spot" if str(market).lower() == "spot" else "futures"
        self.ttl = int(ttl_sec)
        self._symbols: Set[str] = set()
        self._last_fetch: float = 0.0

    def _endpoint(self) -> str:
        if self.market == "spot":
            return f"{BINANCE_SPOT}/api/v3/exchangeInfo"
        return f"{BINANCE_FAPI}/fapi/v1/exchangeInfo"

    def refresh(self, force: bool = False) -> None:
        if not force and (_now() - self._last_fetch) < self.ttl and self._symbols:
            return
        try:
            with httpx.Client(timeout=6.0) as x:
                r = x.get(self._endpoint())
                r.raise_for_status()
                data = r.json()
        except Exception:
            # אל תשבור — אם אין דאטה קודם, נשאיר סט ריק (normalize יטיל חריגה אם לא יימצא)
            return

        try:
            syms = set()
            for s in (data.get("symbols") or []):
                name = str(s.get("symbol") or "").upper().strip()
                if not name:
                    continue
                st = str(s.get("status") or "").upper()
                if st and st not in ("TRADING", "PENDING_TRADING"):
                    continue
                syms.add(name)
            if syms:
                self._symbols = syms
                self._last_fetch = _now()
        except Exception:
            pass

    def all(self) -> Set[str]:
        self.refresh(force=False)
        return set(self._symbols)


def _maybe_add_quote(sym_u: str) -> List[str]:
    """אם לא סופק קווט ידוע, ננסה לצרף USDT."""
    for q in _QUOTES:
        if sym_u.endswith(q):
            return [sym_u]
    return [sym_u + "USDT", sym_u]  # נעדיף עם USDT, אבל נבדוק גם את המקור ליתר ביטחון


def _thousands_variants(sym_u: str) -> List[str]:
    """
    החזר וריאציות '1000' לבייסים ידועים אם לא קיימים.
    לדוגמה: SHIBUSDT → 1000SHIBUSDT
    """
    out: List[str] = []
    for q in _QUOTES:
        if sym_u.endswith(q):
            base = sym_u[: -len(q)]
            if base and base in _THOUSANDS_BASES and not base.startswith("1000"):
                out.append(f"1000{base}{q}")
            break
    return out


def normalize_symbol(
    symbol: str,
    *,
    market: str = "futures",
    cache: Optional[SymbolsCache] = None,
) -> str:
    """
    נרמול סימבול לקאנוני של בינאנס:
      - אותיות גדולות
      - הוספת USDT אם לא הועבר קווט
      - התאמות 1000SHIB/1000PEPE בפיוצ'רס
      - אימות מול exchangeInfo (דרך הקאש שנמסר)
    זורק ValueError אם לא נמצא סימבול תקין.
    """
    if not symbol or not isinstance(symbol, str):
        raise ValueError("symbol is required")

    sym_u = symbol.strip().upper().replace(" ", "")
    mrk = "spot" if str(market).lower() == "spot" else "futures"

    # קאש (אם לא נמסר – ניצור קצר-חיים)
    local_cache = cache or SymbolsCache(market=mrk, ttl_sec=300)
    symbols = local_cache.all()

    # רשימת מועמדים לבדיקה
    candidates: List[str] = []
    candidates.extend(_maybe_add_quote(sym_u))

    # אם הושלם לקווט → נייצר גם וריאציית 1000 לבייסים הרלוונטיים
    extra = []
    for c in list(candidates):
        extra.extend(_thousands_variants(c))
    candidates.extend(extra)

    # בדיקה מול הקאש; אם לא מצאנו, נרענן פעם אחת
    for c in candidates:
        if c in symbols:
            return c

    local_cache.refresh(force=True)
    symbols = local_cache.all()
    for c in candidates:
        if c in symbols:
            return c

    suggestions = [c for c in candidates if c.startswith("1000")]
    hint = f" (did you mean: {', '.join(suggestions[:3])})" if suggestions else ""
    raise ValueError(f"Unknown/unsupported symbol '{symbol}' for {mrk}{hint}")

