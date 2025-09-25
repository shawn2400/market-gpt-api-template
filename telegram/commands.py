# telegram/commands.py
from __future__ import annotations
import os, httpx, logging

log = logging.getLogger("algogpt.tg")

TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
CHAT  = int(os.getenv("TELEGRAM_CHAT_ID", "0") or "0")

async def send_message(text: str) -> None:
    if not TOKEN or not CHAT:
        log.info({"event":"tg_skip", "reason":"no_token_or_chat"})
        return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    timeout = httpx.Timeout(10.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as cli:
        await cli.post(url, data=payload)


