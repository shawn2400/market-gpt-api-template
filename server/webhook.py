# server/webhook.py
from __future__ import annotations
import os, hmac, hashlib, logging
from typing import Optional
from fastapi import FastAPI, Request, HTTPException

from utils.mode_store import ExecMode
from utils.trade_executor import ConfirmStore
from telegram.commands import send_message

log = logging.getLogger("algogpt.webhook")
WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET","").strip()
ADMIN_ID = os.getenv("TELEGRAM_ADMIN_ID","").strip() or os.getenv("ADMIN_CHAT_ID","").strip()

app = FastAPI(title="AlgoGPT Webhook")

def _authorized(uid: Optional[int]) -> bool:
    if not ADMIN_ID:
        return True
    return str(uid or "") == str(ADMIN_ID)

@app.post("/telegram/webhook")
async def telegram_webhook(req: Request):
    if WEBHOOK_SECRET:
        body = await req.body()
        sig = req.headers.get("X-Tg-Sign","")
        exp = hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, exp):
            raise HTTPException(401, "bad signature")
    data = await req.json()

    msg = data.get("message") or data.get("edited_message")
    if msg:
        chat_id = (msg.get("chat") or {}).get("id")
        text    = msg.get("text") or ""
        from_id = (msg.get("from") or {}).get("id")

        if text.startswith("/mode"):
            if not _authorized(from_id):
                await send_message(chat_id, "אין הרשאה.")
                return {"ok": True}
            _, _, arg = text.partition(" ")
            new_mode = "live" if arg.lower().strip() == "live" else "dry"
            ExecMode.set(new_mode)
            await send_message(chat_id, f"מצב עודכן: <b>{new_mode.upper()}</b>", "HTML")
            return {"ok": True}
        if text in ("/mode", "/mode@thisbot"):
            await send_message(chat_id, f"מצב נוכחי: <b>{ExecMode.get().upper()}</b>\nשנה באמצעות: /mode dry או /mode live", "HTML")
            return {"ok": True}

        return {"ok": True}

    cb = data.get("callback_query")
    if cb:
        chat_id = (cb.get("message") or {}).get("chat",{}).get("id")
        from_id = (cb.get("from") or {}).get("id")
        data_str = cb.get("data") or ""
        if data_str.startswith("CONFIRM:"):
            _, action, cid = data_str.split(":", 2)
            if not _authorized(from_id):
                await send_message(chat_id, "אין הרשאה לאשר טרייד.")
                return {"ok": True}
            if action == "APPROVE":
                ConfirmStore.approve(cid, str(from_id))
                await send_message(chat_id, f"✅ אושר · CID={cid}")
            elif action == "REJECT":
                ConfirmStore.reject(cid, str(from_id))
                await send_message(chat_id, f"❌ בוטל · CID={cid}")
        return {"ok": True}

    return {"ok": True}

