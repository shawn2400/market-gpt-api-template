# utils/symbols.py
from __future__ import annotations

import re
import time
from typing import Optional, Dict, Set, List

import httpx

BINANCE_FAPI = "https://fapi.binance.com"
BINANCE_SPOT = "https://api.binance.com"

# אילו מטבעות ציטוט נחשב “סבירים”
QUOTES_FUTURES: List[str] = ["USDT", "BUSD", "USDC", "FDUSD", "TUSD"]
QUOTES_SPOT:    List[str] = ["USDT", "BUSD", "USDC", "FDUSD", "TUSD"]

# פולבק במידה ואין חיבור / Binance לא זמין
DEFAULT_FUTURES: Set[str] = {
    "BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT","ADAUSDT","DOGEUSDT",
    "AVAXUSDT","MATICUSDT","LINKUSDT","TRXUSDT","SHIBUSDT","DOTUSDT",
}
DEFAULT_SPOT: Set[str] = set(DEFAULT_FUTURES)

_CLEAN_PAIR = re.compile(r"[^A-Z0-9]+")

def _upper(s: str) -> str:
    return (s or "").strip().upper()

def _normalize_raw(s: str) -> str:
    """
    מסיר רווחים ומפרידים נפוצים, הופך ל-UPPER.
    תומך: 'avax', 'avax/usdt', 'avax-usdt', 'AVAX_USDT', ' AVAX usdt '
    """
    s = _upper(s)
    # תצורות כמו BASE/QUOTE
    if "/" in s or "-" in s or "_" in s or " " in s:
        parts = re.split(r"[\/\-\_\s]+", s)
        parts = [p for p in parts if p]
        if len(parts) >= 2:
            return "".join(parts[:2])  # BASE + QUOTE
    # “PERP”, “THIS-PERP” וכד' → מתעלמים מהסיומת
    s = s.replace("PERP", "")
    return _CLEAN_PAIR.sub("", s)

class SymbolsCache:
    """
    קאש פשוט לרשימת סימבולים תקפים מהבורסה.
    refresh() סינכרוני – נוח לשימוש גם מתוך פונקציות async שלא await-ות כאן.
    """
    def __init__(self, market: str = "futures", ttl: int = 1800) -> None:
        self.market = "spot" if str(market).lower() == "spot" else "futures"
        self.ttl = int(ttl)
        self._last: float = 0.0
        self._symbols: Set[str] = set(DEFAULT_SPOT if self.market == "spot" else DEFAULT_FUTURES)
        self._bases: Set[str] = set()  # אוסף baseAsset לתיחום חכם

    def _endpoint(self) -> str:
        return f"{BINANCE_SPOT}/api/v3/exchangeInfo" if self.market == "spot" else f"{BINANCE_FAPI}/fapi/v1/exchangeInfo"

    def _quotes(self) -> List[str]:
        return QUOTES_SPOT if self.market == "spot" else QUOTES_FUTURES

    def refresh(self) -> None:
        now = time.time()
        if self._symbols and (now - self._last) < self.ttl:
            return
        try:
            with httpx.Client(timeout=8.0) as x:
                r = x.get(self._endpoint())
                r.raise_for_status()
                data = r.json()
            symbols = data.get("symbols", [])
            syms: Set[str] = set()
            bases: Set[str] = set()
            for s in symbols:
                sym = _upper(s.get("symbol", ""))
                status = _upper(s.get("status", ""))
                base = _upper(s.get("baseAsset", ""))
                if not sym:
                    continue
                # ב־Futures יש גם מצבים כמו PENDING_TRADING; נרשה מצב TRADING בלבד
                if status and status not in {"TRADING", "PENDING_TRADING"}:
                    # ב־SPOT לרוב רק TRADING
                    # עדיין נשמור TRADING; PENDING_TRADING נכלול רק אם אין מספיק כיסוי
                    pass
                syms.add(sym)
                if base:
                    bases.add(base)
            if syms:
                self._symbols = syms
            if bases:
                self._bases = bases
            self._last = now
        except Exception:
            # נשאר עם ברירת המחדל; אין צורך להפיל
            self._last = now  # נסה שוב רק אחרי ttl

    def normalize(self, raw: str) -> str:
        """
        מחזיר סימבול מלא תקף לביננס (לדוגמה: BTC → BTCUSDT, avax/usdt → AVAXUSDT).
        תמיד מחזיר UPPERCASE. נצמד למרקט של הקאש.
        """
        self.refresh()
        s = _normalize_raw(raw)
        if not s:
            raise ValueError("empty symbol")

        # אם כבר סימבול מלא שקיים – החזר
        if s in self._symbols:
            return s

        # אם נמסר כ־BASE+QUOTE בפועל, אבל לא קיים – ננסה וריאציות ציטוט
        quotes = self._quotes()

        # 1) אם מסתיים ב־QUOTE ידוע → בדיקה ישירה (אולי חסר ב־cache)
        for q in quotes:
            if s.endswith(q) and s in self._symbols:
                return s

        # 2) אם נמסר כ־"BASEQUOTE" (כבר מנוּרמל), ננסה לשבור לבסיס
        #    base = כל מה שלא מסתיים באחד ה־quotes
        base = s
        for q in quotes:
            if s.endswith(q):
                base = s[: -len(q)]
                break

        # 3) pair style שהיה עם מפריד (טפלנו ב־_normalize_raw), אך ליתר ביטחון – לא צריך כאן

        # 4) ניחוש חכם: נסה BASE + quote מועדף (USDT תחילה), אח"כ השאר
        preferred = ["USDT"] + [q for q in quotes if q != "USDT"]
        for q in preferred:
            cand = f"{base}{q}"
            if cand in self._symbols:
                return cand

        # 5) אם הבסיס קיים ב־exchange (bases) – החזר BASEUSDT (גם אם לא נכלל ב־symbols)
        if base in self._bases:
            return f"{base}USDT"

        # 6) פולבק סופי: BASEUSDT
        return f"{base}USDT"

def normalize_symbol(symbol: str, market: str = "futures", cache: Optional[SymbolsCache] = None) -> str:
    """
    עטיפה נוחה לשימוש חיצוני. סינכרוני (לא צריך await).
    """
    if cache is None or cache.market != ("spot" if str(market).lower() == "spot" else "futures"):
        cache = SymbolsCache(market=market)
    return cache.normalize(symbol)


