# utils/telegram_notifier.py
from __future__ import annotations

import os
import json
import logging
from typing import Dict, Any

import httpx

logger = logging.getLogger("algogpt.telegram_notifier")

TEMPLATE_PATH = "static/telegram_ui_templates.json"
TG_API_URL = f"https://api.telegram.org/bot{os.getenv('TELEGRAM_BOT_TOKEN', '').strip()}"
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
TELEGRAM_ENABLED = bool(os.getenv("TELEGRAM_ADMIN_ONLY", "1").strip() in ("1", "true", "yes", "on")) and ADMIN_CHAT_ID

_templates: Dict[str, str] = {}

# ===================== LOAD TEMPLATES =====================
def load_templates() -> None:
    global _templates
    try:
        with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
            _templates = json.load(f)
            logger.info("[telegram_notifier] loaded %d templates", len(_templates))
    except Exception as e:
        logger.warning("[telegram_notifier] failed to load templates: %s", e)
        _templates = {}

load_templates()

# ===================== FORMATTER =====================
def render_template(name: str, data: Dict[str, Any]) -> str:
    tmpl = _templates.get(name)
    if not tmpl:
        logger.warning("[telegram_notifier] missing template: %s", name)
        return ""
    try:
        return tmpl.format(**data)
    except Exception as e:
        logger.warning("[telegram_notifier] failed to format %s: %s", name, e)
        return tmpl

# ===================== TELEGRAM SEND =====================
async def send_admin_message(text: str, parse_mode: str = "Markdown") -> None:
    if not TELEGRAM_ENABLED or not ADMIN_CHAT_ID or not TG_API_URL:
        return
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            payload = {
                "chat_id": ADMIN_CHAT_ID,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            }
            r = await client.post(f"{TG_API_URL}/sendMessage", json=payload)
            if r.status_code != 200:
                logger.warning("[telegram_notifier] failed to send: %s", r.text)
    except Exception as e:
        logger.warning("[telegram_notifier] exception during send: %s", e)

# ===================== EXPORTS =====================
__all__ = [
    "render_template",
    "send_admin_message",
]
