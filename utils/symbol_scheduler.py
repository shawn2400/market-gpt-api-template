# utils/symbol_scheduler.py
from __future__ import annotations
import os, time, random, json, logging
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger("algogpt.sym_sched")

# ----- Safe quarantine (fallbacks if module missing) -----
try:
    from utils.safe import is_quarantined, mark_quarantine
except Exception:
    def is_quarantined(symbol: str) -> bool:  # type: ignore
        return False
    def mark_quarantine(symbol: str, until_sec: int = 300) -> None:  # type: ignore
        logger.debug({"event": "quarantine_stub", "symbol": symbol, "until": until_sec})

# ----- ENV -----
SCAN_MAX_LIMIT         = int(os.getenv("SCAN_MAX_LIMIT", "10"))
SYMBOL_COOLDOWN_SEC    = int(os.getenv("SYMBOL_COOLDOWN_SEC", "600"))
TOP_SYMBOLS            = int(os.getenv("TOP_SYMBOLS", "30"))
WEIGHTS_JSON           = os.getenv("SYMBOL_WEIGHTS_JSON", "").strip()  # {"BTCUSDT": 2.0, "ETHUSDT": 1.5}
COOLDOWN_ON_ERROR_SEC  = int(os.getenv("SYMBOL_ERROR_COOLDOWN_SEC", "180"))
ERROR_QUARANTINE_HIT   = int(os.getenv("SYMBOL_ERROR_QUARANTINE_HIT", "3"))

def _parse_weights(raw: str) -> Dict[str, float]:
    if not raw:
        return {}
    try:
        obj = json.loads(raw)
        out: Dict[str, float] = {}
        for k, v in obj.items():
            try:
                out[str(k).upper()] = float(v)
            except Exception:
                continue
        return out
    except Exception:
        return {}

class SymbolScheduler:
    """
    סורק רשימת סימבולים בסבבים, כולל:
      • Cooldown פר-סימבול
      • Priorities/Weights (אופציונלי דרך ENV)
      • Throttle דינמי
      • Quarantine אחרי רצף שגיאות
      • החזרה תמידית של BTCUSDT בראש (אם קיים)
    """
    def __init__(self, watchlist: List[str], batch_size: Optional[int] = None):
        base = [s.upper() for s in watchlist if s]
        base = base[:max(1, TOP_SYMBOLS)]
        # ודא ש-BTCUSDT ראשון אם קיים
        if "BTCUSDT" in base:
            base.remove("BTCUSDT")
        base.insert(0, "BTCUSDT")
        self.syms: List[str] = list(dict.fromkeys(base))
        self.i: int = 0
        self.bs: int = int(batch_size) if batch_size is not None else int(SCAN_MAX_LIMIT)
        self.bs = max(1, self.bs)
        self.last_touch: Dict[str, float] = {}
        self.errors: Dict[str, int] = {}
        self.err_cooldown_until: Dict[str, float] = {}
        self.weights: Dict[str, float] = _parse_weights(WEIGHTS_JSON)

    # ----- API -----
    def set_batch_size(self, n: int) -> None:
        self.bs = max(1, int(n))

    def update_watchlist(self, wl: List[str]) -> None:
        new = [s.upper() for s in wl if s]
        if "BTCUSDT" in new:
            new.remove("BTCUSDT")
        new.insert(0, "BTCUSDT")
        self.syms = list(dict.fromkeys(new))
        self.i = 0

    def set_weights(self, w: Dict[str, float]) -> None:
        self.weights = {str(k).upper(): float(v) for k, v in w.items() if v is not None}

    def bump_weight(self, symbol: str, by: float = 0.25) -> None:
        s = symbol.upper()
        self.weights[s] = max(0.0, float(self.weights.get(s, 1.0)) + float(by))

    def decay_weights(self, factor: float = 0.98) -> None:
        self.weights = {k: max(0.0, v * factor) for k, v in self.weights.items()}

    def report_error(self, symbol: str) -> None:
        s = symbol.upper()
        self.errors[s] = self.errors.get(s, 0) + 1
        self.err_cooldown_until[s] = time.time() + COOLDOWN_ON_ERROR_SEC
        if self.errors[s] >= max(1, ERROR_QUARANTINE_HIT):
            try:
                mark_quarantine(s, until_sec=COOLDOWN_ON_ERROR_SEC * 3)
            except Exception:
                pass
            self.errors[s] = 0

    # ----- Internals -----
    def _eligible(self, sym: str, now: float) -> bool:
        if is_quarantined(sym):
            return False
        if now < self.err_cooldown_until.get(sym, 0.0):
            return False
        last = self.last_touch.get(sym, 0.0)
        if (now - last) < SYMBOL_COOLDOWN_SEC:
            return False
        return True

    def _weighted_slice(self, cands: List[str]) -> List[Tuple[str, float]]:
        out: List[Tuple[str, float]] = []
        for s in cands:
            w = float(self.weights.get(s, 1.0))
            out.append((s, w))
        # משקל גבוה = קדימות גבוהה
        out.sort(key=lambda t: t[1], reverse=True)
        return out

    # ----- Batch selection -----
    def next_batch(self, max_n: Optional[int] = None) -> List[str]:
        size = max(1, int(max_n or self.bs))
        if not self.syms:
            return []

        now = time.time()
        n = len(self.syms)
        seen = 0
        candidates: List[str] = []

        # מעבר סבבי: אוסף מועמדים שזכאים לפי cooldown/quarantine
        while seen < n and len(candidates) < size * 2:  # קח קצת יותר למיון לפי משקל
            sym = self.syms[self.i]
            self.i = (self.i + 1) % n
            seen += 1
            if self._eligible(sym, now):
                candidates.append(sym)

        # אם אין מועמדים (כולם בקירור) — תן לפחות אחד כדי לא לקפוא
        if not candidates:
            # קח את הבא בתור גם אם בקירור (אלא אם הוא בהסגר)
            for _ in range(n):
                sym = self.syms[self.i]
                self.i = (self.i + 1) % n
                if not is_quarantined(sym):
                    candidates = [sym]
                    break

        # מיון לפי משקל ואז ערבוב עדין שימנע "נעילה"
        weighted = self._weighted_slice(candidates)
        picked = [s for s, _ in weighted][:size]
        random.shuffle(picked)

        # עדכן last_touch לכל הסימבולים שנבחרו
        t = time.time()
        for s in picked:
            self.last_touch[s] = t

        return picked



