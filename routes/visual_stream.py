# routes/visual_stream.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import os, json, asyncio, time
from typing import Any, Dict, Optional, AsyncGenerator
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse, StreamingResponse

router = APIRouter(prefix="/visual", tags=["Visual Stream"])

REDIS_URL = os.getenv("REDIS_URL", "")
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

async def _load_pos(redis, symbol: str) -> Dict[str, Any]:
    if not redis:
        return {}
    try:
        key = f"pos:{symbol.upper()}"
        raw = await redis.get(key)
        return json.loads(raw) if raw else {}
    except Exception:
        return {}

@router.get("/state")
async def visual_state(symbol: str = Query(..., min_length=3)):
    r = await _get_redis()
    data = await _load_pos(r, symbol)
    return JSONResponse({"ok": True, "symbol": symbol.upper(), "data": data, "ts": int(time.time())})

async def _sse_symbol(symbol: str) -> AsyncGenerator[bytes, None]:
    r = await _get_redis()
    last_beat = time.time()
    symbol = symbol.upper()
    while True:
        try:
            data = await _load_pos(r, symbol)
            if data:
                payload = {"symbol": symbol, "data": data, "ts": int(time.time())}
                yield f"event: visual\ndata: {json.dumps(payload)}\n\n".encode("utf-8")
            if time.time() - last_beat >= 20:
                last_beat = time.time()
                yield b": hb\n\n"
            await asyncio.sleep(2.0)
        except asyncio.CancelledError:
            break
        except Exception:
            await asyncio.sleep(3.0)

@router.get("/stream")
async def visual_stream(symbol: str = Query(..., min_length=3)):
    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "Content-Type": "text/event-stream",
    }
    return StreamingResponse(_sse_symbol(symbol), headers=headers, media_type="text/event-stream")
