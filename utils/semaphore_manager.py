# utils/semaphore_manager.py
from __future__ import annotations

import os
import asyncio
from typing import Callable, Awaitable, TypeVar, Optional
from functools import wraps

_T = TypeVar("_T")

# ברירת מחדל: 5 בקשות מקבילות; ניתן לעקוף ב-ENV
_MAX = int(os.getenv("GLOBAL_MAX_CONCURRENCY", os.getenv("OPENAI_MAX_CONCURRENCY", "5")))
semaphore = asyncio.Semaphore(max(1, _MAX))


def set_max_concurrency(n: int) -> None:
    """עדכון דינמי של גודל הסמפור (יוצר חדש)."""
    global semaphore
    n = max(1, int(n))
    semaphore = asyncio.Semaphore(n)


class limit:
    """קונטקסט־מנג'ר לשימוש נקודתי:
    async with limit(): ...  # משתמש בסמפור הגלובלי
    או:
    async with limit(3): ...  # מגביל זמנית במשימה זו
    """
    def __init__(self, n: Optional[int] = None) -> None:
        self._sem = asyncio.Semaphore(max(1, int(n))) if n else semaphore

    async def __aenter__(self):
        await self._sem.acquire()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self._sem.release()


def with_semaphore(fn: Callable[..., Awaitable[_T]]) -> Callable[..., Awaitable[_T]]:
    """דקורטור שמוודא שימוש בסמפור הגלובלי עבור כל קריאה async."""
    @wraps(fn)
    async def _wrap(*args, **kwargs) -> _T:
        async with limit():
            return await fn(*args, **kwargs)
    return _wrap
