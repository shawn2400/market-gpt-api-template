# routes/public_pos_events.py
from __future__ import annotations

import os
import asyncio
import json
import time
import contextlib
import typing as t

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse

from utils.redis_helper import get_redis

router = APIRouter(tags=["Public Feed"])

# ======== Config via ENV (עם ערכי-ברירת-מחדל בטוחים) ========
CHANNEL = os.getenv("POS_EVENTS_CHAN", "pos:events:chan")
HEARTBEAT_SEC = int(os.getenv("PUBLIC_SSE_HEARTBEAT_SEC", "20") or 20)
IDLE_TIMEOUT_SEC = int(os.getenv("PUBLIC_SSE_MAX_IDLE_SEC", "300") or 300)  # מיושר ל-render.yaml כברירת מחדל

def _get_bearer_from_req(request: Request) -> str:
    """
    מנסה להביא Bearer מהיכן שנוח:
    - Authorization: Bearer xxx
    - Query: ?bearer=xxx
    - Cookie: bearer=xxx
    """
    # Header
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()

    # Query
    try:
        q = request.query_params.get("bearer")
        if q:
            return str(q).strip()
    except Exception:
        pass

    # Cookie
    try:
        ck = request.cookies.get("bearer")
        if ck:
            return str(ck).strip()
    except Exception:
        pass

    return ""

async def _check_bearer(request: Request) -> None:
    """
    אם PUBLIC_REQUIRE_BEARER=1 — נדרשת אסמכתא Bearer (קריאה מטוקן קריאה בלבד RO).
    אחרת — אין צורך באסמכתא למסלול הציבורי.
    """
    require = str(os.getenv("PUBLIC_REQUIRE_BEARER", "0")).lower() in ("1", "true", "yes", "on")
    if not require:
        return
    expected = (os.getenv("API_BEARER_TOKEN_RO") or os.getenv("API_BEARER_TOKEN") or "").strip()
    token = _get_bearer_from_req(request)
    if not expected or not token:
        raise HTTPException(status_code=401, detail="Missing bearer")
    if token != expected:
        raise HTTPException(status_code=403, detail="Bad bearer")

def _sse_event(data: t.Mapping[str, t.Any], event: str | None = None, eid: str | None = None) -> bytes:
    """
    בונה אירוע SSE תקני:
      event: <name>
      id: <id>
      data: <json>
    (מופרד בשורה ריקה בסוף)
    """
    lines: list[str] = []
    if event:
        lines.append(f"event: {event}")
    if eid:
        lines.append(f"id: {eid}")
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    lines.append(f"data: {payload}")
    lines.append("")  # blank line to end the event
    return ("\n".join(lines) + "\n").encode("utf-8")

@router.get("/public/pos-events/stream")
async def pos_events_stream(request: Request, sym: str | None = None):
    """
    SSE של אירועי פוזיציות בזמן-אמת מתוך Redis Pub/Sub (ערוץ POS_EVENTS_CHAN).
    פרמטרים:
      - sym (אופציונלי): מסנן צד-שרת לסמל ספציפי (למשל BTCUSDT).
    הערות:
      - נשלח heartbeat כל HEARTBEAT_SEC שניות כדי לשמר חיבור מול פרוקסי.
      - ניתוק אוטומטי על חוסר פעילות לאחר IDLE_TIMEOUT_SEC.
    """
    await _check_bearer(request)

    r = await get_redis()
    if not r:
        raise HTTPException(status_code=503, detail="Redis unavailable")

    pubsub = r.pubsub()
    await pubsub.subscribe(CHANNEL)

    async def gen():
        last_any = time.time()   # כל נתון או heartbeat מאפסים אותו
        last_beat = time.time()

        try:
            while True:
                # ננתק אם הלקוח סגר
                if await request.is_disconnected():
                    break

                now = time.time()

                # Timeout קצר על הקריאה מה-PubSub כדי שנוכל לייצר heartbeat
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)

                if msg and msg.get("type") == "message":
                    try:
                        raw = msg["data"]
                        # יכול להגיע bytes או str (תלוי בהגדרת redis client)
                        if isinstance(raw, (bytes, bytearray)):
                            raw = raw.decode("utf-8", "ignore")
                        data = json.loads(raw)

                        # סינון לפי sym אם התבקש
                        if sym and str(data.get("sym", "")).upper() != sym.upper():
                            pass
                        else:
                            last_any = now
                            yield _sse_event(
                                data,
                                event=str(data.get("op") or "pos_event"),
                                eid=str(int(now))
                            )
                    except Exception:
                        # אם JSON לא תקין – דלג בשקט
                        pass

                # Heartbeat תקני (הערת SSE)
                if (now - last_beat) >= HEARTBEAT_SEC:
                    last_beat = now
                    last_any = now
                    # הערות SSE מתחילות ב-":" — שומרות על החיבור חי
                    yield b": ping\n\n"

                # ניתוק על חוסר פעילות (למניעת חיבורים שנשארים לנצח)
                if IDLE_TIMEOUT_SEC > 0 and (now - last_any) >= IDLE_TIMEOUT_SEC:
                    # שולחים פינג אחרון ואז נפרדים
                    yield b": idle-timeout\n\n"
                    break
        finally:
            with contextlib.suppress(Exception):
                await pubsub.unsubscribe(CHANNEL)
            with contextlib.suppress(Exception):
                await pubsub.close()

    # כותרות מתאימות ל-SSE מאחורי פרוקסי/CDN
    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",      # nginx
        "Connection": "keep-alive",
    }
    return StreamingResponse(gen(), media_type="text/event-stream", headers=headers)

