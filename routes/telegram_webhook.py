# routes/telegram_webhook.py
from __future__ import annotations
from fastapi import APIRouter, Request, HTTPException, Depends
from utils.auth import require_api_key
from utils.telegram_api import edit_message
import os, httpx, hmac, hashlib, json

router = APIRouter(prefix="/telegram", tags=["Telegram"], dependencies=[Depends(require_api_key)])

OUT_URL = os.getenv("OUTGOING_WEBHOOK_URL", "").strip()
OUT_TOK = os.getenv("OUTGOING_WEBHOOK_TOKEN", "").strip()  # לשימוש אם תרצה גם token בסיסי
OUT_HMAC_SECRET = os.getenv("OUTGOING_HMAC_SECRET", os.getenv("HMAC_SECRET", "")).encode()

def _sign(body: bytes) -> str:
    if not OUT_HMAC_SECRET:
        return ""
    return hmac.new(OUT_HMAC_SECRET, body, hashlib.sha256).hexdigest()

async def _notify_core(trade_id: str, decision: str, meta: dict):
    if not OUT_URL:
        return {"ok": True, "sent": False}
    payload = {"trade_id": trade_id, "decision": decision, "meta": meta}
    body = json.dumps(payload, separators=(",", ":")).encode()
    sig = _sign(body)
    headers = {
        "Content-Type": "application/json",
        "X-Idempotency-Key": trade_id,  # אידמפוטנסי בצד ה-Core
    }
    if OUT_TOK:
        headers["Authorization"] = f"Bearer {OUT_TOK}"
    if sig:
        headers["X-Signature"] = sig

    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(OUT_URL, content=body, headers=headers)
        return {"ok": (200 <= r.status_code < 300), "status": r.status_code, "body": r.text}


