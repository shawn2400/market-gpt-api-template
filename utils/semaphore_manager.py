# utils/semaphore_manager.py
from __future__ import annotations
import os, asyncio

_semaphores: dict[str, asyncio.Semaphore] = {}

def get_semaphore(name: str = "scan", default_concurrency: int = 8) -> asyncio.Semaphore:
    """מנהל Semaphore גלובלי לפי שם, עם ברירת מחדל ל־SCAN_CONCURRENCY."""
    if name not in _semaphores:
        conc = int(os.getenv("SCAN_CONCURRENCY", default_concurrency))
        if conc <= 0:
            conc = 1
        _semaphores[name] = asyncio.Semaphore(conc)
    return _semaphores[name]

