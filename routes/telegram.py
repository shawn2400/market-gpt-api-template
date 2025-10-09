# routes/telegram.py
from __future__ import annotations
import os, time, json, logging
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, Request, Query, HTTPException, Header

from utils.telegram_notifier import (
    verify_callback_data,
    TelegramNotifier,
)
from utils.anti_replay import build_signature_headers

logger = logging.getLogger("algogpt.telegram.webhook")
router = APIRouter(prefix="/telegram", tags=["telegram"])

API_TOKEN    = os.getenv("API_TOKEN", os.getenv("PRIMARY_API_TOKEN","")).strip()
PUBLIC_HOST  = (os.getenv("PUBLIC_HOST","") or os.getenv("WEBHOOK_HOST","")).rstrip("/")
WEBHOOK_SEC  = os.getenv("TELEGRAM_WEBHOOK_SECRET","").strip()

# יעדי API פנימיים
URL_TRADE_UPDATE   = f"{PUBLIC_HOST}/alerts/trades/update"
URL_MANAGE_ONCE    = f"{PUBLIC_HOST}/position-ops/manage-once"
URL_POS_CANCEL_TPS = f"{PUBLIC_HOST}/position-ops/cancel-tps"      # alias תקני
URL_POS_CLOSE_PCT  = f"{PUBLIC_HOST}/position-ops/close-percent"   # alias תקני

def _auth_headers() -> Dict[str,str]:
    h: Dict[str,str] = {}
    if API_TOKEN:
        h["Authorization"] = f"Bearer {API_TOKEN}"
        h["x-api-key"]     = API_TOKEN
    return h

@router.get("/ping")
async def ping():
    return {"ok": True, "ts": int(time.time())}

@router.post("/webhook")
async def webhook(
    request: Request,
    # תאימות ישנה (optional ?secret=):
    secret_qs: Optional[str] = Query(None, alias="secret"),
    # אימות תקני של טלגרם (Header):
    x_telegram_bot_api_secret_token: Optional[str] = Header(None)
):
    # אימות Secret Header (עדיפות גבוהה), תאימות ל-?secret קיימת:
    if WEBHOOK_SEC:
        header_ok = (x_telegram_bot_api_secret_token or "") == WEBHOOK_SEC
        query_ok  = (secret_qs or "") == WEBHOOK_SEC
        if not (header_ok or query_ok):
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

    # לא מטפלים בהודעות טקסט — רק callback_query
    if "callback_query" not in update:
        return {"ok": True, "ignored": True}

    cb      = update["callback_query"]
    cb_id   = str(cb.get("id",""))
    data    = str(cb.get("data") or "")
    message = cb.get("message") or {}
    chat_id = str(((message.get("chat") or {}).get("id")) or "")
    msg_id  = int(message.get("message_id") or 0)

    # פענוח / אימות callback_data (תומך גם בחתימות אם צורפו)
    try:
        parsed   = verify_callback_data(data)  # dict
        action   = parsed["action"]            # e.g. APPROVE / REJECT / MANAGE_AGAIN / CANCEL_TPS / CLOSE_50
        trade_id = parsed.get("trade_id")      # idem / ticket_id (ל-approve/reject)
        symbol   = parsed.get("symbol")        # לכפתורי POS
        pct      = float(parsed.get("pct", 0) or 0.0)
    except Exception as e:
        try:
            await TelegramNotifier.answer_callback(cb_id, text=f"Callback invalid: {e}", show_alert=True)
        except Exception:
            pass
        raise HTTPException(status_code=400, detail=f"callback_invalid: {e}")

    # שליחת הבקשה הפנימית לפי סוג הפעולה
    try:
        async with httpx.AsyncClient(timeout=20.0) as cli:
            if action in ("APPROVE","REJECT"):
                body    = {"ticket_id": trade_id, "action": action}
                headers = {**_auth_headers(), **build_signature_headers("/alerts/trades/update", body)}
                r       = await cli.post(URL_TRADE_UPDATE, json=body, headers=headers)
                ok      = r.status_code < 400
                txt     = "Approved ✅" if action == "APPROVE" else "Rejected ❌"

                # נטרל כפתורי אישור/דחייה בהודעה המקורית
                try:
                    await TelegramNotifier.answer_callback(cb_id, text=txt, show_alert=False)
                    if chat_id and msg_id:
                        await TelegramNotifier.edit_message_buttons(chat_id, msg_id, disable_all=True)
                except Exception:
                    pass

                if not ok:
                    raise HTTPException(status_code=502, detail=f"downstream_error: {r.status_code}")
                return {"ok": True, "action": action, "trade_id": trade_id}

            # כפתורי Position-Ops:
            elif action == "MANAGE_AGAIN":
                body    = {"symbol": symbol or "", "do": ["be","trail","tp_ladder"]}
                headers = {**_auth_headers(), **build_signature_headers("/position-ops/manage-once", body)}
                r       = await cli.post(URL_MANAGE_ONCE, json=body, headers=headers)
                ok      = r.status_code < 400
                txt     = "ManageOnce triggered ⚙️"
                await TelegramNotifier.answer_callback(cb_id, text=txt, show_alert=False)
                if not ok:
                    raise HTTPException(status_code=502, detail=f"downstream_error: {r.status_code}")
                return {"ok": True, "action": action, "symbol": symbol}

            elif action == "CANCEL_TPS":
                body    = {"symbol": symbol}
                headers = {**_auth_headers(), **build_signature_headers("/position-ops/cancel-tps", body)}
                r       = await cli.post(URL_POS_CANCEL_TPS, json=body, headers=headers)
                ok      = r.status_code < 400
                await TelegramNotifier.answer_callback(cb_id, text="TPs canceled 🧹", show_alert=False)
                if not ok:
                    raise HTTPException(status_code=502, detail=f"downstream_error: {r.status_code}")
                return {"ok": True, "action": action, "symbol": symbol}

            elif action == "CLOSE_50":
                close_pct = pct or 50.0
                body      = {"symbol": symbol, "pct": close_pct}
                headers   = {**_auth_headers(), **build_signature_headers("/position-ops/close-percent", body)}
                r         = await cli.post(URL_POS_CLOSE_PCT, json=body, headers=headers)
                ok        = r.status_code < 400
                await TelegramNotifier.answer_callback(cb_id, text=f"Closed ~{close_pct:.0f}% ➗", show_alert=False)
                if not ok:
                    raise HTTPException(status_code=502, detail=f"downstream_error: {r.status_code}")
                return {"ok": True, "action": action, "symbol": symbol, "pct": close_pct}

            else:
                await TelegramNotifier.answer_callback(cb_id, text=f"Unknown action: {action}", show_alert=True)
                raise HTTPException(status_code=400, detail="unknown_action")

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("webhook handling failed: %s", e)
        raise HTTPException(status_code=500, detail=f"webhook_error: {e}")



