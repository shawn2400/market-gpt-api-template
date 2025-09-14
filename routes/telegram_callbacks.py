# routes/telegram_callbacks.py
from __future__ import annotations
import os, logging
from typing import Any, Dict
from fastapi import APIRouter, Request, HTTPException, Header
from fastapi.responses import JSONResponse
import httpx

from utils.trade_executor import ConfirmStore

logger = logging.getLogger("algogpt.telegram.callbacks")
router = APIRouter(prefix="/telegram", tags=["Telegram"])

TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()

ADMIN_ONLY = os.getenv("TELEGRAM_ADMIN_ONLY", "1").lower() in ("1","true","yes","on")
ADMIN_IDS  = {s.strip() for s in (os.getenv("TELEGRAM_ADMIN_IDS","") or "").split(",") if s.strip()}
def _is_admin(uid: int) -> bool:
    if not ADMIN_ONLY:
        return True
    return str(uid) in ADMIN_IDS

async def _tg_answer_callback(cbq_id: str, text: str = "") -> None:
    if not (TG_TOKEN and cbq_id):
        return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/answerCallbackQuery"
    try:
        async with httpx.AsyncClient(timeout=8.0) as cli:
            await cli.post(url, data={"callback_query_id": cbq_id, "text": text, "show_alert": False})
    except Exception as e:
        logger.warning(f"[tg] answerCallbackQuery failed: {e}")

async def _disable_kb(chat_id: int, message_id: int) -> None:
    if not TG_TOKEN:
        return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/editMessageReplyMarkup"
    try:
        async with httpx.AsyncClient(timeout=8.0) as cli:
            await cli.post(url, data={"chat_id": chat_id, "message_id": message_id, "reply_markup": '{"inline_keyboard":[]}'})
    except Exception as e:
        logger.warning(f"[tg] editMessageReplyMarkup failed: {e}")

@router.post("/callback")
async def callback_handler(req: Request, x_telegram_bot_api_secret_token: str | None = Header(default=None)):
    # הגנת Secret כמו ב-/webhook
    if WEBHOOK_SECRET and (not x_telegram_bot_api_secret_token or x_telegram_bot_api_secret_token.strip() != WEBHOOK_SECRET):
        raise HTTPException(status_code=401, detail="Invalid telegram secret")

    try:
        update = await req.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Bad payload")

    cb = update.get("callback_query")
    if not cb:
        return {"ok": True}

    cb_id = cb.get("id") or ""
    from_user = cb.get("from") or {}
    uid = int(from_user.get("id") or 0)
    msg = cb.get("message") or {}
    chat_id = int((msg.get("chat") or {}).get("id") or 0)
    message_id = int(msg.get("message_id") or 0)
    data = str(cb.get("data") or "")

    if not _is_admin(uid):
        await _tg_answer_callback(cb_id, "⛔️ אין הרשאה")
        return {"ok": True}

    if not data.startswith("CONFIRM:"):
        await _tg_answer_callback(cb_id, "לא נתמך")
        return {"ok": True}

    try:
        _, action, cid = data.split(":", 2)
    except ValueError:
        await _tg_answer_callback(cb_id, "פורמט לא תקין")
        return {"ok": True}

    rec = ConfirmStore.get(cid)
    if not rec or rec.get("status") != "pending":
        if chat_id and message_id:
            await _disable_kb(chat_id, message_id)
        await _tg_answer_callback(cb_id, "פג תוקף/כבר טופל")
        return {"ok": True}

    if action == "APPROVE":
        ConfirmStore.approve(cid, approver=str(uid))
        await _tg_answer_callback(cb_id, "אושר ✅")
        if chat_id and message_id:
            await _disable_kb(chat_id, message_id)
        return JSONResponse(content={"ok": True})

    if action == "REJECT":
        ConfirmStore.reject(cid, approver=str(uid))
        await _tg_answer_callback(cb_id, "בוטל ❌")
        if chat_id and message_id:
            await _disable_kb(chat_id, message_id)
        return JSONResponse(content={"ok": True})

    await _tg_answer_callback(cb_id, "פעולה לא מזוהה")
    return {"ok": True}

