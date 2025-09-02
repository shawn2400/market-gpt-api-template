# utils/symbol_scheduler.py
from __future__ import annotations
import os, time, random
from typing import List, Dict

from utils import config as cfg

SCAN_MAX_LIMIT = int(os.getenv("SCAN_MAX_LIMIT", "10"))
SYMBOL_COOLDOWN_SEC = int(os.getenv("SYMBOL_COOLDOWN_SEC", "600"))
TOP_SYMBOLS = int(os.getenv("TOP_SYMBOLS","30"))

class SymbolScheduler:
    """
    סורק רשימת סימבולים בסבבים, עם cooldown פר-סימבול,
    וחיתוך לגודל סביר לכל טיק כדי להימנע מ-Timeout.
    """
    def __init__(self, watchlist: List[str]):
        self.all = [s.upper() for s in watchlist][:max(1, TOP_SYMBOLS)]
        # הכנס BTCUSDT קדימה
        if "BTCUSDT" in self.all:
            self.all.remove("BTCUSDT")
        self.all.insert(0, "BTCUSDT")
        self.i = 0
        self.last_touch: Dict[str, float] = {}

    def next_batch(self, max_n: int | None = None) -> List[str]:
        size = max_n or SCAN_MAX_LIMIT
        out = []
        seen = 0
        n = len(self.all)
        now = time.time()
        # עובר בסבב ומדלג על סימבולים בקול-דאון
        while seen < n and len(out) < size:
            sym = self.all[self.i]
            self.i = (self.i + 1) % n
            seen += 1
            last = self.last_touch.get(sym, 0.0)
            if now - last < SYMBOL_COOLDOWN_SEC:
                continue
            out.append(sym)
        # עדכון זמן נגיעה — כך שלא נסרוק את אותו סימבול מייד שוב
        t = time.time()
        for s in out:
            self.last_touch[s] = t
        # ג'יטר אקראי קטן לסדר
        random.shuffle(out)
        return out

