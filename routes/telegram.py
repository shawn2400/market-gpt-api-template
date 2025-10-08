# routes/telegram.py
from __future__ import annotations
import os, time, json, logging, hashlib
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, Request, Query, HTTPException

from utils.telegram_notifier import verify_callback_data, TelegramNotifier
from utils.anti_replay import build_signature_headers

logger = logging.getLogger("algogpt.telegram.webhook")
router = APIRouter(prefix="/telegram", tags=["telegram"])

API_TOKEN = os.getenv("API_TOKEN", os.getenv("PRIMARY_API_TOKEN","")).strip()
PUBLIC_HOST = (os.getenv("PUBLIC_HOST","") or os.getenv("WEBHOOK_HOST","")).rstrip("/")
WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET","").strip()

# יעדי API פנימיים
URL_TRADE_UPDATE = f"{PUBLIC_HOST}/alerts/trades/update"
URL_MANAGE_ONCE  = f"{PUBLIC_HOST}/position-ops/manage-once"

def _auth_headers() -> Dict[str,str]:
    h = {}
    if API_TOKEN:
        h["Authorization"] = f"Bearer {API_TOKEN}"
        h["x-api-key"] = API_TOKEN
    return h

@router.get("/ping")
async def ping():
    return {"ok": True, "ts": int(time.time())}

@router.post("/webhook")
async def webhook(request: Request, secret: Optional[str] = Query(None)):
    if WEBHOOK_SECRET and secret != WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="bad_webhook_secret")

    try:
        update = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid_json")

    # Auto setWebhook on first webhook (best-effort)
    try:
        await TelegramNotifier.ensure_webhook()
    except Exception:
        pass

    if "callback_query" not in update:
        return {"ok": True, "ignored": True}

    cb = update["callback_query"]
    data = str(cb.get("data") or "")
    chat_id = None
    msg_id = None
    try:
        if cb.get("message"):
            chat_id = str(cb["message"]["chat"]["id"])
            msg_id  = int(cb["message"]["message_id"])
    except Exception:
        pass

    try:
        parsed = verify_callback_data(data)  # trade_id, action, ts, sig
        trade_id = parsed["trade_id"]
        action = parsed["action"]
    except Exception as e:
        try:
            await TelegramNotifier.answer_callback(cb.get("id",""), text=f"Callback invalid: {e}", show_alert=True)
        except Exception:
            pass
        raise HTTPException(status_code=400, detail=f"callback_invalid: {e}")

    # פעולת MANAGE מפעילה manage-once; APPROVE/REJECT קוראים לעדכון
    try:
        async with httpx.AsyncClient(timeout=15.0) as cli:
            if action in ("APPROVE","REJECT"):
                body = {"ticket_id": trade_id, "action": action}
                headers = {**_auth_headers(), **build_signature_headers("/alerts/trades/update", body)}
                r = await cli.post(URL_TRADE_UPDATE, json=body, headers=headers)
                ok = (r.status_code < 400)
                txt = "Approved ✅" if action=="APPROVE" else "Rejected ❌"
            else:  # MANAGE
                body = {"symbol": "", "do": ["be","trail","tp_ladder"]}
                # במוד ניהול כללי (ללא קשר ל-symbol) — נשמור הודעה פשוטה
                headers = {**_auth_headers(), **build_signature_headers("/position-ops/manage-once", body)}
                r = await cli.post(URL_MANAGE_ONCE, json=body, headers=headers)
                ok = (r.status_code < 400)
                txt = "ManageOnce triggered ⚙️"

        try:
            await TelegramNotifier.answer_callback(cb.get("id",""), text=txt, show_alert=False)
            if chat_id and msg_id:
                await TelegramNotifier.edit_message_buttons(chat_id, msg_id, trade_id, disabled=True)
        except Exception:
            pass

        if not ok:
            raise HTTPException(status_code=500, detail=f"downstream_error: {r.status_code}")
        return {"ok": True, "action": action, "trade_id": trade_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("webhook handling failed: %s", e)
        raise HTTPException(status_code=500, detail=f"webhook_error: {e}")
