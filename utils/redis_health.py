# utils/redis_health.py
from __future__ import annotations
import os, asyncio

async def check_redis_ready(timeout: float = 0.5) -> dict:
    url = os.getenv("REDIS_URL", "").strip()
    if not url:
        return {"ok": True, "skipped": True, "reason": "no_redis_url"}
    try:
        import redis.asyncio as aioredis  # type: ignore
        r = aioredis.from_url(url, decode_responses=True, socket_timeout=timeout)
        pong = await asyncio.wait_for(r.ping(), timeout=timeout)
        return {"ok": bool(pong), "skipped": False}
    except Exception as e:
        return {"ok": False, "skipped": False, "error": str(e)}
