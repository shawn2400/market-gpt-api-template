# routes/telegram_webhook.py
from __future__ import annotations
from fastapi import APIRouter, Request, HTTPException, Depends
from utils.auth import require_api_key
from utils.telegram_api import edit_message
import os, httpx

router = APIRouter(prefix="/telegram", tags=["Telegram"], dependencies=[Depends(require_api_key)])

OUT_URL = os.getenv("OUTGOING_WEBHOOK_URL", "").strip()
OUT_TOK = os.getenv("OUTGOING_WEBHOOK_TOKEN", "").strip()

async def _notify_core(trade_id: str, decision: str, meta: dict):
    if not OUT_URL:
        return {"ok": True, "sent": False}
    payload = {"trade_id": trade_id, "decision": decision, "meta": meta, "token": OUT_TOK}
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(OUT_URL, json=payload)
        return {"ok": (200 <= r.status_code < 300), "status": r.status_code, "body": r.text}

@router.post("/webhook")
async def webhook(request: Request):
    update = await request.json()

    if "callback_query" not in update:
        # אפשר להחזיר 200 תמיד – טלגרם מצפה לזה
        return {"ok": True}

    cq      = update["callback_query"]
    data    = cq.get("data", "")
    msg     = cq.get("message", {})
    chat_id = msg.get("chat", {}).get("id")
    mid     = msg.get("message_id")

    if not data or not chat_id or not mid:
        raise HTTPException(400, "invalid callback")

    if ":" not in data:
        raise HTTPException(400, "bad callback_data")

    action, tid = data.split(":", 1)

    if action == "approve":
        await edit_message(chat_id, mid, f"✅ טרייד {tid} — אושר")
        await _notify_core(tid, "APPROVE", {"chat_id": chat_id, "message_id": mid})
    elif action == "reject":
        await edit_message(chat_id, mid, f"🛑 טרייד {tid} — נדחה")
        await _notify_core(tid, "REJECT", {"chat_id": chat_id, "message_id": mid})
    elif action == "adjust":
        await edit_message(chat_id, mid, f"✏️ טרייד {tid} — בקשת כוונון")
        await _notify_core(tid, "ADJUST", {"chat_id": chat_id, "message_id": mid})
    else:
        raise HTTPException(400, "unknown action")

    return {"ok": True}

