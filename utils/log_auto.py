# utils/log_auto.py
from __future__ import annotations
import os, time, logging
from typing import Deque, Tuple
from collections import deque

class _LogAuto:
    """
    בקר לוג אוטומטי רזה:
    - אוסף סטאטוס/משך אחרונים (ברירת מחדל: חלון של 200 בקשות).
    - אם יש הרבה כשלים או שיהוי גבוה → מרים זמנית DEBUG, אח"כ חוזר ל-LOG_LEVEL המקורי.
    - בלי ENV חובה; מכבד אם קיימים:
        AUTO_TUNE_LATENCY_P95_MS (דיפולט 800ms)
        LOG_AUTO_WINDOW (כמות דגימות לחלון, דיפולט 200)
        LOG_AUTO_DEBUG_WINDOW_SEC (זמן הדיבאג, דיפולט 60s)
        LOG_AUTO_ERR_RATE (סף כשלים, דיפולט 0.15)
    """
    def __init__(self) -> None:
        self.base_level = logging.getLogger().level
        self.latency_p95_ms = float(os.getenv("AUTO_TUNE_LATENCY_P95_MS", "800"))
        self.window_n = int(os.getenv("LOG_AUTO_WINDOW", "200"))
        self.debug_for_sec = int(os.getenv("LOG_AUTO_DEBUG_WINDOW_SEC", "60"))
        self.err_rate_thr = float(os.getenv("LOG_AUTO_ERR_RATE", "0.15"))
        self.samples: Deque[Tuple[int, float]] = deque(maxlen=max(50, self.window_n))
        self.debug_until = 0.0

    def _maybe_reset_level(self) -> None:
        if self.debug_until and time.time() > self.debug_until:
            logging.getLogger().setLevel(self.base_level)
            self.debug_until = 0.0

    def _percentile(self, arr, p: float) -> float:
        if not arr: return 0.0
        a = sorted(arr)
        idx = int(max(0, min(len(a) - 1, round(p * (len(a) - 1)))))
        return a[idx]

    def observe(self, status_code: int, dur_ms: float) -> None:
        try:
            self.samples.append((status_code, float(dur_ms)))
            now = time.time()
            self._maybe_reset_level()

            # אל תבדוק כל בקשה – רק כל ~20 דגימות
            if len(self.samples) < min(60, self.window_n // 3):
                return
            if len(self.samples) % 20 != 0:
                return

            # חשב מדדים בסיסיים
            latencies = [d for _, d in self.samples]
            p95 = self._percentile(latencies, 0.95)
            errs = sum(1 for s, _ in self.samples if int(s) >= 500)
            err_rate = errs / max(1, len(self.samples))

            # טריגר דיבאג זמני
            if p95 > self.latency_p95_ms or err_rate >= self.err_rate_thr:
                logging.getLogger().setLevel(logging.DEBUG)
                self.debug_until = now + self.debug_for_sec
        except Exception:
            # לא שוברים כלום בגלל בקר לוגים
            pass

log_auto = _LogAuto()

