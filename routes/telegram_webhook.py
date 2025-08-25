# routes/telegram_webhook.py
from __future__ import annotations
from fastapi import APIRouter, Request, HTTPException, Depends, Body
from pydantic import BaseModel
from typing import Optional, Dict, Any
import os, json, hmac, hashlib, httpx

# שים לב: ל-webhook של טלגרם לא שמים require_api_key (טלגרם לא ישלח Authorization).
# לכן נגן באמצעות secret token של טלגרם (X-Telegram-Bot-Api-Secret-Token).

router = APIRouter(prefix="/telegram", tags=["Telegram"])

# --- ENV ---
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
SECRET_TOKEN = os.getenv("TELEGRAM_SECRET_TOKEN", "").strip()  # אם תגדיר, טלגרם ישלח Header לבדיקת מקור
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

OUT_URL = os.getenv("OUTGOING_WEBHOOK_URL", "").strip()
OUT_TOK = os.getenv("OUTGOING_WEBHOOK_TOKEN", "").strip()
OUT_HMAC_SECRET = (os.getenv("OUTGOING_HMAC_SECRET") or os.getenv("HMAC_SECRET") or "").encode()

from utils.telegram_api import edit_message

def _sign(body: bytes) -> str:
    if not OUT_HMAC_SECRET:
        return ""
    return hmac.new(OUT_HMAC_SECRET, body, hashlib.sha256).hexdigest()

class WebhookSet(BaseModel):
    url: str
    secret_token: Optional[str] = None

@router.post("/set-webhook")
async def set_webhook(cfg: WebhookSet):
    if not BOT_TOKEN:
        raise HTTPException(400, "missing TELEGRAM_BOT_TOKEN")
    payload = {"url": cfg.url}
    # אפשר להעביר secret_token (מומלץ) — טלגרם ישלח אותו בכותרת ל-webhook שלך
    if cfg.secret_token:
        payload["secret_token"] = cfg.secret_token
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(f"{TELEGRAM_API}/setWebhook", json=payload)
        r.raise_for_status()
        return r.json()

async def _notify_core(trade_id: str, decision: str, meta: Dict[str, Any]) -> Dict[str, Any]:
    """
    מודיע ל-Core על החלטת המשתמש (APPROVE/REJECT/ADJUST/ANALYZE) עם Outbound HMAC.
    """
    if not OUT_URL:
        return {"ok": True, "sent": False, "reason": "OUTGOING_WEBHOOK_URL not set"}
    body = json.dumps({"trade_id": trade_id, "decision": decision, "meta": meta}, separators=(",", ":")).encode()
    headers = {"Content-Type": "application/json", "X-Idempotency-Key": trade_id}
    if OUT_TOK:
        headers["Authorization"] = f"Bearer {OUT_TOK}"
    sig = _sign(body)
    if sig:
        headers["X-Signature"] = sig
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(OUT_URL, content=body, headers=headers)
        ok = 200 <= r.status_code < 300
        return {"ok": ok, "status": r.status_code, "body": r.text}

def _append_status_to_text(txt: str, badge: str) -> str:
    # מוסיף שורת סטטוס בראש הטקסט, בלי לפרק את תוכן ההודעה המקורית
    prefix = f"{badge}\n"
    if txt.startswith("🧠"):
        return prefix + txt
    return prefix + txt

@router.post("/webhook")
async def webhook(request: Request):
    # 1) אימות מקור מטלגרם (אופציונלי אך מומלץ)
    if SECRET_TOKEN:
        got = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if got != SECRET_TOKEN:
            raise HTTPException(401, "invalid telegram secret token")

    upd = await request.json()

    # A) הודעות פקודה (אופציונלי, מינימלי)
    if "message" in upd:
        msg = upd["message"]
        text = str(msg.get("text", "") or "").strip()
        chat_id = msg["chat"]["id"]
        mid = msg.get("message_id")
        if text.startswith("/start"):
            return {"ok": True}
        if text.startswith("/help"):
            return {"ok": True}
        # לא מריצים כאן GPT ולא קוראים ל-Core — הבוט דק
        return {"ok": True}

    # B) לחיצות על כפתורים
    if "callback_query" in upd:
        cq = upd["callback_query"]
        data = cq.get("data", "")
        chat_id = cq["message"]["chat"]["id"]
        mid = cq["message"]["message_id"]
        txt = cq["message"].get("text", "")

        if ":" in data:
            action, tid = data.split(":", 1)
            action = action.strip().lower()
        else:
            action, tid = data.lower(), ""

        if action == "approve":
            # עריכה מיידית + הודעה ל-Core
            new_txt = _append_status_to_text(txt, "✅ *אושר ע\"י משתמש*")
            try:
                await edit_message(chat_id, mid, new_txt)
            except Exception:
                pass
            res = await _notify_core(tid, "APPROVE", {"chat_id": chat_id, "message_id": mid})
            return {"ok": True, "core": res}

        if action == "reject":
            new_txt = _append_status_to_text(txt, "❌ *נדחה ע\"י משתמש*")
            try:
                await edit_message(chat_id, mid, new_txt)
            except Exception:
                pass
            res = await _notify_core(tid, "REJECT", {"chat_id": chat_id, "message_id": mid})
            return {"ok": True, "core": res}

        if action == "adjust":
            new_txt = _append_status_to_text(txt, "✏️ *לבקשת כוונון* — שלח ערכים מעודכנים בבקשה")
            try:
                await edit_message(chat_id, mid, new_txt)
            except Exception:
                pass
            res = await _notify_core(tid, "ADJUST", {"chat_id": chat_id, "message_id": mid})
            return {"ok": True, "core": res}

        if action == "analyze":
            # אל תריץ GPT כאן; רק סימון UI + שליחת בקשה ל-Core
            new_txt = _append_status_to_text(txt, "⏳ *ניתוח GPT בתהליך…*")
            try:
                await edit_message(chat_id, mid, new_txt)
            except Exception:
                pass
            res = await _notify_core(tid, "ANALYZE", {"chat_id": chat_id, "message_id": mid})
            return {"ok": True, "core": res}

        return {"ok": True}

    return {"ok": True}



