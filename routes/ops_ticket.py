# routes/ops_ticket.py
from __future__ import annotations
import os, json
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

# Redis (async)
try:
    import redis.asyncio as aioredis
except Exception:
    aioredis = None

router = APIRouter(prefix="/ops", tags=["Ops"])

REDIS_URL = os.getenv("REDIS_URL", "")
NS        = os.getenv("REDIS_NAMESPACE", "ops-supervisor-web").strip() or "ops-supervisor-web"
KEY_TICKET = lambda tid: f"{NS}:ticket:{tid}"

async def _redis():
    if not aioredis:
        raise RuntimeError("redis.asyncio not available")
    if not REDIS_URL:
        raise RuntimeError("REDIS_URL not set")
    return await aioredis.from_url(REDIS_URL, decode_responses=True)

@router.get("/ticket/{ticket_id}", summary="Get ticket status (as stored by supervisor)")
async def ticket_status(ticket_id: str):
    r = await _redis()

    # הסופרוויזור שומר JSON באמצעות SETEX
    raw = await r.get(KEY_TICKET(ticket_id))
    if raw:
        try:
            data = json.loads(raw)
        except Exception:
            data = {"raw": raw}
        return JSONResponse({"ok": True, "ticket": data})

    # פולי-בק אם בעתיד יישמר כ-Hash
    h = await r.hgetall(KEY_TICKET(ticket_id))
    if h:
        return JSONResponse({"ok": True, "ticket": h})

    raise HTTPException(status_code=404, detail="Ticket not found")

