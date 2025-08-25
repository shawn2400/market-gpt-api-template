# utils/alerts.py
from __future__ import annotations
import os, asyncio, re
import httpx
from typing import Optional, Dict, Any

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

def _escape_md(text: str) -> str:
    # הגנה בסיסית ל-parse_mode=Markdown
    return re.sub(r'([_*[\]()~`>#+\-=|{}.!])', r'\\\1', str(text))

async def _tg_post(method: str, json: Dict[str, Any], timeout: float = 10.0) -> Dict[str, Any]:
    if not TELEGRAM_BOT_TOKEN:
        return {"ok": False, "error": "TELEGRAM_BOT_TOKEN missing"}
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"
    async with httpx.AsyncClient(timeout=timeout) as client:
        # רטריז קל נגד שיבושי רשת
        last_err: Optional[Exception] = None
        for _ in range(3):
            try:
                r = await client.post(url, json=json)
                r.raise_for_status()
                obj = r.json()
                return obj if isinstance(obj, dict) else {"ok": False, "error": "bad json"}
            except Exception as e:
                last_err = e
                await asyncio.sleep(0.6)
        return {"ok": False, "error": str(last_err)}

async def telegram_get_me() -> Dict[str, Any]:
    if not TELEGRAM_BOT_TOKEN:
        return {"ok": False, "error": "TELEGRAM_BOT_TOKEN missing"}
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getMe"
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            r = await client.get(url)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            return {"ok": False, "error": str(e)}

async def telegram_send_chat_action(action: str = "typing") -> Dict[str, Any]:
    if not TELEGRAM_CHAT_ID:
        return {"ok": False, "error": "TELEGRAM_CHAT_ID missing"}
    return await _tg_post("sendChatAction", {"chat_id": TELEGRAM_CHAT_ID, "action": action})

async def send_telegram_alert(
    message: str,
    parse_mode: str = "Markdown",
    disable_web_page_preview: bool = True,
) -> Dict[str, Any]:
    if not TELEGRAM_CHAT_ID:
        return {"ok": False, "error": "TELEGRAM_CHAT_ID missing"}

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": _escape_md(message) if parse_mode == "Markdown" else str(message),
        "parse_mode": parse_mode,
        "disable_web_page_preview": disable_web_page_preview,
    }

    # ניסיון ראשון ב-Markdown; אם נכשל עם 400, ננסה בלי parse_mode
    resp = await _tg_post("sendMessage", payload)
    if not resp.get("ok") and "Bad Request" in str(resp.get("error", "")):
        payload.pop("parse_mode", None)
        resp = await _tg_post("sendMessage", payload)
    return resp

def format_trade_alert(
    symbol: str, side: str, entry: float, sl: float, tp1: float, tp2: float,
    size_usd: float, note: str = "", quality: Optional[float] = None, success_pct: Optional[float] = None
) -> str:
    # פורמט “קצר” לפי ה-SOP שלך
    parts = [
        "קצר",
        f"{'כניסה' if side.upper()=='LONG' else 'Short'}",
        side.upper(),
        f"{entry:.4f}",
        f"SL {sl:.4f}",
        f"TP1 {tp1:.4f}/TP2 {tp2:.4f}",
        f"${size_usd:.0f}",
        (note or "אימות 5m/15m"),
    ]
    head = " | ".join(parts)
    tail = ""
    if quality is not None or success_pct is not None:
        tail = f"\nQuality: {quality:.2f} | Success: {success_pct:.1f}%" if (quality is not None and success_pct is not None) else \
               f"\nQuality: {quality:.2f}" if quality is not None else f"\nSuccess: {success_pct:.1f}%"
    return f"{head}{tail}"
