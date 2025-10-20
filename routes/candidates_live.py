# routes/candidates_live.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import os, json, asyncio, time
from typing import Any, Dict, List, Optional, AsyncGenerator
from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse

router = APIRouter(prefix="/scan", tags=["Public Feed"])

REDIS_URL = os.getenv("REDIS_URL", "")
PUBLIC_SSE_HEARTBEAT_SEC = int(os.getenv("PUBLIC_SSE_HEARTBEAT_SEC", "20"))
PUBLIC_SSE_MAX_IDLE_SEC = int(os.getenv("PUBLIC_SSE_MAX_IDLE_SEC", "300"))

_aioredis = None
try:
    import aioredis  # type: ignore
    _aioredis = aioredis
except Exception:
    pass

async def _get_redis():
    if not _aioredis or not REDIS_URL:
        return None
    return await _aioredis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)

async def _load_list(redis, key: str) -> List[Dict[str, Any]]:
    if not redis:
        return []
    try:
        raw = await redis.get(key)
        if not raw:
            return []
        data = json.loads(raw)
        if isinstance(data, dict) and "items" in data:
            return list(data.get("items") or [])
        if isinstance(data, list):
            return data
        return []
    except Exception:
        return []

@router.get("/public-topk")
async def public_topk():
    r = await _get_redis()
    items = await _load_list(r, "scan:topk")
    return JSONResponse({"ok": True, "items": items, "ts": int(time.time())})

@router.get("/public-now")
async def public_now():
    r = await _get_redis()
    items = await _load_list(r, "scan:now")
    return JSONResponse({"ok": True, "items": items, "ts": int(time.time())})

async def _sse_stream() -> AsyncGenerator[bytes, None]:
    last_beat = time.time()
    r = await _get_redis()
    while True:
        try:
            # load snapshots
            topk = await _load_list(r, "scan:topk")
            now_ = await _load_list(r, "scan:now")

            if topk:
                yield f"event: topk\ndata: {json.dumps({'items': topk, 'ts': int(time.time())})}\n\n".encode("utf-8")
            if now_:
                yield f"event: now\ndata: {json.dumps({'items': now_, 'ts': int(time.time())})}\n\n".encode("utf-8")

            # heartbeat
            if time.time() - last_beat >= max(3, PUBLIC_SSE_HEARTBEAT_SEC):
                last_beat = time.time()
                yield b": hb\n\n"

            await asyncio.sleep(2.5)
        except asyncio.CancelledError:
            break
        except Exception:
            # שמור את הזרם חי גם בשגיאה רגעית
            await asyncio.sleep(3.0)

@router.get("/public-stream")
async def public_stream():
    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "Content-Type": "text/event-stream",
    }
    return StreamingResponse(_sse_stream(), headers=headers, media_type="text/event-stream")
