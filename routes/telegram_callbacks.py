# routes/telegram_callbacks.py
from __future__ import annotations
import os, json, re, time, logging, asyncio
from typing import Any, Dict, Optional, Tuple

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from telegram import Update

from utils.telegram_notifier import handle_callback_action
from utils.binance_client import place_tp_ladder, set_breakeven_stop

logger = logging.getLogger("algogpt.tg_callbacks")

router = APIRouter(prefix="/telegram/callbacks", tags=["TelegramCallbacks"])

# === Env ===
_TP_LADDER_ON_APPROVE = str(os.getenv("TP_LADDER_ON_APPROVE", "1")).lower() in ("1", "true", "yes", "on")
_TP_LADDER_COOLDOWN   = int(os.getenv("TP_LADDER_COOLDOWN_SEC", "60"))

# אם 1 → BE מיידי מותר גם בלי TP1; אם 0/False → BE רק אחרי TP1 (Guard/Stream)
def _be_immediate_allowed() -> bool:
    return str(os.getenv("TP_BE_ONLY_AFTER_TP1", "1")).lower() in ("0", "false", "no")

def _be_offset_bps_default() -> float:
    try:
        return float(os.getenv("TP_BE_OFFSET_BPS", "5"))
    except Exception:
        return 5.0

_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
_ADMIN_ONLY     = str(os.getenv("TELEGRAM_ADMIN_ONLY", "0")).lower() in ("1","true","yes","on")
_ADMIN_CHAT_ID  = os.getenv("TELEGRAM_CHAT_ID", "").strip()

# קירור פנימי למניעת כפילות הקמות
_LADDER_LAST: Dict[str, float] = {}

def _cooldown_ok(symbol: str) -> bool:
    t = time.time()
    last = _LADDER_LAST.get(symbol, 0.0)
    if t - last >= _TP_LADDER_COOLDOWN:
        _LADDER_LAST[symbol] = t
        return True
    return False

# רמזי אישור
_APPROVE_HINTS = ("approve", "approved", "✅", "אשר", "אושר", "מאושר", "לאשר")
_SIDE_HINTS = {
    "long": "LONG", "buy": "LONG", "לונג": "LONG", "קנייה": "LONG",
    "short": "SHORT", "sell": "SHORT", "שורט": "SHORT", "מכירה": "SHORT",
}

def _verify_secret(req: Request) -> bool:
    """אם הוגדר SECRET ב-ENV — דרוש התאמה ל-Header של טלגרם."""
    if not _WEBHOOK_SECRET:
        return True
    got = req.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    return got == _WEBHOOK_SECRET

def _extract_chat_id(update: Update) -> Optional[str]:
    try:
        if update and update.callback_query and update.callback_query.message and update.callback_query.message.chat:
            return str(update.callback_query.message.chat.id)
    except Exception:
        pass
    return None

def _enforce_admin(update: Update) -> bool:
    """אם ADMIN_ONLY=1, ודא שהאירוע מגיע מה-CHAT_ID המורשה."""
    if not _ADMIN_ONLY or not _ADMIN_CHAT_ID:
        return True
    cid = _extract_chat_id(update)
    if cid and cid == _ADMIN_CHAT_ID:
        return True
    return False

def _detect_approved(update: Update, result: Any) -> bool:
    # דרך האובייקט שהחזיר ה-notifier
    if isinstance(result, dict):
        if result.get("approved") is True:
            return True
        act = str(result.get("action", "")).lower()
        if act in ("approve", "approved"):
            return True

    # דרך הנתונים הגולמיים של callback
    try:
        data = update.callback_query.data if update.callback_query else None
        if data:
            # נסה JSON תחילה
            try:
                dj = json.loads(data)
                act = str(dj.get("action", "")).lower()
                if act in ("approve", "approved"):
                    return True
            except Exception:
                s = str(data)
                s_low = s.lower()
                # בדיקה על טקסט ותו ה-✅ עצמו
                if any(h.lower() in s_low for h in _APPROVE_HINTS if isinstance(h, str)) or "✅" in s:
                    return True
    except Exception:
        pass

    # Fallback לטקסט ההודעה
    text = update.callback_query.message.text if (update and update.callback_query and update.callback_query.message) else ""
    if text:
        low = text.lower()
        if any(h.lower() in low for h in _APPROVE_HINTS if isinstance(h, str)) or "✅" in text:
            return True

    return False

