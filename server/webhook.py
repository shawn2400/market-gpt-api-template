# /app/server/webhook.py
from __future__ import annotations
import os
import logging
from typing import Optional
from fastapi import FastAPI, Request
import httpx

log = logging.getLogger("webhook")
app = FastAPI(title="AlgoGPT Webhook")

# ── Mode resolution (בלי להוסיף ENV חדשים) ─────────────────────────────
# סדר עדיפויות:
# 1) ROUTES_ONLY = "live"|"dry" (שימוש כ-FORCE_MODE מבלי להוסיף משתנה חדש)
# 2) DEFAULT_MODE = "live"|"dry" (אם תרצה בכל זאת להגדיר)
# 3) EXECUTE_TRADES (1→live, אחרת dry) ← כבר קיים אצלך
def _initial_mode() -> str:
    force = (os.getenv("ROUTES_ONLY") or "").strip().lower()
    if force in ("live", "dry"):
        return force
    dflt = (os.getenv("DEFAULT_MODE") or "").strip().lower()
    if dflt in ("live", "dry"):
        return dflt
    exec_trades = (os.getenv("EXECUTE_TRADES", "1")).strip().lower()
    return "live" if exec_trades in ("1", "true", "yes", "on") else "dry"

_MODE = _initial_mode()

def get_mode() -> str:
    return _MODE

def set_mode(val: str) -> None:
    global _MODE
    _MODE = "live" if str(val).lower().strip() == "live" else "dry"

# ── Telegram minimal helper ─────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

async def _tg_send(chat_id: int, text: str, parse: Optional[str] = "HTML") -> None:
    if not TELEGRAM_BOT_TOKEN or not chat_id:
        return
    payload = {"chat_id": chat_id, "text": text}
    if parse:
        payload["parse_mode"] = parse
    try:
        async with httpx.AsyncClient(timeout=10.0) as cli:
            await cli.post(f"{TELEGRAM_API}/sendMessage", json=payload)
    except Exception as e:
        log.warning("telegram send failed: %s", e)

# ── Routes ──────────────────────────────────────────────────────────────
@app.get("/ping")
async def ping():
    return {"ok": True, "mode": get_mode()}

@app.post("/telegram/webhook")
async def telegram_webhook(req: Request):
    body = await req.json()
    msg = body.get("message") or body.get("edited_message")
    cb  = body.get("callback_query")

    # /mode command
    if msg:
        chat_id = (msg.get("chat") or {}).get("id")
        text = (msg.get("text") or "").strip()
        if text.startswith("/mode"):
            _, _, arg = text.partition(" ")
            set_mode(arg or "dry")
            await _tg_send(chat_id, f"מצב עודכן: <b>{get_mode().upper()}</b>")
            return {"ok": True}
        if text in ("/mode", "/mode@bot"):
            await _tg_send(chat_id, f"מצב נוכחי: <b>{get_mode().upper()}</b>\nשנה באמצעות: /mode dry או /mode live")
            return {"ok": True}
        return {"ok": True}

    # Inline-approve/reject (תואם לפורמט מ-ConfirmStore)
    if cb:
        chat_id = (cb.get("message") or {}).get("chat", {}).get("id")
        data_str = cb.get("data") or ""
        try:
            _, action, cid = data_str.split(":", 2)
        except Exception:
            return {"ok": True}
        try:
            from utils.trade_executor import ConfirmStore
            approver = str((cb.get("from") or {}).get("id"))
            if action == "APPROVE":
                ConfirmStore.approve(cid, approver)
                await _tg_send(chat_id, f"✅ אושר · CID=<code>{cid}</code>")
            elif action == "REJECT":
                ConfirmStore.reject(cid, approver)
                await _tg_send(chat_id, f"❌ בוטל · CID=<code>{cid}</code>")
        except Exception as e:
            log.warning("confirm handler failed: %s", e)
        return {"ok": True}

    return {"ok": True}


