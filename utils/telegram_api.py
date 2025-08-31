# utils/telegram_api.py
from __future__ import annotations

import os
import json
import logging
from typing import Optional, Dict, Any

import httpx

from utils.hmac_utils import build_signed_outbound

LOGGER = logging.getLogger("utils.telegram_api")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())

# --- Env / Config ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
DEFAULT_CHAT_ID = (os.getenv("TELEGRAM_CHAT_ID", "") or os.getenv("ADMIN_CHAT_ID", "")).strip()

TIMEOUT = float(os.getenv("TELEGRAM_HTTP_TIMEOUT", "15"))

# Optional: route via /alerts/analysis (HMAC) instead of direct Telegram API
USE_SINK = os.getenv("TELEGRAM_VIA_SINK", "0").lower() in ("1", "true", "yes")
ALERTS_ANALYSIS_URL = os.getenv("ALERTS_ANALYSIS_URL", "http://127.0.0.1:8000/alerts/analysis").strip()
WEBHOOK_HMAC_SECRET = os.getenv("WEBHOOK_HMAC_SECRET", "").strip()

# --- Helpers ---
def _tg_api_url(method: str) -> str:
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")
    return f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"

def _resolve_chat_id(chat_id: Optional[int | str]) -> int | str:
    if chat_id is not None:
        return chat_id
    if DEFAULT_CHAT_ID:
        return DEFAULT_CHAT_ID
    raise RuntimeError("chat_id is required (DEFAULT_CHAT_ID/ADMIN_CHAT_ID not set)")

# --- Public API ---

async def send_message(
    text: str,
    reply_markup: Optional[Dict[str, Any]] = None,
    chat_id: Optional[int | str] = None,
    reply_to_message_id: Optional[int] = None,
    silent: bool = False,
    parse_mode: Optional[str] = "Markdown",
    disable_web_page_preview: bool = True,
) -> Dict[str, Any]:
    """
    Sends a Telegram message. Two modes:
      1) Via /alerts/analysis (HMAC) when TELEGRAM_VIA_SINK=1 and WEBHOOK_HMAC_SECRET is set.
      2) Directly to Telegram Bot API (default).
    """
    cid = _resolve_chat_id(chat_id)

    # Try sink mode first (if enabled)
    if USE_SINK and WEBHOOK_HMAC_SECRET and ALERTS_ANALYSIS_URL:
        payload = {
            "chat_id": cid,
            "text": text,
            "reply_to_message_id": reply_to_message_id,
            "silent": bool(silent),
            "reply_markup": reply_markup or None,
        }
        body, headers = build_signed_outbound(
            WEBHOOK_HMAC_SECRET,
            payload,
            extra_headers={"Content-Type": "application/json"},
        )
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.post(ALERTS_ANALYSIS_URL, content=body, headers=headers)
            try:
                r.raise_for_status()
                return r.json() if r.headers.get("content-type","").startswith("application/json") else {"ok": True, "via": "sink"}
            except httpx.HTTPStatusError as e:
                LOGGER.warning("sink send failed (%s), falling back to Telegram API", e.response.status_code)

    # Fallback / default: direct Telegram API
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured (and sink mode is unavailable).")

    body = {
        "chat_id": cid,
        "text": text,
        "disable_web_page_preview": bool(disable_web_page_preview),
    }
    if parse_mode:
        body["parse_mode"] = parse_mode
    if reply_markup:
        body["reply_markup"] = reply_markup
    if reply_to_message_id:
        body["reply_to_message_id"] = reply_to_message_id
    if silent:
        body["disable_notification"] = True

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.post(_tg_api_url("sendMessage"), json=body)
        r.raise_for_status()
        return r.json()

async def edit_message(
    chat_id: int | str,
    message_id: int,
    text: str,
    reply_markup: Optional[Dict[str, Any]] = None,
    parse_mode: Optional[str] = "Markdown",
    disable_web_page_preview: bool = True,
) -> Dict[str, Any]:
    """
    Edits an existing message — always uses Telegram Bot API directly
    (the sink endpoint does not implement edit).
    """
    cid = _resolve_chat_id(chat_id)
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")

    body = {
        "chat_id": cid,
        "message_id": int(message_id),
        "text": text,
        "disable_web_page_preview": bool(disable_web_page_preview),
    }
    if parse_mode:
        body["parse_mode"] = parse_mode
    if reply_markup:
        body["reply_markup"] = reply_markup

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.post(_tg_api_url("editMessageText"), json=body)
        r.raise_for_status()
        return r.json()

async def delete_message(
    chat_id: int | str,
    message_id: int,
) -> Dict[str, Any]:
    """
    Optional helper to delete messages.
    """
    cid = _resolve_chat_id(chat_id)
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")

    body = {"chat_id": cid, "message_id": int(message_id)}
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.post(_tg_api_url("deleteMessage"), json=body)
        r.raise_for_status()
        return r.json()

