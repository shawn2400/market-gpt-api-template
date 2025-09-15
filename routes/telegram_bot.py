# routes/telegram_bot.py
from __future__ import annotations
import os, logging
from typing import Optional, Dict, Any

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, ConfigDict

logger = logging.getLogger("algogpt.routes.telegram_bot")

# שים לב: אין כאן Depends(require_api_key). ההגנה מתבצעת ע"י ה-middleware הגלובלי ב-main.py.
router = APIRouter(
    prefix="/telegram",
    tags=["Telegram"],
)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
API_BASE  = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else ""
DEFAULT_CHAT = os.getenv("TELEGRAM_TEST_CHAT_ID", "").strip()
PM_ENV = (os.getenv("TELEGRAM_PARSE_MODE", "").strip() or None)  # None => לא שולחים parse_mode

PUBLIC_HOST = os.getenv("PUBLIC_HOST", "").strip()
WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()

class SendRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    chat_id: Optional[int] = Field(None, description="אם לא — יילקח מ־TELEGRAM_TEST_CHAT_ID")
    text: str = Field(..., min_length=1, max_length=4096)
    parse_mode: Optional[str] = Field(None, description="HTML / MarkdownV2 (אם לא נשלח — יילקח מה-ENV אם קיים)")
    disable_preview: bool = Field(True, description="השבתת תצוגה מקדימה")

@router.get("/health")
async def health() -> Dict[str, Any]:
    if not BOT_TOKEN:
        return {"ok": False, "error": "BOT_TOKEN missing"}
    try:
        async with httpx.AsyncClient(timeout=8.0) as cli:
            me = await cli.get(f"{API_BASE}/getMe")
            wh = await cli.get(f"{API_BASE}/getWebhookInfo")
        me_json = me.json() if "application/json" in me.headers.get("content-type","") else {}
        wh_json = wh.json() if "application/json" in wh.headers.get("content-type","") else {}
        return {"ok": True, "bot": me_json.get("result", {}), "webhook": wh_json.get("result", {})}
    except Exception as e:
        logger.warning("telegram/health failed: %s", e)
        return {"ok": False, "error": str(e)}

@router.get("/test-ping")
async def test_ping(chat_id: Optional[int] = Query(None)) -> Dict[str, Any]:
    if not BOT_TOKEN:
        raise HTTPException(500, "BOT_TOKEN missing")
    cid = chat_id or (int(DEFAULT_CHAT) if DEFAULT_CHAT.isdigit() else None)
    if not cid:
        raise HTTPException(400, "chat_id required (or set TELEGRAM_TEST_CHAT_ID)")
    payload: Dict[str, Any] = {
        "chat_id": cid,
        "text": "pong ✅ (test-ping)",
        "disable_web_page_preview": True,
    }
    if PM_ENV:
        payload["parse_mode"] = PM_ENV
    try:
        async with httpx.AsyncClient(timeout=8.0) as cli:
            r = await cli.post(f"{API_BASE}/sendMessage", json=payload)
        j = r.json() if "application/json" in r.headers.get("content-type","") else {"ok": False, "raw": r.text}
        return {"ok": bool(j.get("ok")), "result": j}
    except Exception as e:
        logger.error("telegram/test-ping failed: %s", e)
        raise HTTPException(502, str(e))

@router.post("/send")
async def send(req: SendRequest) -> Dict[str, Any]:
    if not BOT_TOKEN:
        raise HTTPException(500, "BOT_TOKEN missing")
    cid = req.chat_id or (int(DEFAULT_CHAT) if DEFAULT_CHAT.isdigit() else None)
    if not cid:
        raise HTTPException(400, "chat_id required (or set TELEGRAM_TEST_CHAT_ID)")

    payload: Dict[str, Any] = {
        "chat_id": cid,
        "text": req.text,
        "disable_web_page_preview": bool(req.disable_preview),
    }
    pm_effective = req.parse_mode if req.parse_mode is not None else PM_ENV
    if pm_effective:
        payload["parse_mode"] = pm_effective

    try:
        async with httpx.AsyncClient(timeout=8.0) as cli:
            r = await cli.post(f"{API_BASE}/sendMessage", json=payload)
        j = r.json() if "application/json" in r.headers.get("content-type","") else {"ok": False, "raw": r.text}
        return {"ok": bool(j.get("ok")), "result": j}
    except Exception as e:
        logger.error("telegram/send failed: %s", e)
        raise HTTPException(502, str(e))

@router.get("/set-webhook")
async def set_webhook() -> Dict[str, Any]:
    if not BOT_TOKEN:
        raise HTTPException(500, "BOT_TOKEN missing")
    if not PUBLIC_HOST:
        raise HTTPException(500, "PUBLIC_HOST missing")
    url = f"{PUBLIC_HOST}/telegram/webhook"
    payload: Dict[str, Any] = {
        "url": url,
        "drop_pending_updates": True,
        "max_connections": 40,
    }
    if WEBHOOK_SECRET:
        payload["secret_token"] = WEBHOOK_SECRET
    try:
        async with httpx.AsyncClient(timeout=10.0) as cli:
            r = await cli.post(f"{API_BASE}/setWebhook", json=payload)
        j = r.json() if "application/json" in r.headers.get("content-type","") else {"ok": False, "raw": r.text}
        ok = bool(j.get("ok"))
        return {"ok": ok, "telegram_response": j, "webhook_url": url}
    except Exception as e:
        logger.error("telegram/set-webhook failed: %s", e)
        raise HTTPException(502, str(e))






























