# -*- coding: utf-8 -*-
from __future__ import annotations
import time
import os
from typing import Dict, Any

_START_TIME = time.time()
_SENT_TELEGRAM = 0
_FAILED_TELEGRAM = 0

# psutil אופציונלי: אם לא זמין, לא נכשלים
try:
    import psutil  # type: ignore
    _HAS_PSUTIL = True
except Exception:
    _HAS_PSUTIL = False


def record_telegram_sent() -> None:
    global _SENT_TELEGRAM
    _SENT_TELEGRAM += 1


def record_telegram_failed() -> None:
    global _FAILED_TELEGRAM
    _FAILED_TELEGRAM += 1


def get_metrics_snapshot() -> Dict[str, Any]:
    """
    מחזיר צילום מצב אינסטנס: גרסה, זמן ריצה, CPU/MEM (אם psutil קיים), וספירת הודעות טלגרם.
    """
    uptime = time.time() - _START_TIME
    if _HAS_PSUTIL:
        try:
            cpu = float(__import__("psutil").cpu_percent(interval=0.1))
            mem = float(__import__("psutil").virtual_memory().percent)
        except Exception:
            cpu, mem = None, None
    else:
        cpu, mem = None, None

    return {
        "version": os.getenv("ALGOGPT_VERSION", "unknown"),
        "uptime_sec": round(uptime, 1),
        "cpu_pct": cpu,
        "mem_pct": mem,
        "telegram_sent": _SENT_TELEGRAM,
        "telegram_failed": _FAILED_TELEGRAM,
    }


__all__ = [
    "record_telegram_sent",
    "record_telegram_failed",
    "get_metrics_snapshot",
]


