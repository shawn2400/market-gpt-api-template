# routes/telegram_bot.py
from __future__ import annotations
import os, logging
from typing import Optional, Dict, Any, List

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, ConfigDict

from utils.auth import require_api_key

logger = logging.getLogger("algogpt.routes.telegram_bot")

router = APIRouter(
    prefix="/telegram",
    tags=["Telegram"],
    dependencies=[Depends(require_api_key)],  # שליחת הודעות—מוגן בטוקן
)

# ── ENV
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
API_BASE  = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else ""
DEFAULT_CHAT = os.getenv("TELEGRAM_TEST_CHAT_ID", "").strip()

# ── Models
class SendRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    chat_id: Optional[int] = Field(None, description="אם לא יימסר—יילקח מ־TELEGRAM_TEST_CHAT_ID")
    text: str = Field(..., min_length=1, max_length=4096)
    parse_mode: Optional[str] = Field(None, description="HTML / MarkdownV2")
    disable_preview: bool = Field(True, description="השבתת תצוגה מקדימה של קישורים")

# ── Endpoints
@router.get("/health")
async def health() -> Dict[str, Any]:
    """בדיקת בריאות: token, getMe, webhook."""
    if not BOT_TOKEN:
        return {"ok": False, "error": "BOT_TOKEN missing"}
    try:
        async with httpx.AsyncClient(timeout=8.0) as cli:
            me = await cli.get(f"{API_BASE}/getMe")
            wh = await cli.get(f"{API_BASE}/getWebhookInfo")
        return {
            "ok": True,
            "bot": (me.json().get("result", {}) if me.headers.get("content-type","").startswith("application/json") else {}),
            "webhook": (wh.json().get("result", {}) if wh.headers.get("content-type","").startswith("application/json") else {}),
        }
    except Exception as e:
        logger.warning("telegram/health failed: %s", e)
        return {"ok": False, "error": str(e)}

@router.get("/test-ping")
async def test_ping(chat_id: Optional[int] = Query(None)) -> Dict[str, Any]:
    """
    שולח הודעת pong ✅ לצ'אט נתון. אם chat_id לא סופק, ננסה מה־ENV (TELEGRAM_TEST_CHAT_ID).
    """
    if not BOT_TOKEN:
        raise HTTPException(500, "BOT_TOKEN missing")
    cid = chat_id or (int(DEFAULT_CHAT) if DEFAULT_CHAT.isdigit() else None)
    if not cid:
        raise HTTPException(400, "chat_id required (or set TELEGRAM_TEST_CHAT_ID)")
    try:
        async with httpx.AsyncClient(timeout=8.0) as cli:
            r = await cli.post(f"{API_BASE}/sendMessage", data={
                "chat_id": cid,
                "text": "pong ✅ (test-ping)",
                "disable_web_page_preview": True,
            })
        j = r.json() if "application/json" in r.headers.get("content-type","") else {"ok": False, "raw": r.text}
        return {"ok": bool(j.get("ok")), "result": j}
    except Exception as e:
        logger.error("telegram/test-ping failed: %s", e)
        raise HTTPException(502, str(e))

@router.post("/send")
async def send(req: SendRequest) -> Dict[str, Any]:
    """שליחת הודעה גנרית—מאובטח ע"י API key."""
    if not BOT_TOKEN:
        raise HTTPException(500, "BOT_TOKEN missing")
    cid = req.chat_id or (int(DEFAULT_CHAT) if DEFAULT_CHAT.isdigit() else None)
    if not cid:
        raise HTTPException(400, "chat_id required (or set TELEGRAM_TEST_CHAT_ID)")
    payload = {
        "chat_id": cid,
        "text": req.text,
        "disable_web_page_preview": "true" if req.disable_preview else "false",
    }
    if req.parse_mode:
        payload["parse_mode"] = req.parse_mode
    try:
        async with httpx.AsyncClient(timeout=8.0) as cli:
            r = await cli.post(f"{API_BASE}/sendMessage", data=payload)
        j = r.json() if "application/json" in r.headers.get("content-type","") else {"ok": False, "raw": r.text}
        return {"ok": bool(j.get("ok")), "result": j}
    except Exception as e:
        logger.error("telegram/send failed: %s", e)
        raise HTTPException(502, str(e))



























