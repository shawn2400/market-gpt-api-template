# server/routes/streams.py
from __future__ import annotations
import asyncio, json, time
from typing import AsyncGenerator
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/api", tags=["SSE"])

async def _event_stream(kind: str) -> AsyncGenerator[bytes, None]:
    # פינג כל 15ש' כדי לשמור חיבור
    while True:
        payload = {"ts": time.time(), "kind": kind, "ping": True}
        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")
        await asyncio.sleep(15)

@router.get("/news/stream")
async def news_stream():
    return StreamingResponse(_event_stream("news"), media_type="text/event-stream")

@router.get("/quotes/stream")
async def quotes_stream():
    return StreamingResponse(_event_stream("quotes"), media_type="text/event-stream")

@router.get("/mailbox/stream")
async def mailbox_stream():
    return StreamingResponse(_event_stream("mailbox"), media_type="text/event-stream")
