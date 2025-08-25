# routes/analysis_sink.py
from __future__ import annotations
from fastapi import APIRouter, Depends, Body, Header, HTTPException, Request
from pydantic import BaseModel
from typing import Optional, Dict, Any
import os, httpx

try:
    from utils.auth import require_api_key
except Exception:
    def require_api_key():
        return None

from utils.security import verify_hmac, idem_seen

router = APIRouter(prefix="/alerts", tags=["Alerts"], dependencies=[Depends(require_api_key)])

BOT = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID_DEFAULT = os.getenv("TELEGRAM_CHAT_ID", "").strip()
TELEGRAM_API = f"https://api.telegram.org/bot{BOT}"
TIMEOUT = float(os.getenv("TELEGRAM_HTTP_TIMEOUT", "15"))

class AnalysisIn(BaseModel):
    text: str
    chat_id: Optional[int | str] = None
    reply_to_message_id: Optional[int] = None
    parse_mode: Optional[str] = "Markdown"
    disable_web_page_preview: bool = True
    silent: bool = False

@router.post("/analysis")
async def post_analysis(
    request: Request,
    payload: AnalysisIn = Body(...),
    x_idempotency_key: Optional[str] = Header(default=None, convert_underscores=False),
    x_signature: Optional[str] = Header(default=None, convert_underscores=False),
):
    if not BOT:
        raise HTTPException(500, "TELEGRAM_BOT_TOKEN not configured")

    raw = await request.body()
    if not verify_hmac(x_signature, raw):
        raise HTTPException(401, "Invalid signature")

    if x_idempotency_key and idem_seen(x_idempotency_key):
        return {"ok": True, "duplicate": True}

    chat_id = payload.chat_id or CHAT_ID_DEFAULT
    if not chat_id:
        raise HTTPException(400, "chat_id missing and TELEGRAM_CHAT_ID not set")

    text = payload.text[:3900] + ("\n…" if len(payload.text) > 3900 else "")
    body: Dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": payload.disable_web_page_preview,
        "parse_mode": payload.parse_mode or "Markdown",
        "disable_notification": payload.silent,
    }
    if payload.reply_to_message_id:
        body["reply_to_message_id"] = payload.reply_to_message_id
        body["allow_sending_without_reply"] = True

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.post(f"{TELEGRAM_API}/sendMessage", json=body)
        r.raise_for_status()
        return r.json()


