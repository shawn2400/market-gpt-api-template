# routes/aliases.py
from __future__ import annotations
import os, json, time, logging, asyncio
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Body, Query

logger = logging.getLogger("algogpt.aliases")
router = APIRouter()

NS = os.getenv("REDIS_NAMESPACE", "ops-supervisor-web").strip() or "ops-supervisor-web"
REDIS_URL = (os.getenv("REDIS_URL") or "").strip()

# In-memory fallback store
_mem: Dict[str, str] = {}

_aioredis = None
try:
    import redis.asyncio as _aioredis  # type: ignore
except Exception:
    _aioredis = None

_redis_client = None
_client_lock = asyncio.Lock()

async def _get_redis():
    global _redis_client
    if not (_aioredis and REDIS_URL):
        return None
    if _redis_client:
        return _redis_client
    async with _client_lock:
        if _redis_client:
            return _redis_client
        try:
            _redis_client = _aioredis.from_url(REDIS_URL, decode_responses=True)
        except Exception as e:
            logger.warning("aliases: redis connect failed: %s", e)
            _redis_client = None
    return _redis_client

def _key(alias: str) -> str:
    return f"{NS}:aliases:{alias}"

async def _read(alias: str) -> Optional[str]:
    # 1) memory
    if alias in _mem:
        return _mem[alias]
    # 2) redis (optional)
    r = await _get_redis()
    if r:
        try:
            v = await r.get(_key(alias))
            if v:
                _mem[alias] = v
                return v
        except Exception as e:
            logger.debug("aliases: redis get fail: %s", e)
    return None

async def _write(alias: str, target: str) -> None:
    _mem[alias] = target
    r = await _get_redis()
    if r:
        try:
            await r.set(_key(alias), target)
        except Exception as e:
            logger.debug("aliases: redis set fail: %s", e)

async def _delete(alias: str) -> None:
    _mem.pop(alias, None)
    r = await _get_redis()
    if r:
        try:
            await r.delete(_key(alias))
        except Exception as e:
            logger.debug("aliases: redis del fail: %s", e)

@router.get("/aliases/resolve")
async def aliases_resolve(alias: str = Query(..., min_length=1, max_length=120)):
    target = await _read(alias.strip())
    if not target:
        raise HTTPException(status_code=404, detail="alias_not_found")
    return {"ok": True, "alias": alias, "target": target}

@router.post("/aliases/set")
async def aliases_set(payload: Dict[str, Any] = Body(...)):
    alias = str(payload.get("alias") or "").strip()
    target = str(payload.get("target") or "").strip()
    if not alias or not target:
        raise HTTPException(status_code=422, detail="alias/target required")
    await _write(alias, target)
    return {"ok": True, "alias": alias, "target": target, "ts": int(time.time())}

@router.delete("/aliases/delete")
async def aliases_delete(alias: str = Query(..., min_length=1, max_length=120)):
    await _delete(alias.strip())
    return {"ok": True, "alias": alias}

