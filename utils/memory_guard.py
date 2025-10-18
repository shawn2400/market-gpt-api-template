# utils/memory_guard.py
from __future__ import annotations
import asyncio, logging
from typing import Optional
from utils.telegram_notifier_core import notify_telegram

log = logging.getLogger("algogpt.memguard")

_LOW_MB = 200  # trigger threshold
_RECOVER_MB = 350  # hysteresis

_state_low = False

def _mem_available_kb() -> Optional[int]:
    try:
        with open("/proc/meminfo","r") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    parts = line.split()
                    return int(parts[1])  # kB
    except Exception as e:
        log.debug("meminfo_fail: %s", e)
    return None

async def _apply_throttle(enabled: bool) -> None:
    # כאן תבצע הורדה/החזרה של עומסים – בהתאם למחלקות שלך:
    # דוגמאות (שמור על idempotent):
    import os
    if enabled:
        os.environ["SCAN_CONCURRENCY"] = "1"
        os.environ["SUGGEST_CAP_PER_CYCLE"] = "5"
        os.environ["PUBLIC_WEB_BURST"] = "3"
        # אפשר גם לכבות Features כבדים אם יש flags סביבתיים
    else:
        # החזרה לברירות־מחדל "בטוחות"
        os.environ["SCAN_CONCURRENCY"] = os.environ.get("SCAN_CONCURRENCY_DEFAULT","2")
        os.environ["SUGGEST_CAP_PER_CYCLE"] = os.environ.get("SUGGEST_CAP_PER_CYCLE_DEFAULT","30")
        os.environ["PUBLIC_WEB_BURST"] = os.environ.get("PUBLIC_WEB_BURST_DEFAULT","6")

async def memory_guard_loop(interval_sec: int = 30) -> None:
    global _state_low
    while True:
        try:
            await asyncio.sleep(interval_sec)
            kb = _mem_available_kb()
            if kb is None: 
                continue
            mb = kb // 1024
            if not _state_low and mb < _LOW_MB:
                _state_low = True
                await _apply_throttle(True)
                await notify_telegram(
                    f"⚠️ Low memory guard ON · MemAvailable={mb}MB < {_LOW_MB}MB",
                    level="critical", kind="status", cooldown_sec=60, dedupe_key="mem_guard_on"
                )
            elif _state_low and mb > _RECOVER_MB:
                _state_low = False
                await _apply_throttle(False)
                await notify_telegram(
                    f"✅ Memory recovered · MemAvailable={mb}MB > {_RECOVER_MB}MB · guard OFF",
                    level="critical", kind="status", cooldown_sec=60, dedupe_key="mem_guard_off"
                )
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.debug("memguard_loop_err: %s", e)

async def ensure_memory_guard_started() -> bool:
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(memory_guard_loop())
        return True
    except Exception:
        return False
