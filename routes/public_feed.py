# routes/public_feed.py
from __future__ import annotations
import os
import logging
from typing import Dict, Any

from fastapi import APIRouter, Request, Depends, HTTPException
from starlette.status import HTTP_403_FORBIDDEN

from utils.telegram_notifier import _send as send_telegram_raw

logger = logging.getLogger("algogpt.public_feed")

router = APIRouter(
    prefix="/public-feed",
    tags=["Public Feed"],
)

# הרשאות סוד עבור webhook
WEBHOOK_HMAC_SECRET = os.getenv("WEBHOOK_HMAC_SECRET")
PUBLIC_FEED_CHANNEL_ID = os.getenv("PUBLIC_FEED_CHANNEL_ID")
ENABLE_PUBLIC_FEED = str(os.getenv("ENABLE_PUBLIC_FEED", "0")).lower() in ("1", "true", "yes", "on")


def require_webhook_secret(request: Request):
    if not ENABLE_PUBLIC_FEED:
        raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="public feed disabled")
    if "X-Hub-Signature" not in request.headers:
        raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="missing signature")
    sig = request.headers["X-Hub-Signature"]
    if sig != WEBHOOK_HMAC_SECRET:
        raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="invalid signature")


@router.post("/broadcast", summary="Broadcast trade alert to public Telegram feed")
async def broadcast_trade(request: Request, _: Any = Depends(require_webhook_secret)) -> Dict[str, Any]:
    try:
        data = await request.json()
        symbol = data.get("symbol")
        message = data.get("message")

        if not symbol or not message:
            raise HTTPException(status_code=400, detail="missing fields")

        if not PUBLIC_FEED_CHANNEL_ID:
            raise HTTPException(status_code=500, detail="public channel not configured")

        # שליחת ההודעה לערוץ
        send_telegram_raw(text=message, chat_id=PUBLIC_FEED_CHANNEL_ID)
        logger.info("[public-feed] broadcasted: %s", message)
        return {"ok": True, "message": "broadcasted"}

    except Exception as e:
        logger.exception("public_feed_broadcast_error")
        raise HTTPException(status_code=500, detail=str(e))

