# routes/telegram_webhook.py
from __future__ import annotations
import os, logging, hmac, hashlib, time
from typing import Any, Dict

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
import httpx

logger = logging.getLogger("algogpt.telegram.webhook")
router = APIRouter(prefix="/telegram", tags=["Telegram"])

TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ADMIN_ONLY = str(os.getenv("TELEGRAM_ADMIN_ONLY", "1")).lower() in ("1","true","yes","on")
ADMIN_IDS = {s.strip() for s in (os.getenv("TELEGRAM_ADMIN_IDS","") or "").split(",") if s.strip()}
BOT_NAME = os.getenv("TELEGRAM_BOT_NAME", "AlgoGPT")

# קלות גישה: בלי סיסמה/קוד — בדיפולט רק למנהלים (ADMIN_IDS). לשחרור: TELEGRAM_ADMIN_ONLY=0
def _allowed_user(uid: int) -> bool:
    if not ADMIN_ONLY:
        return True
    return str(uid) in ADMIN_IDS

async def _reply(chat_id: int, text: str):
    if not TG_TOKEN:
        return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown", "disable_web_page_preview": True}
    try:
        async with httpx.AsyncClient(timeout=8.0) as cli:
            await cli.post(url, json=payload)
    except Exception as e:
        logger.warning(f"[tg] sendMessage failed: {e}")

# כפתורי Reply — נשלחים לפי צורך
async def _reply_with_keyboard(chat_id: int, text: str, buttons: list[list[str]]):
    if not TG_TOKEN:
        return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id, "text": text, "parse_mode": "Markdown",
        "reply_markup": {"keyboard": buttons, "resize_keyboard": True, "one_time_keyboard": False},
    }
    try:
        async with httpx.AsyncClient(timeout=8.0) as cli:
            await cli.post(url, json=payload)
    except Exception as e:
        logger.warning(f"[tg] sendMessage(kbd) failed: {e}")

# פקודות נתמכות (דו־לשוני)
HELP_TEXT = (
    "🤖 *AlgoGPT Bot* — תפריט עזרה\n\n"
    "• /help — עזרה\n"
    "• /status — סטטוס סריקה/אקזקיוטר\n"
    "• /mute — השתקת התראות\n"
    "• /unmute — ביטול השתקה\n"
    "• /scan <SYMBOL> <15m|1h|4h> — סריקה מהירה\n"
    "• /exec_dry <SYMBOL> <BUY|SELL> <QTY> <ENTRY> <SL> <TP> <LEV>\n"
    "• /approve <TRADE_ID> — אישור טרייד ממתין\n"
    "• /positions — פוזיציות פתוחות\n"
    "• /pnl — תקציר PnL\n"
    "• /system — עומסים וניטור\n"
)

async def _api_get(path: str, token: str | None = None) -> Dict[str, Any]:
    url = path if path.startswith("http") else f"http://127.0.0.1:8000{path}"
    headers = {}
    if token := (token or os.getenv("API_BEARER_TOKEN","").strip()):
        headers["Authorization"] = f"Bearer {token}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as cli:
            r = await cli.get(url, headers=headers)
            r.raise_for_status()
            return r.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}

async def _api_post(path: str, body: Dict[str, Any], token: str | None = None) -> Dict[str, Any]:
    url = path if path.startswith("http") else f"http://127.0.0.1:8000{path}"
    headers = {"Content-Type":"application/json"}
    if token := (token or os.getenv("API_BEARER_TOKEN","").strip()):
        headers["Authorization"] = f"Bearer {token}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as cli:
            r = await cli.post(url, json=body, headers=headers)
            r.raise_for_status()
            return r.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}

