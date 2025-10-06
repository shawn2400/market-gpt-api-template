# jobs/smoke_guard_job.py
from __future__ import annotations
import os, asyncio, logging
from typing import Optional
from utils.smoke_checks import run_smoke_guard

log = logging.getLogger("smoke-guard")

SMOKE_GUARD_ENABLE = (os.getenv("SMOKE_GUARD_ENABLE","1").lower() in ("1","true","yes","on"))
INTERVAL_SEC = int(os.getenv("SMOKE_GUARD_INTERVAL_SEC","900") or 900)

_task: Optional[asyncio.Task] = None
_stop = asyncio.Event()

async def _loop():
    if not SMOKE_GUARD_ENABLE:
        log.info("Smoke-Guard disabled by env")
        return
    log.info(f"Smoke-Guard started. interval={INTERVAL_SEC}s")
    while not _stop.is_set():
        try:
            res = run_smoke_guard(send_report=True)
            if not res.get("ok", True):
                log.warning(f"Smoke-Guard detected errors: {res.get('errors')}")
            else:
                log.info("Smoke-Guard tick done")
        except Exception as e:
            log.exception(f"Smoke-Guard tick failed: {e}")
        await asyncio.wait([_stop.wait()], timeout=INTERVAL_SEC)

def start():
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop())

def stop():
    _stop.set()
