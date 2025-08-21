# utils/cache_fallback.py
from __future__ import annotations
import time
import asyncio
from typing import Any, Dict, Tuple

class InMemoryCache:
    def __init__(self):
        self._store: Dict[str, Tuple[float, Any]] = {}
        self._lock = asyncio.Lock()

    async def set(self, key: str, value: Any, ttl: int = 60):
        expire = time.time() + ttl
        async with self._lock:
            self._store[key] = (expire, value)

    async def get(self, key: str) -> Any | None:
        now = time.time()
        async with self._lock:
            hit = self._store.get(key)
            if hit and hit[0] > now:
                return hit[1]
            if hit:
                self._store.pop(key, None)
        return None

    async def lpush(self, key: str, value: Any):
        async with self._lock:
            arr = self._store.get(key, (float("inf"), []))[1]
            if not isinstance(arr, list):
                arr = []
            arr.insert(0, value)
            self._store[key] = (float("inf"), arr)

    async def ltrim(self, key: str, start: int, end: int):
        async with self._lock:
            arr = self._store.get(key, (float("inf"), []))[1]
            if isinstance(arr, list):
                self._store[key] = (float("inf"), arr[start:end+1])

    async def ping(self) -> bool:
        return True  # תמיד זמין

# ✅ singleton
in_memory_cache = InMemoryCache()
