# utils/semaphore_manager.py
from __future__ import annotations
import os, asyncio
_semaphores: dict[str, asyncio.Semaphore] = {}

def get_semaphore(name: str = "scan", default_concurrency: int = 8) -> asyncio.Semaphore:
    if name not in _semaphores:
        conc = int(os.getenv("SCAN_CONCURRENCY", default_concurrency))
        _semaphores[name] = asyncio.Semaphore(conc if conc > 0 else 1)
    return _semaphores[name]

