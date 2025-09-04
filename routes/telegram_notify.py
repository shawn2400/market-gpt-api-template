# routes/telegram_notify.py
from __future__ import annotations
import os, logging
from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, Body
from fastapi.responses import JSONResponse
import httpx

try:
    from utils.auth import require_api_key
    _deps = [Depends(require_api_key)]
except Exception:
    _deps = []

logger = logging.getLogger("algogpt.tg_notify")
router = APIRouter(prefix="/telegram", tags=["Telegram"], dependencies=_deps)

TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ADMIN_ID = os.getenv("ADMIN_CHAT_ID", "").strip()

@router.post("/notify")
async def notify(body: Dict[str, Any] = Body(...)):
    if not TG_TOKEN or not ADMIN_ID:
        return JSONResponse(status_code=400, content={"ok": False, "error": "missing telegram creds"})
    text = str(body.get("text","")).strip()
    chat_id = int(body.get("chat_id", ADMIN_ID))
    if not text:
        return JSONResponse(status_code=400, content={"ok": False, "error": "missing text"})
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=8.0) as cli:
            r = await cli.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"})
            r.raise_for_status()
            return {"ok": True}
    except Exception as e:
        logger.warning(f"/telegram/notify failed: {e}")
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})
