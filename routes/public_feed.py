# routes/public_feed.py
from __future__ import annotations
import os
import logging
from typing import Dict, Any, Optional

from fastapi import APIRouter, Request, Depends, HTTPException
from starlette.status import HTTP_403_FORBIDDEN

# נעדיף את ליבת ה־notifier הא-סינכרונית
try:
    from utils.telegram_notifier_core import _tg_send as tg_send  # type: ignore
except Exception:
    tg_send = None  # type: ignore

logger = logging.getLogger("algogpt.public_feed")

router = APIRouter(
    prefix="/public-feed",
    tags=["Public Feed"],
)

WEBHOOK_HMAC_SECRET: Optional[str] = os.getenv("WEBHOOK_HMAC_SECRET")
PUBLIC_FEED_CHANNEL_ID_ENV = os.getenv("PUBLIC_FEED_CHANNEL_ID", "").strip()
ENABLE_PUBLIC_FEED = str(os.getenv("ENABLE_PUBLIC_FEED", "0")).lower() in ("1", "true", "yes", "on")

def require_webhook_secret(request: Request):
    if not ENABLE_PUBLIC_FEED:
        raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="public feed disabled")
    sig = request.headers.get("X-Hub-Signature")
    if not sig:
        raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="missing signature")
    if not WEBHOOK_HMAC_SECRET or sig != WEBHOOK_HMAC_SECRET:
        raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="invalid signature")

@router.post("/broadcast", summary="Broadcast trade alert to public Telegram feed")
async def broadcast_trade(request: Request, _: Any = Depends(require_webhook_secret)) -> Dict[str, Any]:
    if tg_send is None:
        raise HTTPException(status_code=500, detail="telegram notifier unavailable")

    try:
        data = await request.json()
        symbol = data.get("symbol")
        message = data.get("message")

        if not symbol or not message:
            raise HTTPException(status_code=400, detail="missing fields")

        if not PUBLIC_FEED_CHANNEL_ID_ENV:
            raise HTTPException(status_code=500, detail="public channel not configured")

        # תמיכה ב־int/str
        try:
            chat_id: int | str = int(PUBLIC_FEED_CHANNEL_ID_ENV)
        except Exception:
            chat_id = PUBLIC_FEED_CHANNEL_ID_ENV

        await tg_send(text=str(message), chat_id=chat_id)  # async send
        logger.info({"event": "public-feed.broadcasted", "symbol": symbol})
        return {"ok": True, "message": "broadcasted"}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("public_feed_broadcast_error")
        raise HTTPException(status_code=500, detail=str(e))


