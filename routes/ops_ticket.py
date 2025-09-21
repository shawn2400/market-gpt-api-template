# routes/ops_ticket.py
from __future__ import annotations
import os
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

try:
    import redis.asyncio as aioredis
except Exception:
    aioredis = None

router = APIRouter(prefix="/ops", tags=["Ops"])

REDIS_URL  = os.getenv("REDIS_URL", "")
NS         = os.getenv("REDIS_NAMESPACE", "ops-supervisor-web").strip() or "ops-supervisor-web"
KEY_TICKET = lambda tid: f"{NS}:ticket:{tid}"

async def _redis():
    if not aioredis:
        raise RuntimeError("redis.asyncio not available")
    if not REDIS_URL:
        raise RuntimeError("REDIS_URL not set")
    return await aioredis.from_url(REDIS_URL, decode_responses=True)

@router.get("/ticket/{ticket_id}", summary="Get ticket status")
async def ticket_status(ticket_id: str):
    r = await _redis()
    data = await r.hgetall(KEY_TICKET(ticket_id))
    if not data:
        raise HTTPException(status_code=404, detail="Ticket not found")
    # סינון אפשרי של שדות רגישים
    safe = {k: v for k, v in data.items() if k not in ("secret", "token", "payload")}
    return JSONResponse({"ok": True, "ticket": safe})
