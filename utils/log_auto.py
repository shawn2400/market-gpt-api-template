# utils/log_auto.py
from __future__ import annotations
import os, time, logging
from collections import deque
from typing import Deque, Tuple

class LogAutoTuner:
    """
    מרים DEBUG לבאסט קצר כשיש ספייק שגיאות/לטנסי/CPU, ואז חוזר ל-INFO.
    נשלט ע"י ENV, לא חוסם ולא מכביד.
    """
    def __init__(self) -> None:
        self.enable = str(os.getenv("LOG_AUTO_TUNE", "0")).lower() in ("1","true","yes","on")
        self.debug_burst_sec = int(os.getenv("LOG_DEBUG_BURST_SEC", "180"))
        self.win_sec = int(os.getenv("LOG_ERROR_RATE_WINDOW_SEC", "60"))
        self.err_spike = int(os.getenv("LOG_ERROR_RATE_SPIKE", "8"))
        self.latency_p95_ms = int(os.getenv("LOG_LATENCY_P95_MS", os.getenv("AUTO_TUNE_LATENCY_P95_MS","800")))
        self.cpu_spike = int(os.getenv("LOG_CPU_SPIKE", "85"))  # אופציונלי: אם תזין שימוש CPU
        self._root = logging.getLogger()
        self._was_forced = False
        self._debug_until = 0.0
        self._q: Deque[Tuple[float,int,float]] = deque(maxlen=500)  # (ts, status, dur_ms)

    def observe(self, status: int, dur_ms: float) -> None:
        if not self.enable: 
            return
        now = time.time()
        self._q.append((now, status, dur_ms))
        # נקה חלון
        while self._q and now - self._q[0][0] > self.win_sec:
            self._q.popleft()
        errors = sum(1 for _, s, _ in self._q if s >= 500)
        # p95 גס (ללא numpy)
        ms_sorted = sorted(x[2] for x in self._q)
        p95 = ms_sorted[int(0.95*len(ms_sorted))-1] if ms_sorted else 0.0

        trigger = (errors >= self.err_spike) or (p95 >= self.latency_p95_ms)
        if trigger:
            self._set_debug_burst(now + self.debug_burst_sec)
        elif self._was_forced and now >= self._debug_until:
            self._set_info()

    def _set_debug_burst(self, until_ts: float) -> None:
        if not self._was_forced:
            self._prev_level = self._root.level
        self._root.setLevel(logging.DEBUG)
        self._was_forced = True
        self._debug_until = until_ts

    def _set_info(self) -> None:
        lvl = os.getenv("LOG_LEVEL","info").lower()
        new = logging.INFO if lvl=="info" else logging.getLevelName(lvl.upper())
        self._root.setLevel(new)
        self._was_forced = False
        self._debug_until = 0.0

# מחזיק יחיד גלובלי
log_auto = LogAutoTuner()
