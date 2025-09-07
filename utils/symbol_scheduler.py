# utils/symbol_scheduler.py
from __future__ import annotations
import os, time, random
from typing import List, Dict
from utils.safe import is_quarantined

SCAN_MAX_LIMIT = int(os.getenv("SCAN_MAX_LIMIT", "10"))
SYMBOL_COOLDOWN_SEC = int(os.getenv("SYMBOL_COOLDOWN_SEC", "600"))
TOP_SYMBOLS = int(os.getenv("TOP_SYMBOLS","30"))

class SymbolScheduler:
    """
    סורק רשימת סימבולים בסבבים, עם cooldown פר-סימבול,
    throttle דינמי והסגר (quarantine).
    """
    def __init__(self, watchlist: List[str]):
        self.all = [s.upper() for s in watchlist][:max(1, TOP_SYMBOLS)]
        if "BTCUSDT" in self.all:
            self.all.remove("BTCUSDT")
        self.all.insert(0, "BTCUSDT")
        self.i = 0
        self.last_touch: Dict[str, float] = {}
        self.errors: Dict[str,int] = {}

    def next_batch(self, max_n: int | None = None) -> List[str]:
        size = max_n or SCAN_MAX_LIMIT
        out, seen, n, now = [], 0, len(self.all), time.time()
        while seen < n and len(out) < size:
            sym = self.all[self.i]; self.i=(self.i+1)%n; seen+=1
            if is_quarantined(sym): continue
            last = self.last_touch.get(sym, 0.0)
            if now-last < SYMBOL_COOLDOWN_SEC: continue
            out.append(sym)
        t = time.time()
        for s in out: self.last_touch[s] = t
        random.shuffle(out)
        return out

    def report_error(self, symbol: str) -> None:
        s=symbol.upper(); self.errors[s]=self.errors.get(s,0)+1
        if self.errors[s] >= 3:  # אחרי 3 טעויות → הסגר זמני
            from utils.safe import mark_quarantine
            mark_quarantine(s); self.errors[s]=0