def _extract_symbol_side(update: Update, result: Any) -> Tuple[Optional[str], Optional[str]]:
    # קודם מהתוצאה עצמה
    if isinstance(result, dict):
        sym = result.get("symbol") or result.get("sym") or result.get("ticker")
        side = result.get("side")
        if isinstance(sym, str) and sym.strip():
            if isinstance(side, str) and side.strip():
                sd = side.strip().upper()
                if sd in ("LONG", "SHORT"):
                    return sym.strip().upper(), sd
                if sd in ("BUY", "SELL"):
                    return sym.strip().upper(), ("LONG" if sd == "BUY" else "SHORT")

    # מטקסט ההודעה
    text = update.callback_query.message.text if (update and update.callback_query and update.callback_query.message) else ""
    if text:
        # סמלים נפוצים: USDT/FDUSD/USDC/BUSD
        m = re.search(r"\b([A-Z]{3,15}(?:USDT|FDUSD|USDC|BUSD))\b", text)
        sym = m.group(1).upper() if m else None
        low = text.lower()
        side = None
        for k, v in _SIDE_HINTS.items():
            if k in low:
                side = v
                break
        if sym and side:
            return sym, side

    # מתוך data של callback
    try:
        data = update.callback_query.data if update.callback_query else None
        if data:
            try:
                dj = json.loads(data)
                sym = (dj.get("symbol") or dj.get("sym") or dj.get("ticker") or "").strip().upper()
                sd  = (dj.get("side") or dj.get("position") or dj.get("dir") or "").strip().upper()
                if sym and sd:
                    if sd in ("LONG", "SHORT"):
                        return sym, sd
                    if sd in ("BUY", "SELL"):
                        return sym, ("LONG" if sd == "BUY" else "SHORT")
            except Exception:
                pass
    except Exception:
        pass

    return None, None

@router.post("/")
async def telegram_callback_webhook(request: Request):
    # אימות Secret (אם הופעל)
    if not _verify_secret(request):
        return JSONResponse(status_code=403, content={"ok": False, "error": "invalid webhook secret"})

    try:
        body = await request.body()
        update = Update.de_json(json.loads(body), None)

        # בדיקת admin (אם הופעל)
        if not _enforce_admin(update):
            return JSONResponse(status_code=403, content={"ok": False, "error": "unauthorized chat"})

        # העיבוד הקיים שלך
        result = await handle_callback_action(update)

        approved = _detect_approved(update, result)
        ladder = None
        be_res = None

        if approved and _TP_LADDER_ON_APPROVE:
            symbol, side = _extract_symbol_side(update, result)
            if symbol and side and _cooldown_ok(symbol):
                try:
                    # הרצה ב-threadpool כדי לא לחנוק את event loop
                    ladder = await asyncio.to_thread(place_tp_ladder, symbol)
                except Exception as e:
                    logger.warning("TP ladder failed: %s", e)
                    ladder = {"ok": False, "error": str(e)}

                # BE מיידי רק אם הותר דרך ENV
                if _be_immediate_allowed():
                    try:
                        be_res = await asyncio.to_thread(
                            set_breakeven_stop, symbol, _be_offset_bps_default()
                        )
                    except Exception as e:
                        logger.warning("BE set failed: %s", e)
                        be_res = {"ok": False, "error": str(e)}

        return JSONResponse(content={"ok": True, "result": result, "ladder": ladder, "be": be_res})
    except Exception as e:
        logger.exception("telegram_callback_webhook failed")
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})





