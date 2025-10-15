# utils/async_backoff.py
import asyncio, random, time
from typing import Callable, Any, Optional, Tuple

class RetryError(Exception):
    pass

async def call_with_backoff(
    fn: Callable[..., Any],
    *args,
    retries: int = 3,
    base_ms: int = 400,
    max_ms: int = 2000,
    jitter: Tuple[float, float] = (0.25, 0.75),
    as_thread: bool = True,
    **kwargs
):
    """
    מריץ fn סינכרוני (או אסינכרוני) עם backoff וג'יטר.
    ברירת מחדל: להריץ ב-thread כדי לא לחסום event loop.
    """
    attempt = 0
    while True:
        try:
            if as_thread:
                return await asyncio.to_thread(fn, *args, **kwargs)
            res = fn(*args, **kwargs)
            if asyncio.iscoroutine(res):
                return await res
            return res
        except Exception as e:
            attempt += 1
            if attempt > retries:
                raise RetryError(f"exhausted after {retries} retries; last={e}") from e
            sleep_ms = min(max_ms, base_ms * (2 ** (attempt - 1)))
            sleep_ms = int(sleep_ms * random.uniform(*jitter))
            await asyncio.sleep(sleep_ms / 1000.0)
