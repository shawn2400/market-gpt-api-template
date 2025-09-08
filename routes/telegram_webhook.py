# routes/telegram_webhook.py
from __future__ import annotations
import os, logging
from typing import Any, Dict
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
import httpx
from utils.metrics_tracker import get_metrics_snapshot

logger = logging.getLogger("algogpt.telegram.webhook")
router = APIRouter(prefix="/telegram", tags=["Telegram"])

TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ADMIN_ONLY = str(os.getenv("TELEGRAM_ADMIN_ONLY", "1")).lower() in ("1","true","yes","on")
ADMIN_IDS = {s.strip() for s in (os.getenv("TELEGRAM_ADMIN_IDS","") or "").split(",") if s.strip()}


def _allowed_user(uid: int) -> bool:
    if not ADMIN_ONLY:
        return True
    return str(uid) in ADMIN_IDS


async def _reply(chat_id: int, text: str):
    """שליחת תשובה למשתמש בטלגרם"""
    if not TG_TOKEN:
        return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    try:
        async with httpx.AsyncClient(timeout=8.0) as cli:
            await cli.post(url, json=payload)
    except Exception as e:
        logger.warning(f"[tg] sendMessage failed: {e}")


HELP_TEXT = (
    "🤖 *AlgoGPT Bot* — Help / עזרה\n\n"
    "• /help — עזרה\n"
    "• /status — סטטוס מערכת\n"
    "• /positions — פוזיציות פתוחות\n"
    "• /pnl — סיכום PnL\n"
    "• /scan SYMBOL [15m|1h|4h] — סריקה\n"
    "• /exec_dry SYMBOL BUY|SELL QTY ENTRY SL TP LEV — סימולציה\n"
    "• /system — ניטור משאבים\n"
)

@router.post("/webhook")
async def webhook(req: Request):
    if not TG_TOKEN:
        raise HTTPException(status_code=400, detail="Missing TELEGRAM_BOT_TOKEN")
    try:
        update = await req.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Bad payload")

    msg = update.get("message") or {}
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    user = msg.get("from") or {}
    uid = int(user.get("id") or 0)
    text = (msg.get("text") or "").strip()

    if not chat_id or not uid:
        return {"ok": True}
    if not _allowed_user(uid):
        await _reply(chat_id, "⛔️ אין לך הרשאה להשתמש בבוט זה.")
        return {"ok": True}

    if not text or text in ("/start", "/help"):
        await _reply(chat_id, HELP_TEXT)
        return {"ok": True}

    parts = text.split()
    cmd = parts[0].lower()

    if cmd == "/status":
        metrics = get_metrics_snapshot()
        await _reply(chat_id, f"📊 *Status*\n```{metrics}```")
        return {"ok": True}

    if cmd == "/pnl":
        await _reply(chat_id, "💹 PnL Summary: (בשלב זה מחובר ל-/pnl/summary API)")
        return {"ok": True}

    if cmd == "/scan":
        if len(parts) < 2:
            await _reply(chat_id, "שימוש: /scan SYMBOL [15m|1h|4h]")
            return {"ok": True}
        sym = parts[1].upper()
        interval = parts[2] if len(parts) > 2 else "15m"
        await _reply(chat_id, f"🔎 Scan {sym} @ {interval} (placeholder)")
        return {"ok": True}

    if cmd == "/exec_dry":
        await _reply(chat_id, f"🧪 Dry run: {parts}")
        return {"ok": True}

    if cmd == "/system":
        metrics = get_metrics_snapshot()
        await _reply(chat_id, f"🖥 System Metrics:\n```{metrics}```")
        return {"ok": True}

    await _reply(chat_id, "❓ פקודה לא מזוהה. /help לתפריט.")
    return {"ok": True}






