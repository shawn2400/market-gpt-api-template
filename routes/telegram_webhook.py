# routes/telegram_webhook.py
from __future__ import annotations
import os, logging
from typing import Any, Dict
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
import httpx

logger = logging.getLogger("algogpt.telegram.webhook")
router = APIRouter(prefix="/telegram", tags=["Telegram"])

TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ADMIN_ONLY = str(os.getenv("TELEGRAM_ADMIN_ONLY", "1")).lower() in ("1","true","yes","on")
ADMIN_IDS = {s.strip() for s in (os.getenv("TELEGRAM_ADMIN_IDS","") or "").split(",") if s.strip()}

def _allowed_user(uid: int) -> bool:
    if not ADMIN_ONLY:
        return True
    return str(uid) in ADMIN_IDS

async def _reply(chat_id: int, text: str, kbd: list[list[str]] | None = None):
    if not TG_TOKEN:
        return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload: Dict[str, Any] = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown", "disable_web_page_preview": True}
    if kbd:
        payload["reply_markup"] = {"keyboard": kbd, "resize_keyboard": True, "one_time_keyboard": False}
    try:
        async with httpx.AsyncClient(timeout=8.0) as cli:
            await cli.post(url, json=payload)
    except Exception as e:
        logger.warning(f"[tg] sendMessage failed: {e}")

async def _api_get(path: str) -> Dict[str, Any]:
    url = path if path.startswith("http") else f"http://127.0.0.1:8000{path}"
    headers = {}
    tok = os.getenv("API_BEARER_TOKEN","").strip()
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as cli:
            r = await cli.get(url, headers=headers)
            r.raise_for_status()
            return r.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}

async def _api_post(path: str, body: Dict[str, Any]) -> Dict[str, Any]:
    url = path if path.startswith("http") else f"http://127.0.0.1:8000{path}"
    headers = {"Content-Type":"application/json"}
    tok = os.getenv("API_BEARER_TOKEN","").strip()
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    try:
        async with httpx.AsyncClient(timeout=12.0) as cli:
            r = await cli.post(url, json=body, headers=headers)
            r.raise_for_status()
            return r.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}

HELP_TEXT = (
    "🤖 *AlgoGPT Bot* — Help / עזרה\n\n"
    "• /help — עזרה\n"
    "• /status — סטטוס\n"
    "• /positions — פוזיציות פתוחות\n"
    "• /pnl — סיכום PnL\n"
    "• /scan <SYMBOL> <15m|1h|4h> — סריקה\n"
    "• /exec_dry SYMBOL BUY|SELL QTY ENTRY SL TP LEV — סימולציה\n"
    "• /approve <TRADE_ID> — אישור טרייד (אם יש תור)\n"
    "• /system — עומסים וניטור\n"
)

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
    user = msg.get("from") or {}
    uid = int(user.get("id") or 0)
    text = (msg.get("text") or "").strip()

    if not chat_id or not uid:
        return {"ok": True}
    if not _allowed_user(uid):
        await _reply(chat_id, "⛔️ אין לך הרשאה להשתמש בבוט זה.")
        return {"ok": True}

    kbd = [
        ["/status", "/positions", "/pnl"],
        ["/scan BTCUSDT 15m", "/scan ETHUSDT 1h"],
        ["/system", "/help"]
    ]

    if not text or text in ("/start", "/help"):
        await _reply(chat_id, HELP_TEXT, kbd)
        return {"ok": True}

    parts = text.split()
    cmd = parts[0].lower()

    if cmd == "/status":
        s1 = await _api_get("/executor/status")
        s2 = await _api_get("/system/autopilot/status")
        await _reply(chat_id, f"📊 *Status*\n`{s1}`\n`{s2}`")
        return {"ok": True}

    if cmd == "/positions":
        res = await _api_get("/executor/open-positions")
        await _reply(chat_id, f"📂 *Open Positions*\n`{res}`")
        return {"ok": True}

    if cmd == "/pnl":
        res = await _api_get("/pnl/summary")
        await _reply(chat_id, f"💹 *PnL Summary*\n`{res}`")
        return {"ok": True}

    if cmd == "/scan":
        if len(parts) < 2:
            await _reply(chat_id, "שימוש: /scan SYMBOL [15m|1h|4h]")
            return {"ok": True}
        sym = parts[1].upper()
        interval = parts[2] if len(parts) > 2 else "15m"
        res = await _api_get(f"/ai/analyze?symbol={sym}&interval={interval}")
        text = res.get("analysis") or str(res)
        await _reply(chat_id, f"🔎 *{sym}* {interval}\n{text}")
        return {"ok": True}

    if cmd == "/exec_dry":
        if len(parts) < 8:
            await _reply(chat_id, "שימוש: /exec_dry SYMBOL BUY|SELL QTY ENTRY SL TP LEV")
            return {"ok": True}
        _, sym, side, qty, entry, sl, tp, lev = parts[:8]
        res = await _api_post("/trade/execute", {
            "symbol": sym.upper(),
            "side": "BUY" if side.upper().startswith("B") else "SELL",
            "budget": 0,  # אם מסופק quantity, ה-budget לא נדרש בפועל
            "leverage": int(lev),
            "entry": float(entry),
            "sl": float(sl),
            "tp": float(tp),
            "dry_run": True,
            "quantity": float(qty)
        })
        await _reply(chat_id, f"🧪 *Dry Run*\n`{res}`")
        return {"ok": True}

    if cmd == "/system":
        res = await _api_get("/system/autopilot/status")
        await _reply(chat_id, f"🖥 *System*\n`{res}`")
        return {"ok": True}

    await _reply(chat_id, "❓ פקודה לא מזוהה. /help לתפריט.", kbd)
    return {"ok": True}