@router.post("/webhook")
async def webhook(req: Request):
    if not TG_TOKEN:
        raise HTTPException(status_code=400, detail="Missing TELEGRAM_BOT_TOKEN")
    try:
        update = await req.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Bad payload")

    msg = update.get("message") or update.get("edited_message") or {}
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    from_user = msg.get("from") or {}
    uid = int(from_user.get("id") or 0)
    text = (msg.get("text") or "").strip()

    logger.info({"event":"tg_in","uid":uid,"chat":chat_id,"text":text})
    if not chat_id or not uid:
        return {"ok": True}

    if not _allowed_user(uid):
        await _reply(chat_id, "⛔️ אין לך הרשאה להשתמש בבוט זה.")
        return {"ok": True}

    # כפתורי הנחיה מהירה
    home_buttons = [
        ["/status", "/positions", "/pnl"],
        ["/scan BTCUSDT 15m", "/scan ETHUSDT 1h"],
        ["/system", "/help"]
    ]

    if not text or text in ("/start", "/help"):
        await _reply_with_keyboard(chat_id, HELP_TEXT, home_buttons)
        return {"ok": True}

    parts = text.split()
    cmd = parts[0].lower()

    if cmd == "/status":
        s1 = await _api_get("/executor/status")
        s2 = await _api_get("/system/autopilot/status")
        ok = s1.get("ok") and (s2.get("ok", True))
        await _reply(chat_id, f"📊 *Status*\nexecutor: `{s1}`\nautopilot: `{s2}`")
        return {"ok": True}

    if cmd in ("/mute", "/unmute"):
        try:
            # routes/telegram_bot.py
            target = "/telegram/mute" if cmd == "/mute" else "/telegram/toggle"
            body = {"state": True} if cmd == "/mute" else {}
            res = await _api_post(target, body)
            await _reply(chat_id, f"🔔 Mute state: `{res}`")
        except Exception as e:
            await _reply(chat_id, f"❌ mute/unmute failed: {e}")
        return {"ok": True}

    if cmd == "/scan":
        if len(parts) < 2:
            await _reply(chat_id, "שימוש: /scan SYMBOL [15m|1h|4h]")
            return {"ok": True}
        symbol = parts[1].upper()
        interval = parts[2] if len(parts) > 2 else "15m"
        res = await _api_get(f"/ai/analyze?symbol={symbol}&interval={interval}")
        text = res.get("analysis") or str(res)
        await _reply(chat_id, f"🔎 *{symbol}* {interval}\n{text}")
        return {"ok": True}

    if cmd == "/exec_dry":
        if len(parts) < 8:
            await _reply(chat_id, "שימוש: /exec_dry SYMBOL BUY|SELL QTY ENTRY SL TP LEV")
            return {"ok": True}
        _, sym, side, qty, entry, sl, tp, lev = parts[:8]
        body = {
            "symbol": sym.upper(),
            "side": "BUY" if side.upper().startswith("B") else "SELL",
            "qty": float(qty),
            "entry_price": float(entry),
            "sl_price": float(sl),
            "tp_price": float(tp),
            "leverage": int(lev),
            "position_side": "BOTH",
            "reduce_only": False,
            "dry_run": True
        }
        res = await _api_post("/executor/trade", body)
        await _reply(chat_id, f"🧪 *Dry Run*\n`{res}`")
        return {"ok": True}

    if cmd == "/positions":
        res = await _api_get("/executor/open-positions")
        await _reply(chat_id, f"📂 *Open Positions*\n`{res}`")
        return {"ok": True}

    if cmd == "/pnl":
        res = await _api_get("/pnl/summary")
        await _reply(chat_id, f"💹 *PnL Summary*\n`{res}`")
        return {"ok": True}

    if cmd == "/system":
        res = await _api_get("/system/autopilot/status")
        await _reply(chat_id, f"🖥 *System*\n`{res}`")
        return {"ok": True}

    # לא מוכר: נחזיר תפריט
    await _reply_with_keyboard(chat_id, "❓ פקודה לא מזוהה. /help לתפריט.", home_buttons)
    return {"ok": True}





