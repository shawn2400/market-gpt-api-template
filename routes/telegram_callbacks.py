# routes/telegram_callbacks.py
from __future__ import annotations
import os, json, re, time, logging
from typing import Any, Dict, Optional, Tuple

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from telegram import Update

from utils.telegram_notifier import handle_callback_action
from utils.binance_client import place_tp_ladder, set_breakeven_stop

logger = logging.getLogger("algogpt.tg_callbacks")

router = APIRouter(prefix="/telegram/callbacks", tags=["TelegramCallbacks"])

# ===== Config / ENV =====
_TP_LADDER_COOLDOWN = int(os.getenv("TP_LADDER_COOLDOWN_SEC", "60"))
_TP_LADDER_ON_APPROVE = str(os.getenv("TP_LADDER_ON_APPROVE", "1")).lower() in ("1","true","yes","on")
_TELEGRAM_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()

# ===== Internal cooldown to avoid duplicate ladders =====
_LADDER_LAST: Dict[str, float] = {}

def _cooldown_ok(symbol: str) -> bool:
    t = time.time()
    last = _LADDER_LAST.get(symbol, 0.0)
    if t - last >= _TP_LADDER_COOLDOWN:
        _LADDER_LAST[symbol] = t
        return True
    return False

# ===== Heuristics for approve / side detection =====
_APPROVE_HINTS = ("approve", "approved", "✅", "אשר", "אושר", "מאושר", "לאשר")
_SIDE_HINTS = {
    "long": "LONG", "buy": "LONG", "לונג": "LONG", "קנייה": "LONG",
    "short": "SHORT", "sell": "SHORT", "שורט": "SHORT", "מכירה": "SHORT"
}

def _detect_approved(update: Update, result: Any) -> bool:
    # From result dict (preferred)
    if isinstance(result, dict):
        if result.get("approved") is True:
            return True
        act = str(result.get("action", "")).lower()
        if act in ("approve", "approved"):
            return True

    # From callback data JSON or plain text
    try:
        data = update.callback_query.data if update.callback_query else None
        if data:
            try:
                dj = json.loads(data)
                act = str(dj.get("action","")).lower()
                if act in ("approve","approved"):
                    return True
            except Exception:
                s = str(data).lower()
                if any(h in s for h in _APPROVE_HINTS):
                    return True
    except Exception:
        pass

    # From message text
    try:
        text = update.callback_query.message.text if (update and update.callback_query and update.callback_query.message) else ""
        if text and any(h in text.lower() for h in _APPROVE_HINTS):
            return True
    except Exception:
        pass

    return False

def _extract_symbol_side(update: Update, result: Any) -> Tuple[Optional[str], Optional[str]]:
    # Prefer structured result
    if isinstance(result, dict):
        sym = result.get("symbol") or result.get("sym") or result.get("ticker")
        side = result.get("side")
        if isinstance(sym, str) and sym.strip():
            if isinstance(side, str) and side.strip():
                sd = side.strip().upper()
                if sd in ("LONG","SHORT"): return sym.strip().upper(), sd
                if sd in ("BUY","SELL"):    return sym.strip().upper(), ("LONG" if sd=="BUY" else "SHORT")

    # From message text
    text = update.callback_query.message.text if (update and update.callback_query and update.callback_query.message) else ""
    if text:
        m = re.search(r"\b([A-Z]{3,15}USDT)\b", text)
        sym = m.group(1) if m else None
        low = text.lower()
        side = None
        for k, v in _SIDE_HINTS.items():
            if k in low:
                side = v
                break
        if sym and side:
            return sym, side

    # From callback data JSON
    try:
        data = update.callback_query.data if update.callback_query else None
        if data:
            try:
                dj = json.loads(data)
                sym = (dj.get("symbol") or dj.get("sym") or dj.get("ticker") or "").strip().upper()
                sd  = (dj.get("side") or dj.get("position") or dj.get("dir") or "").strip().upper()
                if sym and sd:
                    if sd in ("LONG","SHORT"): return sym, sd
                    if sd in ("BUY","SELL"):   return sym, ("LONG" if sd=="BUY" else "SHORT")
            except Exception:
                pass
    except Exception:
        pass

    return None, None

def _be_immediate_allowed() -> bool:
    # 0 → מותר BE מיידי; 1 (דיפולט) → רק אחרי TP1 (כאן לא)
    return str(os.getenv("TP_BE_ONLY_AFTER_TP1","1")).lower() in ("0","false","no")

def _be_offset_bps_default() -> float:
    try:
        return float(os.getenv("TP_BE_OFFSET_BPS","5"))
    except Exception:
        return 5.0

def _verify_secret(req: Request) -> bool:
    """
    אם הוגדר TELEGRAM_WEBHOOK_SECRET, נוודא התאמה להדר X-Telegram-Bot-Api-Secret-Token.
    אם לא הוגדר, לא נאכוף (תואם ברירת מחדל).
    """
    if not _TELEGRAM_SECRET:
        return True
    try:
        tok = req.headers.get("x-telegram-bot-api-secret-token") or req.headers.get("X-Telegram-Bot-Api-Secret-Token")
        return str(tok or "").strip() == _TELEGRAM_SECRET
    except Exception:
        return False

@router.post("/")
async def telegram_callback_webhook(request: Request):
    # אימות secret (אם קיים)
    if not _verify_secret(request):
        logger.warning("Telegram secret token mismatch")
        return JSONResponse(status_code=403, content={"ok": False, "error": "forbidden"})

    try:
        # Parse update
        try:
            payload = await request.json()
        except Exception:
            body = await request.body()
            payload = json.loads(body)

        update = Update.de_json(payload, None)

        # בצע פעולה ראשית (פתור את ה-callback)
        result = await handle_callback_action(update)

        # הרחבת אוטומציה לאחר אישור
        approved = _detect_approved(update, result)
        ladder_res = None
        be_res = None

        if approved and _TP_LADDER_ON_APPROVE:
            symbol, side = _extract_symbol_side(update, result)
            if symbol and side and _cooldown_ok(symbol):
                # 1) TP Ladder
                try:
                    ladder_res = place_tp_ladder(symbol)
                except Exception as e:
                    logger.warning("TP ladder failed: %s", e)
                    ladder_res = {"ok": False, "error": str(e)}

                # 2) Breakeven מיידי (אם מותר לפי ENV)
                if _be_immediate_allowed():
                    try:
                        be_res = set_breakeven_stop(symbol, offset_bps=_be_offset_bps_default())
                    except Exception as e:
                        logger.warning("BE set failed: %s", e)
                        be_res = {"ok": False, "error": str(e)}

        return JSONResponse(content={"ok": True, "result": result, "ladder": ladder_res, "be": be_res})

    except Exception as e:
        logger.exception("telegram_callback_webhook failed")
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})








