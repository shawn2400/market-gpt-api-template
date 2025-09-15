# routes/telegram_fallback.py
from __future__ import annotations
import os
import time
import logging
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, Request, Header, HTTPException

from utils.trade_executor import ConfirmStore

router = APIRouter()

# ────────────────────────────────────────────────────────────────────────────────
# Env
# ────────────────────────────────────────────────────────────────────────────────
WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
BOT_TOKEN      = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
API_BASE       = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else ""
PM_ENV         = (os.getenv("TELEGRAM_PARSE_MODE", "").strip() or None)  # None => לא שולחים parse_mode

# Admin policy
ADMIN_ONLY = os.getenv("TELEGRAM_ADMIN_ONLY", "1").lower() in ("1","true","yes","on")
ADMIN_IDS  = {s.strip() for s in (os.getenv("TELEGRAM_ADMIN_IDS","") or "").split(",") if s.strip()}

def _is_admin(uid: int) -> bool:
    if not ADMIN_ONLY:
        return True
    return str(uid) in ADMIN_IDS

async def _tg_send(chat_id: int, text: str):
    if not BOT_TOKEN:
        return
    payload: Dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    if PM_ENV:
        payload["parse_mode"] = PM_ENV
    try:
        async with httpx.AsyncClient(timeout=10.0) as cli:
            await cli.post(f"{API_BASE}/sendMessage", json=payload)
    except Exception as e:
        logging.getLogger("algogpt.telegram").warning("telegram send failed: %s", e)

async def _tg_answer_callback(cbq_id: str, text: str = ""):
    if not (BOT_TOKEN and cbq_id):
        return
    try:
        async with httpx.AsyncClient(timeout=10.0) as cli:
            await cli.post(f"{API_BASE}/answerCallbackQuery", json={
                "callback_query_id": cbq_id, "text": text, "show_alert": False
            })
    except Exception as e:
        logging.getLogger("algogpt.telegram").warning("answerCallbackQuery failed: %s", e)

async def _tg_disable_kb(chat_id: int, message_id: int):
    if not BOT_TOKEN:
        return
    try:
        async with httpx.AsyncClient(timeout=10.0) as cli:
            await cli.post(f"{API_BASE}/editMessageReplyMarkup", json={
                "chat_id": chat_id, "message_id": message_id, "reply_markup": {"inline_keyboard": []}
            })
    except Exception as e:
        logging.getLogger("algogpt.telegram").warning("disable_kb failed: %s", e)

# ────────────────────────────────────────────────────────────────────────────────
# Routes
# ────────────────────────────────────────────────────────────────────────────────
@router.get("/telegram/ping", include_in_schema=False)
async def tg_ping():
    return {"ok": True, "src": "telegram", "ts_ms": int(time.time() * 1000)}

@router.post("/telegram/webhook", include_in_schema=False)
async def telegram_webhook(request: Request, x_telegram_bot_api_secret_token: str | None = Header(default=None)):
    # Secret header (הגנת webhook)
    if WEBHOOK_SECRET and (not x_telegram_bot_api_secret_token or x_telegram_bot_api_secret_token.strip() != WEBHOOK_SECRET):
        raise HTTPException(401, "Invalid telegram secret")

    try:
        update = await request.json()
    except Exception:
        raise HTTPException(400, "invalid JSON")

    # callback_query — אישור/ביטול
    cb = update.get("callback_query")
    if cb:
        cb_id = cb.get("id")
        from_user = cb.get("from") or {}
        uid = int(from_user.get("id") or 0)
        msg = cb.get("message") or {}
        chat_id = int((msg.get("chat") or {}).get("id") or 0)
        message_id = int(msg.get("message_id") or 0)
        data = str(cb.get("data") or "")
        if not _is_admin(uid):
            await _tg_answer_callback(cb_id, "⛔️ אין הרשאה")
            return {"ok": True}

        parts = data.split(":", 2)
        if len(parts) == 3 and parts[0] == "CONFIRM":
            action, cid = parts[1], parts[2]
            rec = ConfirmStore.get(cid)
            if not rec or rec.get("status") != "pending":
                if chat_id and message_id:
                    await _tg_disable_kb(chat_id, message_id)
                await _tg_answer_callback(cb_id, "פג תוקף/כבר טופל")
                return {"ok": True}
            if action == "APPROVE":
                ConfirmStore.approve(cid, approver=str(uid))
                await _tg_answer_callback(cb_id, "אושר ✅")
                if chat_id and message_id:
                    await _tg_disable_kb(chat_id, message_id)
                return {"ok": True}
            if action == "REJECT":
                ConfirmStore.reject(cid, approver=str(uid))
                await _tg_answer_callback(cb_id, "בוטל ❌")
                if chat_id and message_id:
                    await _tg_disable_kb(chat_id, message_id)
                return {"ok": True}
            await _tg_answer_callback(cb_id, "פעולה לא מזוהה")
            return {"ok": True}

    # הודעות טקסט פשוטות (לשימוש מהיר: /ping)
    msg = update.get("message")
    if msg and str(msg.get("text", "")).strip() == "/ping":
        chat_id = int((msg.get("chat") or {}).get("id") or 0)
        if chat_id:
            await _tg_send(chat_id, "pong ✅")
        return {"ok": True}

    return {"ok": True}
