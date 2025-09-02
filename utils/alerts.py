# utils/alerts.py
from __future__ import annotations
import os
import asyncio
from typing import Optional, Dict, Any
import logging

import httpx

logger = logging.getLogger("algogpt.alerts")

TELEGRAM_BOT_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
ADMIN_CHAT_ID = (os.getenv("ADMIN_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID") or "").strip()

_TG_REC   = (os.getenv("TG_NOTIFY_RECONCILE","1").strip().lower() in ("1","true","yes","on"))
_TG_GRID  = (os.getenv("TG_NOTIFY_GRID","1").strip().lower() in ("1","true","yes","on"))
_TG_MNGR  = (os.getenv("TG_NOTIFY_MANAGER","0").strip().lower() in ("1","true","yes","on"))

DEFAULT_TIMEOUT = float(os.getenv("TELEGRAM_HTTP_TIMEOUT", "10"))
MAX_RETRIES = int(os.getenv("TELEGRAM_MAX_RETRIES", "3"))
TELEGRAM_MSG_LIMIT = 4096

def _api_base() -> str:
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")
    return f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

def _ensure_chat_id() -> str:
    if not ADMIN_CHAT_ID:
        raise RuntimeError("ADMIN_CHAT_ID/TELEGRAM_CHAT_ID is not set")
    return ADMIN_CHAT_ID

async def _post_json_with_retries(method: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    url = f"{_api_base()}/{method}"
    last_err: Optional[str] = None
    backoff = 0.6
    for attempt in range(MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
                r = await client.post(url, json=payload)
                if r.status_code == 429:
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
                try:
                    js = r.json()
                except Exception:
                    js = {"ok": False, "status_code": r.status_code, "text": r.text}
                if not js.get("ok", False):
                    logger.warning({"event": "tg_api_error", "method": method, "status": r.status_code, "resp": js})
                return js
        except Exception as e:
            last_err = str(e)
            if attempt >= MAX_RETRIES:
                return {"ok": False, "error": last_err or "request_failed"}
            await asyncio.sleep(backoff)
            backoff = min(backoff * 1.8, 5.0)
    return {"ok": False, "error": last_err or "request_failed"}

async def telegram_get_me() -> Dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            r = await client.get(f"{_api_base()}/getMe")
            try:
                return r.json()
            except Exception:
                return {"ok": False, "status_code": r.status_code, "text": r.text}
    except Exception as e:
        return {"ok": False, "error": str(e)}

async def telegram_send_chat_action(action: str = "typing") -> Dict[str, Any]:
    chat_id = _ensure_chat_id()
    return await _post_json_with_retries("sendChatAction", {"chat_id": chat_id, "action": action})

def _coerce_side(side: str) -> str:
    s = (side or "").strip().upper()
    if s in ("LONG", "BUY"):
        return "LONG"
    if s in ("SHORT", "SELL"):
        return "SHORT"
    return s or "LONG"

def format_trade_alert(
    symbol: str,
    side: str,
    entry: float,
    sl: float,
    tp1: float,
    tp2: float,
    size_usd: float = 50.0,
    *,
    note: str = "",
    quality: Optional[float] = None,
    success_pct: Optional[float] = None,
) -> str:
    sym = (symbol or "").upper().strip()
    side_n = _coerce_side(side)
    q_str = f"\n• Quality: *{quality:.2f}*/10" if isinstance(quality, (int, float)) else ""
    s_str = f"\n• Success Rate: *{success_pct:.1f}%*" if isinstance(success_pct, (int, float)) else ""
    n_str = f"\n• Note: _{note}_" if note else ""
    txt = (
        "🔔 *AlgoGPT – Trade Alert*\n"
        f"*{sym}* • *{side_n}*\n"
        f"• Entry: `{entry:.6f}`\n"
        f"• SL: `{sl:.6f}`\n"
        f"• TP1: `{tp1:.6f}`\n"
        f"• TP2: `{tp2:.6f}`\n"
        f"• Size ≈ ${size_usd:.2f}"
        f"{q_str}{s_str}{n_str}"
    )
    # חיתוך עדין אם עברנו את מגבלת טלגרם (ליתר ביטחון)
    if len(txt) > TELEGRAM_MSG_LIMIT:
        txt = txt[:TELEGRAM_MSG_LIMIT - 3] + "..."
    return txt

async def send_telegram_alert(
    message: str,
    parse_mode: str = "Markdown",
    disable_preview: bool = True,
) -> Dict[str, Any]:
    chat_id = _ensure_chat_id()
    # פיצול אם ארוך מדי
    def _split(text: str) -> list[str]:
        if len(text) <= TELEGRAM_MSG_LIMIT:
            return [text]
        out: list[str] = []
        start = 0
        while start < len(text):
            out.append(message[start:start + TELEGRAM_MSG_LIMIT])
            start += TELEGRAM_MSG_LIMIT
        return out

    parts = _split(message)
    last: Dict[str, Any] = {}
    for idx, part in enumerate(parts):
        data = {
            "chat_id": chat_id,
            "text": part,
            "parse_mode": parse_mode,
            "disable_web_page_preview": bool(disable_preview),
            "disable_notification": False,
        }
        last = await _post_json_with_retries("sendMessage", data)
        if not last.get("ok") and "error" in last:
            return last
    if len(parts) > 1:
        last["parts_sent"] = len(parts)
    return last

def _fire_and_forget(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(coro)
    except Exception:
        pass

def tg_info(text: str) -> None:
    _fire_and_forget(send_telegram_alert(f"ℹ️ {text}"))

def tg_warn(text: str) -> None:
    _fire_and_forget(send_telegram_alert(f"⚠️ {text}"))

def tg_ok(text: str) -> None:
    _fire_and_forget(send_telegram_alert(f"✅ {text}"))

def tg_err(text: str) -> None:
    _fire_and_forget(send_telegram_alert(f"❌ {text}"))

def tg_rec(text: str) -> None:
    if _TG_REC:
        _fire_and_forget(send_telegram_alert(text))

def tg_grid(text: str) -> None:
    if _TG_GRID:
        _fire_and_forget(send_telegram_alert(text))

def tg_mngr(text: str) -> None:
    if _TG_MNGR:
        _fire_and_forget(send_telegram_alert(text))




