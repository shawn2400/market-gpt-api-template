# utils/telegram_api.py
from __future__ import annotations
import os, asyncio, time
from typing import Any, Dict, Optional, List, Tuple
import httpx

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
BASE  = f"https://api.telegram.org/bot{TOKEN}" if TOKEN else ""

TELEGRAM_MSG_LIMIT = 4096
DEFAULT_TIMEOUT = float(os.getenv("TELEGRAM_HTTP_TIMEOUT", "10"))
MAX_RETRIES = int(os.getenv("TELEGRAM_MAX_RETRIES", "3"))

def _chat_default(chat_id: Optional[int | str]) -> int | str:
    if chat_id is not None:
        return chat_id
    return os.getenv("ADMIN_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID") or ""

def _split_message(text: str, limit: int = TELEGRAM_MSG_LIMIT) -> List[str]:
    """מפצל הודעות ארוכות מכדי שליחה בהודעה אחת, תוך שמירת גבולות שורה."""
    if len(text) <= limit:
        return [text]
    parts: List[str] = []
    chunk = []
    current_len = 0
    for line in text.splitlines(keepends=True):
        ln = len(line)
        if current_len + ln <= limit:
            chunk.append(line)
            current_len += ln
        else:
            if chunk:
                parts.append("".join(chunk))
            # אם השורה עצמה ארוכה מהלימיט — נחתוך אותה גולמית
            while ln > limit:
                parts.append(line[:limit])
                line = line[limit:]
                ln = len(line)
            chunk = [line]
            current_len = ln
    if chunk:
        parts.append("".join(chunk))
    return parts

async def _post_json_with_retries(url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    last_err: Optional[str] = None
    backoff = 0.6
    for attempt in range(MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
                r = await client.post(url, json=payload)
                if r.status_code == 429:
                    # כיבוד Retry-After אם אפשר
                    try:
                        ra = float(r.headers.get("Retry-After", "1.0"))
                    except Exception:
                        ra = backoff
                    await asyncio.sleep(max(0.2, ra))
                    backoff = min(backoff * 1.8, 5.0)
                    continue
                if r.status_code >= 500:
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 1.8, 5.0)
                    continue
                return r.json()
        except Exception as e:
            last_err = str(e)
            if attempt >= MAX_RETRIES:
                return {"ok": False, "error": last_err or "request_failed"}
            await asyncio.sleep(backoff)
            backoff = min(backoff * 1.8, 5.0)
    return {"ok": False, "error": last_err or "request_failed"}

async def send_message(
    text: str,
    reply_markup: Optional[Dict[str, Any]] = None,
    chat_id: Optional[int | str] = None,
    silent: bool = False,
    parse_mode: str = "Markdown",
) -> Dict[str, Any]:
    if not TOKEN or not BASE:
        return {"ok": False, "error": "missing TELEGRAM_BOT_TOKEN"}
    chat = _chat_default(chat_id)
    if not chat:
        return {"ok": False, "error": "missing chat_id (ADMIN_CHAT_ID/TELEGRAM_CHAT_ID)"}

    # פיצול אוטומטי אם ארוך מדי
    parts = _split_message(text)
    last_resp: Dict[str, Any] = {}
    for idx, part in enumerate(parts):
        payload: Dict[str, Any] = {
            "chat_id": chat,
            "text": part,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
            "disable_notification": bool(silent),
        }
        if reply_markup and idx == len(parts) - 1:
            payload["reply_markup"] = reply_markup
        last_resp = await _post_json_with_retries(f"{BASE}/sendMessage", payload)
        # אם הטוקן חסר/שגוי — אין טעם להמשיך
        if not last_resp.get("ok") and "error" in last_resp:
            return last_resp
    # מחזירים את תגובת החלק האחרון (שכולל גם את הכפתורים אם היו)
    if len(parts) > 1:
        last_resp["parts_sent"] = len(parts)
    return last_resp

async def edit_message(
    chat_id: int | str,
    message_id: int,
    text: str,
    reply_markup: Optional[Dict[str, Any]] = None,
    parse_mode: str = "Markdown",
) -> Dict[str, Any]:
    if not TOKEN or not BASE:
        return {"ok": False, "error": "missing TELEGRAM_BOT_TOKEN"}

    # אם הטקסט ארוך מדי לעריכה — נשלח הודעה חדשה במקום (פול בק)
    if len(text) > TELEGRAM_MSG_LIMIT:
        return await send_message(text, reply_markup=reply_markup, chat_id=chat_id, silent=False, parse_mode=parse_mode)

    payload: Dict[str, Any] = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return await _post_json_with_retries(f"{BASE}/editMessageText", payload)

async def get_me() -> Dict[str, Any]:
    if not TOKEN or not BASE:
        return {"ok": False, "error": "missing TELEGRAM_BOT_TOKEN"}
    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            r = await client.get(f"{BASE}/getMe")
            return r.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}

async def send_chat_action(action: str = "typing", chat_id: Optional[int | str] = None) -> Dict[str, Any]:
    if not TOKEN or not BASE:
        return {"ok": False, "error": "missing TELEGRAM_BOT_TOKEN"}
    payload = {"chat_id": _chat_default(chat_id), "action": action}
    return await _post_json_with_retries(f"{BASE}/sendChatAction", payload)





