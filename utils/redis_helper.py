# utils/redis_helper.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import os, json, asyncio
from typing import Any, Optional

_aioredis = None
try:
    import aioredis  # type: ignore
    _aioredis = aioredis
except Exception:
    pass

REDIS_URL = os.getenv("REDIS_URL", "")

async def get_redis():
    if not _aioredis or not REDIS_URL:
        return None
    return await _aioredis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)

async def set_json(key: str, value: Any, *, ttl_sec: Optional[int] = None) -> bool:
    r = await get_redis()
    if not r:
        return False
    data = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if ttl_sec and ttl_sec > 0:
        await r.set(key, data, ex=int(ttl_sec))
    else:
        await r.set(key, data)
    return True

async def get_json(key: str) -> Any:
    r = await get_redis()
    if not r:
        return None
    raw = await r.get(key)
    return json.loads(raw) if raw else None


