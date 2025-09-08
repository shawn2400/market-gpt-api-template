# utils/metrics_tracker.py
import time, psutil, os
from typing import Dict, Any

_start_time = time.time()
_sent_telegram = 0
_failed_telegram = 0

def record_telegram_sent():
    global _sent_telegram
    _sent_telegram += 1

def record_telegram_failed():
    global _failed_telegram
    _failed_telegram += 1

def get_metrics_snapshot() -> Dict[str, Any]:
    uptime = time.time() - _start_time
    cpu = psutil.cpu_percent(interval=0.1)
    mem = psutil.virtual_memory().percent
    return {
        "version": os.getenv("ALGOGPT_VERSION", "unknown"),
        "uptime_sec": round(uptime, 1),
        "cpu_pct": cpu,
        "mem_pct": mem,
        "telegram_sent": _sent_telegram,
        "telegram_failed": _failed_telegram,
    }

