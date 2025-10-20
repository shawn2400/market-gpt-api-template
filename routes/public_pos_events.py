# routes/public_pos_events.py
from __future__ import annotations
import asyncio, json, time, typing as t
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse

from utils.redis_helper import get_redis

router = APIRouter(tags=["Public Feed"])

CHANNEL = "pos:events:chan"
HEARTBEAT_SEC = int(20)
IDLE_TIMEOUT_SEC = int(300)  # מיושר ל-render.yaml: PUBLIC_SSE_MAX_IDLE_SEC

async def _check_bearer(request: Request) -> None:
    """כיבוד דגל PUBLIC_REQUIRE_BEARER=1 אם קיים בקונפיג הכללי (אופציונלי).
       אם אתם מממשים בדיקה במקום אחר – אפשר למחוק את הפונקציה הזו.
    """
    import os
    require = str(os.getenv("PUBLIC_REQUIRE_BEARER", "0")).lower() in ("1","true","yes","on")
    if not require:
        return
    expected = os.getenv("API_BEARER_TOKEN_RO") or os.getenv("API_BEARER_TOKEN")
    auth = request.headers.get("authorization","")
    if not expected or not auth.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer")
    token = auth.split(" ",1)[1].strip()
    if token != expected:
        raise HTTPException(status_code=403, detail="Bad bearer")

def _sse_event(data: dict, event: str | None = None, eid: str | None = None) -> bytes:
    lines = []
    if event:
        lines.append(f"event: {event}")
    if eid:
        lines.append(f"id: {eid}")
    payload = json.dumps(data, ensure_ascii=False, separators=(",",":"))
    lines.append(f"data: {payload}")
    lines.append("")  # blank line to end the event
    return ("\n".join(lines) + "\n").encode("utf-8")

@router.get("/public/pos-events/stream")
async def pos_events_stream(request: Request, sym: str | None = None):
    """SSE של אירועי פוזיציות בזמן-אמת מה-Redis Pub/Sub (ערוץ pos:events:chan).
       פרמטרים:
         - sym (אופציונלי): לסנן לפי סמל ספציפי (BTCUSDT וכו').
    """
    await _check_bearer(request)
    r = await get_redis()
    if not r:
        raise HTTPException(status_code=503, detail="Redis unavailable")

    pubsub = r.pubsub()
    await pubsub.subscribe(CHANNEL)

    async def gen():
        last_beat = time.time()
        try:
            while True:
                # ננתק אם הלקוח סגר
                if await request.is_disconnected():
                    break

                # נסה לקרוא הודעה עם timeout קצר
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                now = time.time()

                if msg and msg.get("type") == "message":
                    try:
                        data = json.loads(msg["data"])
                        if sym and str(data.get("sym","")).upper() != sym.upper():
                            # סינון בצד השרת
                            pass
                        else:
                            yield _sse_event(data, event=data.get("op"), eid=str(int(now)))
                    except Exception:
                        # אם JSON לא תקין – דלג בשקט
                        pass

                # Heartbeat כדי להשאיר את החיבור חי מאחורי פרוקסי
                if (now - last_beat) >= HEARTBEAT_SEC:
                    last_beat = now
                    yield b": ping\n\n"  # הערת SSE תקנית

        finally:
            with contextlib.suppress(Exception):
                await pubsub.unsubscribe(CHANNEL)
                await pubsub.close()

    import contextlib
    return StreamingResponse(gen(), media_type="text/event-stream")
