# telegram/commands.py
from __future__ import annotations
import os, asyncio, httpx, logging
from typing import Dict, Any, Optional
from utils.mode_store import ExecMode

log = logging.getLogger("algogpt.telegram.commands")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
API_BASE  = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else ""
ADMIN_USER_ID = os.getenv("TELEGRAM_ADMIN_ID", "").strip()  # אופציונלי להגבלת פקודות

async def send_message(chat_id: int, text: str, parse_mode: Optional[str] = None) -> None:
    if not BOT_TOKEN:
        log.warning("send_message: BOT_TOKEN missing")
        return
    payload: Dict[str, Any] = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
    if parse_mode: payload["parse_mode"] = parse_mode
    try:
        async with httpx.AsyncClient(timeout=10.0) as cli:
            await cli.post(f"{API_BASE}/sendMessage", json=payload)
    except Exception as e:
        log.warning("send_message failed: %s", e)

async def _handle_command(chat_id: int, from_id: Optional[int], text: str) -> None:
    cmd = (text or "").strip()
    if not cmd:
        return

    # (אופציונלי) הגבלה למנהל
    if ADMIN_USER_ID and (str(from_id or "") != str(ADMIN_USER_ID)):
        await send_message(chat_id, "אין הרשאה לפקודות ניהול.", None)
        return

    if cmd.startswith("/mode"):
        _, _, arg = cmd.partition(" ")
        new_mode = "live" if arg.lower().strip() == "live" else "dry"
        ExecMode.set(new_mode)
        await send_message(chat_id, f"מצב עודכן: <b>{new_mode.upper()}</b>", "HTML")
        return

    if cmd in ("/mode@thisbot", "/mode"):
        await send_message(chat_id, f"מצב נוכחי: <b>{ExecMode.get().upper()}</b>\nשנה באמצעות: /mode dry או /mode live", "HTML")
        return

    # פקודות נוספות… (לדוגמה /ping)
    if cmd.startswith("/ping"):
        await send_message(chat_id, "pong ✅", None)
        return

async def poll_bot_commands(offset: Optional[int] = None, poll_interval_sec: float = 1.5) -> None:
    """
    פולינג פשוט לעדכוני טלגרם. מריץ בלולאה (להפעיל כ-Task ברקע).
    """
    if not BOT_TOKEN:
        log.warning("poll_bot_commands: BOT_TOKEN missing; skipping.")
        return

    last_update_id: Optional[int] = offset
    while True:
        try:
            params = {"timeout": 10}
            if last_update_id is not None:
                params["offset"] = last_update_id + 1

            async with httpx.AsyncClient(timeout=15.0) as cli:
                r = await cli.get(f"{API_BASE}/getUpdates", params=params)
                data = r.json() if r.headers.get("content-type","").startswith("application/json") else {}
                if not data.get("ok"):
                    await asyncio.sleep(poll_interval_sec)
                    continue

                for upd in data.get("result", []):
                    last_update_id = int(upd["update_id"])
                    msg = upd.get("message") or upd.get("edited_message") or {}
                    text = msg.get("text") or ""
                    chat = msg.get("chat") or {}
                    chat_id = chat.get("id")
                    from_user = msg.get("from") or {}
                    from_id = from_user.get("id")

                    if isinstance(chat_id, int) and isinstance(text, str):
                        if text.startswith("/"):
                            await _handle_command(chat_id, from_id, text)
        except Exception as e:
            log.warning("poll_bot_commands error: %s", e)
        finally:
            await asyncio.sleep(poll_interval_sec)
